#!/usr/bin/env python3
"""Private local interface for stable-diffusion.cpp; Pillow finalizes exact ratios."""
from __future__ import annotations

import argparse
import datetime as dt
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import webbrowser

from PIL import Image

APP_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.2"
RESOLUTION_SHORT_SIDES = (1024, 2048, 3072, 4096)
MAX_DIMENSION = 16384
MAX_OUTPUT_PIXELS = 64 * 1024 * 1024
MAX_UPLOAD = 32 * 1024 * 1024
MAX_JSON = 64 * 1024
JOB_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-f0-9]{12}$")
UPLOAD_ID = re.compile(r"^[a-f0-9]{32}\.(png|jpg)$")
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def atomic_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def image_info(data):
    """Recognize the formats sd-cli decodes; the browser converts WebP to PNG."""
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return "png", *struct.unpack(">II", data[16:24])
    if data.startswith(b"\xff\xd8\xff"):
        i = 2
        while i + 4 <= len(data):
            if data[i] != 0xff:
                i += 1
                continue
            while i < len(data) and data[i] == 0xff:
                i += 1
            if i >= len(data):
                break
            marker = data[i]
            i += 1
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                continue
            if i + 2 > len(data):
                break
            size = int.from_bytes(data[i:i + 2], "big")
            if size < 2 or i + size > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and size >= 7:
                height, width = struct.unpack(">HH", data[i + 3:i + 7])
                return "jpg", width, height
            i += size
    raise ValueError("Image illisible. Choisissez un fichier PNG, JPEG ou WebP dans l’interface.")


def diagnose(text):
    lower = text.lower()
    error_lines = "\n".join(line for line in lower.splitlines() if re.search(r"\b(error|failed|fatal|exception|assert|cannot|unable|mismatch|incompatible|invalid)\b", line))
    if any(word in lower for word in ("out of memory", "cuda_error_out_of_memory", "failed to allocate", "not enough memory", "bad_alloc")):
        return "Mémoire insuffisante : fermez les autres applications utilisant le GPU, puis revenez au palier 1K. Les photos très panoramiques demandent davantage de mémoire. Les options d’économie mémoire se règlent dans config.json."
    if any(word in lower for word in ("no kernel image", "invalid device function", "cuda driver version", "cudart", "cublas", "cuda initialization")):
        return "Erreur CUDA : vérifiez le pilote NVIDIA et la présence des DLL du paquet CUDA de sd-cli à côté de l’exécutable. Consultez aussi diagnostics.json."
    if any(word in error_lines for word in ("mmproj", "clip_vision", "llm_vision", "vision model", "projector")):
        return "Erreur du module de vision : vérifiez mmproj-F16.gguf, l’encodeur Qwen3-VL-8B et la version de sd-cli. Le journal complet conserve le message d’origine."
    if any(word in lower for word in ("unknown argument", "unrecognized", "unknown option")):
        return "Option inconnue : la version de sd-cli et les options de config.json doivent correspondre. Consultez command.json et engine.log."
    if any(word in lower for word in ("failed to load", "cannot open", "not found", "no such file", "invalid model")):
        return "Chargement impossible : vérifiez les quatre fichiers de modèle, leurs chemins dans config.json et la fin de leurs téléchargements."
    return "Le moteur a échoué. Le journal complet, la commande et les diagnostics NVIDIA sont enregistrés dans le dossier de cet essai."


