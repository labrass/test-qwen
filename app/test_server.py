"""Isolated HTTP/process regression tests; no model, internet or GPU is used."""
import base64
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from PIL import Image

import server


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0dEAAAAASUVORK5CYII=")


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix=".interface-test-", dir=server.APP_DIR)
        cls.root = Path(cls.temp.name).resolve()
        assert cls.root.parent == server.APP_DIR
        cls.fake = cls.root / "fake_cli.py"
        cls.fake.write_text('''import pathlib, sys, time
from PIL import Image
args=sys.argv[1:]
prompt=args[args.index('-p')+1]
print('CUDA0: fake diagnostic for isolated tests',flush=True)
if prompt=='slow': time.sleep(30)
if prompt=='fail':
    print('CUDA out of memory',flush=True)
    raise SystemExit(7)
out=pathlib.Path(args[args.index('-o')+1])
size=(int(args[args.index('-W')+1]),int(args[args.index('-H')+1]))
if prompt=='wrong-size': size=(1,1)
image=Image.new('RGB',size,(12,34,56))
if size[0]>5: image.putpixel((5,0),(210,31,47))
image.save(out)
print('test output saved',flush=True)
''', encoding="utf-8")
        models = {}
        for name in ("diffusion", "llm", "vision", "vae"):
            path = cls.root / (name + ".fixture")
            path.write_bytes(b"fixture")
            models[name] = path.name
        server.atomic_json(cls.root / "config.json", {"sd_cli": sys.executable, "models": models, "extra_args": ["--backend", "cuda0"]})
        cls.httpd = server.LocalServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.app = server.App(cls.root, cls.port)
        cls.httpd.app = cls.app
        original = cls.app.build_command
        cls.app.build_command = lambda job, folder: (lambda command: [command[0], str(cls.fake), *command[1:]])(original(job, folder))
        cls.app.nvidia_diagnostic = lambda: {"nvidia_stdout": "isolated test fixture"}
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        for handler in cls.app.logger.handlers:
            handler.close()
        cls.temp.cleanup()

    def request(self, method, path, data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        request_headers = {"Origin": f"http://127.0.0.1:{self.port}", "X-Qwen-Token": self.app.token}
        if headers:
            request_headers.update(headers)
        body = raw if raw is not None else json.dumps(data).encode() if data is not None else None
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body, request_headers)
        response = connection.getresponse()
        payload = response.read()
        status = response.status
        ctype = response.getheader("Content-Type", "")
        connection.close()
        return status, json.loads(payload) if "json" in ctype else payload

    def create(self, prompt="ok", **options):
        status, data = self.request("POST", "/api/jobs", {"mode": "generate", "prompt": prompt, **options})
        self.assertEqual(status, 202, data)
        return data

    def wait_done(self, job_id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            _, job = self.request("GET", "/api/jobs/" + job_id)
            if job["status"] in server.TERMINAL and job.get("ended_at"):
                return job
            time.sleep(0.05)
        self.fail("Fake job did not terminate")

    def test_01_static_and_health(self):
        for path in ("/", "/app.js", "/style.css", "/api/state", "/api/status"):
            self.assertEqual(self.request("GET", path)[0], 200, path)
        self.assertTrue(self.request("GET", "/api/status")[1]["engine"]["ready"])
        status = self.request("GET", "/api/status")[1]
        self.assertEqual(status["version"], server.APP_VERSION)
        self.assertEqual(status["resolution_short_sides"], [1024, 2048, 3072, 4096])
        self.assertEqual(status["max_dimension"], 16384)
        self.assertEqual(status["max_pixels"], 64 * 1024 * 1024)
        self.assertTrue(status["shutdown_supported"])
        self.assertTrue(status["exact_output_dimensions"])

    def test_02_security_and_validation(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/jobs", {}, headers={"X-Qwen-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("POST", "/api/jobs", {}, headers={"Origin": ""})[0], 403)
        self.assertEqual(self.request("POST", "/api/shutdown", {}, headers={"X-Qwen-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("POST", "/api/shutdown", {}, headers={"Origin": ""})[0], 403)
        self.assertEqual(self.request("POST", "/api/shutdown", {}, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/shutdown", [])[0], 400)
        self.assertFalse(self.app.shutting_down)
        self.assertEqual(self.request("GET", "/../config.json")[0], 404)
        self.assertEqual(self.request("POST", "/api/uploads", raw=b"not an image")[0], 400)
        for change in ({"width": 513}, {"steps": 0}, {"seed": True}, {"cfg": float("nan")}, {"mode": "edit", "upload_id": "../../config.json"}):
            self.assertEqual(self.request("POST", "/api/jobs", {"mode": "generate", "prompt": "ok", **change})[0], 400)

    def test_03_upload_edit_and_logs(self):
        status, upload = self.request("POST", "/api/uploads", raw=PNG)
        self.assertEqual(status, 201, upload)
        job = self.create(mode="edit", upload_id=upload["upload_id"], seed=-1)
        result = self.wait_done(job["id"])
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("test output saved", result["log_tail"])
        with Image.open(io.BytesIO(self.request("GET", result["image_url"])[1])) as output:
            self.assertEqual(output.size, (1024, 1024))
        self.assertEqual(self.request("GET", result["input_url"])[1], PNG)
        command = json.loads((self.app.results / job["id"] / "command.json").read_text())
        self.assertIn("--llm_vision", command["argv"])
        self.assertIn("-r", command["argv"])
        self.assertIn("euler", command["argv"])
        self.assertEqual(self.request("GET", result["diagnostics_url"])[0], 200)
        self.assertGreaterEqual(result["seed"], 0)

    def test_04_error_guidance(self):
        result = self.wait_done(self.create("fail")["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("Mémoire insuffisante", result["error"])
        self.assertNotIn("module de vision", server.diagnose("loading mmproj-F16.gguf\nfatal: unrelated failure"))
        self.assertIn("module de vision", server.diagnose("failed to load mmproj-F16.gguf"))

    def test_05_cancel_single_job_and_duplicate_start(self):
        job = self.create("slow")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, current = self.request("GET", "/api/jobs/" + job["id"])
            if current["status"] == "running":
                break
            time.sleep(0.05)
        self.assertEqual(current["status"], "running")
        self.assertEqual(self.request("POST", "/api/shutdown", {})[0], 409)
        self.assertFalse(self.app.shutting_down)
        self.assertFalse(self.app.cancel_event.is_set())
        self.assertEqual(self.app.active, job["id"])
        self.assertEqual(self.request("POST", "/api/jobs", {"mode": "generate", "prompt": "second"})[0], 409)
        second = subprocess.run([sys.executable, str(server.APP_DIR / "server.py"), "--root", str(self.root), "--port", str(self.port), "--no-browser"], capture_output=True, timeout=5, creationflags=server.CREATE_NO_WINDOW)
        self.assertEqual(second.returncode, 1)
        metadata = json.loads((self.app.results / job["id"] / "metadata.json").read_text())
        self.assertEqual(metadata["status"], "running", "Second launch must not alter an active run")
        self.assertEqual(self.request("POST", "/api/jobs/" + job["id"] + "/cancel", {})[0], 200)
        result = self.wait_done(job["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(self.app.active)
        self.assertTrue((self.app.results / job["id"] / "engine.log").exists())

    def test_06_output_dimensions_and_limits(self):
        request = {"mode": "generate", "prompt": "ok"}
        defaults = self.app.validate(request)
        self.assertEqual((defaults["width"], defaults["height"]), (1024, 1024))
        for width, height in ((1536, 1024), (2048, 3072), (4608, 3072), (4096, 6144), (16384, 4096), (8192, 8192)):
            with self.subTest(width=width, height=height):
                values = self.app.validate({**request, "width": width, "height": height})
                self.assertEqual((values["width"], values["height"]), (width, height))
        for change in ({"width": 224}, {"height": 16385}, {"width": 16416}, {"width": 1537}, {"height": 1024.0}, {"width": True}, {"height": "1024"}, {"width": float("nan")}, {"height": float("inf")}, {"width": 16384, "height": 4128}):
            with self.subTest(change=change):
                self.assertEqual(self.request("POST", "/api/jobs", {**request, **change})[0], 400)
        for change in ({"output_width": 1024}, {"output_width": 992, "output_height": 1024}, {"output_width": 1025, "output_height": 1024}, {"output_width": 1024.0, "output_height": 1024}, {"output_width": True, "output_height": 1024}, {"output_width": 1024, "output_height": float("nan")}, {"width": 256, "output_width": 255, "output_height": 1024}):
            with self.subTest(change=change):
                self.assertEqual(self.request("POST", "/api/jobs", {**request, **change})[0], 400)

    def test_07_large_dimensions_reach_command_and_metadata(self):
        for width, height in ((1536, 1024), (2048, 3072), (4096, 6144)):
            with self.subTest(width=width, height=height):
                job = self.create(width=width, height=height)
                result = self.wait_done(job["id"])
                self.assertEqual(result["status"], "succeeded", result)
                self.assertEqual((result["width"], result["height"]), (width, height))
                command = self.request("GET", result["command_url"])[1]["argv"]
                self.assertEqual(command[command.index("-W") + 1], str(width))
                self.assertEqual(command[command.index("-H") + 1], str(height))
                metadata = self.request("GET", result["metadata_url"])[1]
                self.assertEqual((metadata["width"], metadata["height"]), (width, height))
                self.assertEqual((metadata["output_width"], metadata["output_height"]), (width, height))
                with Image.open(io.BytesIO(self.request("GET", result["image_url"])[1])) as output:
                    self.assertEqual(output.size, (width, height))

    def test_08_exact_ratio_removes_alignment_padding(self):
        _, upload = self.request("POST", "/api/uploads", raw=PNG)
        job = self.create(mode="edit", upload_id=upload["upload_id"], width=1376, height=1024, output_width=1365, output_height=1024)
        result = self.wait_done(job["id"])
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(result["alignment_crop"], {"left": 5, "top": 0, "right": 6, "bottom": 0})
        with Image.open(io.BytesIO(self.request("GET", result["image_url"])[1])) as output:
            self.assertEqual(output.size, (1365, 1024))
            self.assertEqual(output.getpixel((0, 0)), (210, 31, 47), "The crop must preserve original pixels at the expected center offset")
        with Image.open(self.app.results / job["id"] / "engine-output.png") as raw:
            self.assertEqual(raw.size, (1376, 1024))
            self.assertEqual(raw.getpixel((5, 0)), (210, 31, 47))
        command = self.request("GET", result["command_url"])[1]["argv"]
        preprocessing = command[command.index("--image-preprocess") + 1]
        self.assertEqual(preprocessing, "target=ref,index=0,mode=fit-pad,width=1376,height=1024,anchor=center,filter=lanczos")

    def test_09_wrong_engine_dimensions_fail(self):
        result = self.wait_done(self.create("wrong-size")["id"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("Dimensions inattendues", result["error"])

    def test_99_idle_shutdown(self):
        self.assertIsNone(self.app.active)
        status, result = self.request("POST", "/api/shutdown", {})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "shutting_down")
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "The serving thread should exit gracefully")
        self.assertTrue(self.app.shutting_down)
        with self.assertRaisesRegex(RuntimeError, "cours d’arrêt"):
            self.app.create_job({"mode": "generate", "prompt": "late"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