class App:
    def __init__(self, root, port):
        self.root = Path(root).resolve()
        self.port = port
        self.data = self.root / "data"
        self.results = self.data / "results"
        self.uploads = self.data / "inputs"
        self.logs = self.data / "logs"
        for folder in (self.results, self.uploads, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_hex(32)
        self.lock = threading.RLock()
        self.active = None
        self.process = None
        self.cancel_event = threading.Event()
        self.shutting_down = False
        self.jobs = {}
        self.logger = logging.getLogger(f"qwen-local.{id(self)}")
        self.logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(self.logs / "interface.log", maxBytes=4 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.addHandler(handler)
        self.logger.addHandler(logging.StreamHandler())
        self._load_history()

    def _load_history(self):
        for folder in sorted(self.results.iterdir(), reverse=True):
            if not folder.is_dir() or not JOB_ID.fullmatch(folder.name):
                continue
            try:
                data = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
                if data.get("id") != folder.name:
                    continue
                if data.get("status") not in TERMINAL:
                    data.update(status="interrupted", ended_at=now(), error="L’interface a été arrêtée pendant cet essai. Relancez-le si nécessaire.")
                    atomic_json(folder / "metadata.json", data)
                self.jobs[data["id"]] = data
            except (OSError, ValueError, KeyError):
                self.logger.exception("Lecture d’un essai ignorée : %s", folder.name)

    def config(self):
        try:
            cfg = json.loads((self.root / "config.json").read_text(encoding="utf-8-sig"))
            if not isinstance(cfg, dict):
                raise ValueError("objet JSON attendu")
            return cfg
        except (OSError, ValueError) as exc:
            raise ValueError(f"config.json absent ou invalide : {exc}") from exc

    def configured_path(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError("Chemin de modèle ou de moteur manquant dans config.json.")
        path = Path(value)
        return (path if path.is_absolute() else self.root / path).resolve()

    def readiness(self):
        try:
            cfg = self.config()
            files = [("sd-cli CUDA", cfg.get("sd_cli"))]
            files.extend((key, cfg.get("models", {}).get(key)) for key in ("diffusion", "llm", "vision", "vae"))
            checks = []
            for name, value in files:
                path = self.configured_path(value)
                checks.append({"name": name, "filename": path.name, "present": path.is_file(), "bytes": path.stat().st_size if path.is_file() else 0})
            return {"ready": all(item["present"] and item["bytes"] > 0 for item in checks), "files": checks, "error": None}
        except (ValueError, OSError, AttributeError) as exc:
            return {"ready": False, "files": [], "error": str(exc)}

    def state(self):
        with self.lock:
            return {"csrf_token": self.token, "active_job": self.active, "root": str(self.root), "engine": self.readiness(), "jobs": [self.public_job(x) for x in sorted(self.jobs.values(), key=lambda j: j["id"], reverse=True)[:100]]}

    def public_job(self, job, with_log=False):
        data = dict(job)
        folder = self.results / job["id"]
        data["image_url"] = f"/api/jobs/{job['id']}/output.png" if job.get("status") == "succeeded" and (folder / "output.png").is_file() else None
        data["input_url"] = f"/api/jobs/{job['id']}/input{job.get('input_extension', '.png')}" if job.get("input_extension") else None
        data["log_url"] = f"/api/jobs/{job['id']}/engine.log"
        data["metadata_url"] = f"/api/jobs/{job['id']}/metadata.json"
        data["command_url"] = f"/api/jobs/{job['id']}/command.json"
        data["diagnostics_url"] = f"/api/jobs/{job['id']}/diagnostics.json"
        if with_log:
            path = folder / "engine.log"
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 48000))
                    data["log_tail"] = stream.read().decode("utf-8", errors="replace")
            except OSError:
                data["log_tail"] = ""
        return data

    def persist(self, job):
        atomic_json(self.results / job["id"] / "metadata.json", job)

    def upload(self, data):
        extension, width, height = image_info(data)
        if not (1 <= width <= 16384 and 1 <= height <= 16384 and width * height <= 100_000_000):
            raise ValueError("Image trop grande : maximum 16 384 pixels par côté et 100 mégapixels.")
        name = secrets.token_hex(16) + "." + extension
        (self.uploads / name).write_bytes(data)
        return {"upload_id": name, "width": width, "height": height, "bytes": len(data)}

    def validate(self, data):
        if not isinstance(data, dict):
            raise ValueError("Requête JSON invalide.")
        mode = data.get("mode", "edit")
        if mode not in ("edit", "generate"):
            raise ValueError("Mode invalide.")
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
            raise ValueError("Saisissez une consigne de 1 à 12 000 caractères.")
        values = {"mode": mode, "prompt": prompt.strip()}
        for key, default, lo, hi in (("width", 1024, 256, MAX_DIMENSION), ("height", 1024, 256, MAX_DIMENSION), ("steps", 20, 1, 100)):
            value = data.get(key, default)
            if type(value) is not int or not lo <= value <= hi or (key != "steps" and value % 32):
                raise ValueError(f"{key} : entier de {lo} à {hi}" + (", multiple de 32." if key != "steps" else "."))
            values[key] = value
        if values["width"] * values["height"] > MAX_OUTPUT_PIXELS:
            raise ValueError("Résolution de sortie trop grande : maximum 64 × 1 024 × 1 024 pixels. Choisissez une résolution inférieure.")
        if ("output_width" in data) != ("output_height" in data):
            raise ValueError("Les dimensions finales output_width et output_height doivent être fournies ensemble.")
        for axis in ("width", "height"):
            final = data.get("output_" + axis, values[axis])
            if type(final) is not int or not 256 <= final <= MAX_DIMENSION or not 0 <= values[axis] - final < 32:
                raise ValueError(f"output_{axis} : entier d’au moins 256 pixels, égal à la dimension du moteur ou inférieur de 31 pixels maximum.")
            values["output_" + axis] = final
        cfg = data.get("cfg", 6)
        if isinstance(cfg, bool) or not isinstance(cfg, (int, float)) or not 1 <= cfg <= 20:
            raise ValueError("Le guidage CFG doit être compris entre 1 et 20.")
        values["cfg"] = cfg
        seed = data.get("seed", 42)
        if seed is None or seed == -1:
            seed = secrets.randbelow(2**31)
        if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
            raise ValueError("La graine doit être comprise entre 0 et 2 147 483 647, ou -1 pour une graine aléatoire.")
        values["seed"] = seed
        if mode == "edit":
            upload_id = data.get("upload_id", "")
            if not isinstance(upload_id, str) or not UPLOAD_ID.fullmatch(upload_id) or not (self.uploads / upload_id).is_file():
                raise ValueError("Ajoutez une photo avant de lancer la retouche.")
            values["upload_id"] = upload_id
        return values

    def build_command(self, job, folder):
        cfg = self.config()
        models = cfg.get("models", {})
        command = [str(self.configured_path(cfg.get("sd_cli")))]
        flags = {"diffusion": "--diffusion-model", "llm": "--llm", "vision": "--llm_vision", "vae": "--vae"}
        for key, flag in flags.items():
            command += [flag, str(self.configured_path(models.get(key)))]
        command += ["-p", job["prompt"], "-W", str(job["width"]), "-H", str(job["height"]), "--steps", str(job["steps"]), "--cfg-scale", str(job["cfg"]), "-s", str(job["seed"]), "--sampling-method", "euler", "-o", str(folder / "output.png")]
        if job["mode"] == "edit":
            command += ["-r", str(folder / ("input" + job["input_extension"]))]
            if (job.get("output_width", job["width"]), job.get("output_height", job["height"])) != (job["width"], job["height"]):
                command += ["--image-preprocess", f"target=ref,index=0,mode=fit-pad,width={job['width']},height={job['height']},anchor=center,filter=lanczos"]
        extra = cfg.get("extra_args", [])
        if not isinstance(extra, list) or any(not isinstance(x, str) for x in extra):
            raise ValueError("extra_args doit être une liste de chaînes dans config.json.")
        command += extra
        return command

    def create_job(self, data):
        values = self.validate(data)
        with self.lock:
            if self.shutting_down:
                raise RuntimeError("L’interface est en cours d’arrêt.")
            if self.active:
                raise RuntimeError("Un essai est déjà en cours. Attendez sa fin ou annulez-le.")
            readiness = self.readiness()
            if not readiness["ready"]:
                missing = ", ".join(x["name"] for x in readiness["files"] if not x["present"] or not x["bytes"])
                raise ValueError(readiness["error"] or f"Installation incomplète : {missing}.")
            job_id = dt.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(6)
            folder = self.results / job_id
            folder.mkdir()
            upload_id = values.pop("upload_id", None)
            job = {"id": job_id, **values, "status": "queued", "created_at": now(), "started_at": None, "ended_at": None, "elapsed_seconds": None, "exit_code": None, "error": None, "progress": None}
            if upload_id:
                job["input_extension"] = Path(upload_id).suffix
                shutil.copyfile(self.uploads / upload_id, folder / ("input" + job["input_extension"]))
            command = self.build_command(job, folder)
            atomic_json(folder / "command.json", {"argv": command, "cwd": str(Path(command[0]).parent), "created_at": now()})
            (folder / "engine.log").write_text("", encoding="utf-8")
            self.persist(job)
            self.jobs[job_id] = job
            self.active = job_id
            self.cancel_event.clear()
            threading.Thread(target=self.run_job, args=(job, command, folder), name=f"qwen-{job_id}", daemon=True).start()
            return self.public_job(job)

    def nvidia_diagnostic(self):
        command = ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,memory.free", "--format=csv"]
        result = {"captured_at": now(), "python": sys.version, "platform": sys.platform, "nvidia_command": command}
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12, creationflags=CREATE_NO_WINDOW)
            result.update(nvidia_exit_code=completed.returncode, nvidia_stdout=completed.stdout, nvidia_stderr=completed.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["nvidia_error"] = str(exc)
        return result

    def finalize_output(self, job, folder):
        """Remove only alignment padding; never resize or distort the generated pixels."""
        output = folder / "output.png"
        engine_size = (job["width"], job["height"])
        final_size = (job.get("output_width", job["width"]), job.get("output_height", job["height"]))
        with Image.open(output) as generated:
            if generated.size != engine_size:
                raise ValueError(f"Dimensions inattendues du moteur : {generated.width} × {generated.height} ; attendu {engine_size[0]} × {engine_size[1]}.")
            generated.load()
            if final_size == engine_size:
                return
            left = (engine_size[0] - final_size[0]) // 2
            top = (engine_size[1] - final_size[1]) // 2
            cropped = generated.crop((left, top, left + final_size[0], top + final_size[1]))
            # Preserve the original generated image and publish the crop atomically.
            shutil.copyfile(output, folder / "engine-output.png")
            temporary = folder / "output-final.tmp"
            cropped.save(temporary, format="PNG")
        temporary.replace(output)
        job["alignment_crop"] = {"left": left, "top": top, "right": engine_size[0] - final_size[0] - left, "bottom": engine_size[1] - final_size[1] - top}
        self.logger.info("Essai %s : retrait des marges d’alignement %s vers %s", job["id"], engine_size, final_size)

    def run_job(self, job, command, folder):
        started = time.monotonic()
        try:
            with self.lock:
                job.update(status="preparing", started_at=now())
                self.persist(job)
            atomic_json(folder / "diagnostics.json", self.nvidia_diagnostic())
            with (folder / "engine.log").open("ab", buffering=0) as logfile:
                logfile.write(f"[{now()}] Essai local {job['id']}\n".encode("utf-8"))
                with self.lock:
                    if self.cancel_event.is_set():
                        job["status"] = "cancelled"
                        return
                    self.process = subprocess.Popen(command, cwd=str(Path(command[0]).parent), stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW, shell=False)
                    job.update(status="running", pid=self.process.pid)
                    self.persist(job)
                while True:
                    with self.lock:
                        process = self.process
                    code = process.poll()
                    if code is not None:
                        break
                    if self.cancel_event.wait(0.6):
                        self.terminate(process)
                    # sd-cli renders progress with carriage returns; keep it byte-for-byte in the log.
                with self.lock:
                    job["exit_code"] = code
                    if self.cancel_event.is_set():
                        job["status"] = "cancelled"
                    elif code == 0 and (folder / "output.png").is_file() and (folder / "output.png").stat().st_size > 24:
                        try:
                            self.finalize_output(job, folder)
                            job["status"] = "succeeded"
                        except (ValueError, OSError) as exc:
                            job.update(status="failed", error=f"Sortie du moteur invalide : {exc}")
                    else:
                        tail = self.public_job(job, True)["log_tail"]
                        job.update(status="failed", error=diagnose(tail) if code else "Le moteur a terminé sans produire output.png. Consultez engine.log.")
                logfile.write(f"\n[{now()}] Fin : {job['status']} ; code = {code}\n".encode("utf-8"))
        except Exception as exc:
            self.logger.exception("Échec essai %s", job["id"])
            with self.lock:
                process = self.process
            if process and process.poll() is None:
                self.terminate(process)
            with self.lock:
                job.update(status="cancelled" if self.cancel_event.is_set() else "failed", error=f"Impossible de lancer ou de suivre sd-cli : {exc}")
            try:
                with (folder / "engine.log").open("a", encoding="utf-8") as stream:
                    stream.write(f"\nErreur de l’interface : {type(exc).__name__}: {exc}\n")
            except OSError:
                pass
        finally:
            with self.lock:
                job.update(ended_at=now(), elapsed_seconds=round(time.monotonic() - started, 2))
                try:
                    self.persist(job)
                except OSError:
                    self.logger.exception("Impossible d’enregistrer la fin de l’essai %s", job["id"])
                finally:
                    self.process = None
                    self.active = None
            self.logger.info("Essai %s : %s en %.1f s", job["id"], job["status"], job["elapsed_seconds"])

    @staticmethod
    def terminate(process):
        try:
            process.terminate()
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)
        except (OSError, ProcessLookupError):
            pass

    def cancel(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            if self.active == job_id:
                self.cancel_event.set()
                self.jobs[job_id]["status"] = "cancelling"
                self.persist(self.jobs[job_id])
            return self.public_job(self.jobs[job_id])

    def close(self):
        with self.lock:
            self.shutting_down = True
            self.cancel_event.set()
            process = self.process
        if process and process.poll() is None:
            self.terminate(process)

    def request_shutdown(self):
        """Reserve an idle shutdown atomically, without cancelling a running job."""
        with self.lock:
            if self.active or (self.process and self.process.poll() is None):
                raise RuntimeError("Un essai est en cours. Attendez sa fin avant de redémarrer l’interface.")
            self.shutting_down = True
        self.logger.info("Arrêt de l’interface demandé par la session locale.")


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = f"QwenLocal/{APP_VERSION}"

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        if self.command != "GET" or args[1] != "200":
            self.app.logger.info("HTTP %s %s", self.address_string(), fmt % args)

    def trusted_request(self, mutation=False):
        hosts = {f"127.0.0.1:{self.app.port}", f"localhost:{self.app.port}"}
        if self.headers.get("Host", "").lower() not in hosts:
            self.json_response(403, {"error": "Hôte refusé. Ouvrez l’adresse locale de l’interface."})
            return False
        origin = self.headers.get("Origin")
        if (origin and origin.lower() not in {"http://" + x for x in hosts}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.json_response(403, {"error": "Origine externe refusée."})
            return False
        if mutation and (not origin or not hmac.compare_digest(self.headers.get("X-Qwen-Token", ""), self.app.token)):
            self.json_response(403, {"error": "Session locale invalide. Rechargez la page."})
            return False
        return True

    def standard_headers(self, content_type, length):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()

    def json_response(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.standard_headers("application/json; charset=utf-8", len(data))
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def file_response(self, path, content_type=None, download=False):
        if not path.is_file():
            self.json_response(404, {"error": "Fichier introuvable."})
            return
        try:
            data = path.read_bytes()
            self.send_response(200)
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.standard_headers(content_type or mimetypes.guess_type(path)[0] or "application/octet-stream", len(data))
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.trusted_request():
            return
        path = urlsplit(self.path).path
        try:
            static = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/resolution.js": ("resolution.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in static:
                name, content_type = static[path]
                self.file_response(APP_DIR / name, content_type)
            elif path == "/api/status":
                self.json_response(200, {"app": "Qwen-Image-Local", "version": APP_VERSION, "status": "ok", "active_job": self.app.active, "engine": self.app.readiness(), "resolution_short_sides": RESOLUTION_SHORT_SIDES, "max_dimension": MAX_DIMENSION, "max_pixels": MAX_OUTPUT_PIXELS, "exact_output_dimensions": True, "shutdown_supported": True})
            elif path == "/api/state":
                self.json_response(200, self.app.state())
            elif path.startswith("/api/jobs/"):
                parts = path.split("/")
                if len(parts) not in (4, 5) or not JOB_ID.fullmatch(parts[3]):
                    raise KeyError(path)
                job_id = parts[3]
                with self.app.lock:
                    job = self.app.jobs[job_id]
                    if len(parts) == 4:
                        data = self.app.public_job(job, True)
                        self.json_response(200, data)
                        return
                filename = parts[4]
                if filename not in {"output.png", "engine-output.png", "input.png", "input.jpg", "engine.log", "metadata.json", "command.json", "diagnostics.json"}:
                    raise KeyError(path)
                self.file_response(self.app.results / job_id / filename, "text/plain; charset=utf-8" if filename.endswith(".log") else None, filename.endswith((".log", ".json")))
            else:
                self.json_response(404, {"error": "Route inconnue."})
        except KeyError:
            self.json_response(404, {"error": "Essai ou fichier introuvable."})
        except Exception:
            self.app.logger.exception("Erreur GET %s", path)
            self.json_response(500, {"error": "Erreur de l’interface. Consultez data/logs/interface.log."})

    def read_body(self, limit):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfert segmenté non accepté.")
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdecimal() or not 0 < int(raw_length) <= limit:
            raise ValueError(f"Taille du contenu invalide (maximum {limit // 1024} Ko).")
        self.connection.settimeout(30)
        length = int(raw_length)
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("Envoi incomplet.")
        return data

    def do_POST(self):
        if not self.trusted_request(mutation=True):
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/uploads":
                self.json_response(201, self.app.upload(self.read_body(MAX_UPLOAD)))
                return
            data = json.loads(self.read_body(MAX_JSON))
            if path == "/api/jobs":
                self.json_response(202, self.app.create_job(data))
            elif path == "/api/shutdown":
                if not isinstance(data, dict):
                    raise ValueError("Requête JSON invalide.")
                self.app.request_shutdown()
                self.json_response(200, {"status": "shutting_down"})
                # shutdown() must run outside the serve_forever() thread.
                threading.Thread(target=self.server.shutdown, name="qwen-shutdown", daemon=True).start()
            elif re.fullmatch(r"/api/jobs/[0-9]{8}T[0-9]{6}-[a-f0-9]{12}/cancel", path):
                self.json_response(200, self.app.cancel(path.split("/")[3]))
            else:
                self.json_response(404, {"error": "Route inconnue."})
        except (ValueError, UnicodeError) as exc:
            self.app.logger.warning("Requête refusée %s : %s", path, exc)
            self.json_response(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.json_response(409, {"error": str(exc)})
        except KeyError:
            self.json_response(404, {"error": "Essai introuvable."})
        except Exception:
            self.app.logger.exception("Erreur POST %s", path)
            self.json_response(500, {"error": "Erreur de l’interface. Consultez data/logs/interface.log."})


def main():
    parser = argparse.ArgumentParser(description="Interface locale Qwen-Image-2.1")
    parser.add_argument("--root", type=Path, default=APP_DIR.parent)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Le port doit être compris entre 1024 et 65535.")
    try:
        httpd = LocalServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        print(f"Le port {args.port} est déjà utilisé ou indisponible. Une interface est peut-être déjà ouverte. ({exc})", file=sys.stderr)
        return 1
    # Only the process that owns the local port may recover unfinished history.
    try:
        app = App(args.root, args.port)
    except Exception:
        httpd.server_close()
        raise
    httpd.app = app
    url = f"http://127.0.0.1:{args.port}"
    app.logger.info("Interface démarrée : %s ; dossier %s", url, app.root)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        app.logger.info("Arrêt de l’interface demandé.")
    finally:
        app.close()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
