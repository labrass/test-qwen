# Installer sur un nouveau PC Windows

Le dépôt fournit l’interface et la configuration. Le moteur, ses DLL et les modèles se téléchargent séparément depuis leurs sources officielles. **Aucun dépôt de modèles complet n’est nécessaire.** Les téléchargements et l’installation de Python utilisent Internet ; la génération et la retouche s’exécutent ensuite localement.

## 1. Préparer Python

Prérequis : Windows 11 64 bits, GPU NVIDIA avec pilote compatible avec le moteur CUDA, et **Python 3.10 ou plus récent, 64 bits**, accessible au lanceur Python Windows ou au terminal. Le profil a été testé sur une RTX 5060 Ti 16 Go avec 32 Go de RAM. Prévoir de l’espace pour environ 10,41 Gio de modèles, le moteur et les résultats ; 20 Gio libres permettent de démarrer.

Après avoir cloné ce dépôt, ouvrez PowerShell à sa racine et lancez :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Installer-Python.ps1
```

Ce script prépare l’environnement Python local et sa dépendance Pillow. Il n’installe ni les modèles ni un service de génération.

## 2. Installer le moteur Windows CUDA

La version de référence est **stable-diffusion.cpp `master-905-70c1dbc`**, commit `70c1dbc01e10e5da8227cb43e99daa01ea910af1`. Le paquet Windows CUDA 12 utilisé lors des essais est compilé avec CUDA 12.8.1 et prend en charge la RTX 5060 Ti.

Téléchargez ces **deux archives** de la [version officielle](https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-905-70c1dbc) :

- [sd-master-70c1dbc-bin-win-cuda12-x64.zip](https://github.com/leejet/stable-diffusion.cpp/releases/download/master-905-70c1dbc/sd-master-70c1dbc-bin-win-cuda12-x64.zip)
- [cudart-sd-bin-win-cu12-x64.zip](https://github.com/leejet/stable-diffusion.cpp/releases/download/master-905-70c1dbc/cudart-sd-bin-win-cu12-x64.zip)

Décompressez-les et placez `sd-cli.exe` ainsi que les DLL de ces deux paquets **ensemble dans `bin/`**, directement à la racine de ce dossier. La configuration attend `bin/sd-cli.exe` ; ne laissez pas l’exécutable dans un sous-dossier créé par l’archive. Conservez aussi les notices fournies par les paquets.

Vérifiez le moteur :

```powershell
.\bin\sd-cli.exe --version
.\bin\sd-cli.exe --list-devices
```

Le commit attendu est `70c1dbc` et le périphérique doit mentionner la NVIDIA via CUDA. Cette version peut afficher « version unknown » avec le bon commit. N’utilisez pas une ancienne version qui ne reconnaît pas Qwen-Image-2.1.

## 3. Télécharger exactement quatre fichiers de modèles

Créez `models/` à la racine et placez-y les fichiers ci-dessous, sans changer leur nom. Les liens directs figent les révisions utilisées pendant les essais.

| Composant | Fichier à télécharger | Taille décimale |
|---|---|---:|
| Générateur | [qwen-image-2.1-Q4_K_M.gguf](https://huggingface.co/unsloth/Qwen-Image-2.1-GGUF/resolve/2c31ccd392b367a6637841a143813320a02dff55/qwen-image-2.1-Q4_K_M.gguf) | 4 199 565 024 octets |
| Encodeur | [Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/b93a7ee713758252c555be4210c00540df954dc2/Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf) | 5 148 699 488 octets |
| Vision | [mmproj-F16.gguf](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/b93a7ee713758252c555be4210c00540df954dc2/mmproj-F16.gguf) | 1 159 030 336 octets |
| VAE 2.1 | [qwen_image_2.1_vae_bf16.safetensors](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/resolve/9a44dbdb47cefd046be9c0a13476192f34c8db8e/vae/qwen_image_2.1_vae_bf16.safetensors) | 675 509 688 octets |

Le module de vision et l’encodeur viennent du même dépôt Qwen3-VL-8B. Cette paire a été validée par une retouche réelle sur le backend CUDA.

## 4. Vérifier les téléchargements

Les empreintes SHA-256 suivantes correspondent aux fichiers réellement téléchargés et vérifiés lors de l’installation initiale. Elles sont aussi disponibles avec les URL et tailles dans [artifacts.json](artifacts.json).

| Fichier | SHA-256 |
|---|---|
| qwen-image-2.1-Q4_K_M.gguf | `631d532e7ca71e8d90a87c71d3699761a812039d22e3370e87498d87754660fe` |
| Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf | `e3d1a6e87c5cb31e054f2c3bc0dd82ffde052f613de5eef3665b7bd33c9b703e` |
| mmproj-F16.gguf | `d406d03ebabefdef86a2c86bf0c1b65f9e046f7a81c218f25de4931b46a07fc4` |
| qwen_image_2.1_vae_bf16.safetensors | `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9` |
| sd-master-70c1dbc-bin-win-cuda12-x64.zip | `81a86718eae9579e3c7bb5775bfedb7ef8e7cdc22ef0ee406d35efe7de668bd3` |
| cudart-sd-bin-win-cu12-x64.zip | `fe20366827d357c00797eebb58244dddab7fd9a348d70090c3871004c320f38d` |

Exemple de contrôle dans PowerShell :

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\models\mmproj-F16.gguf
```

Comparez la valeur obtenue avec la ligne correspondante. Faites de même pour les quatre modèles et les deux archives avant de considérer l’installation complète.

## 5. Lancer

`config.json` utilise des chemins **relatifs à la racine du projet** vers `bin/` et `models/`. Le profil fourni active CUDA0, l’offload RAM, Flash Attention, le VAE par tuiles, un budget de 14 Gio et désactive le cache de préfixe.

Double-cliquez sur **`Lancer.vbs`**. La page locale doit afficher le moteur prêt. Commencez par **1K** avec votre photo ; le ratio est conservé automatiquement. Les sorties et journaux sont créés dans `data/`. Les durées et besoins mémoire des résolutions 2K à 4K n’ont pas encore fait l’objet d’un benchmark contrôlé sur le GPU de référence.

En cas de problème, exécutez :

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Diagnostic.ps1
```

Voir le [guide](GUIDE.md) et la [documentation officielle Qwen-Image-2.1](https://github.com/leejet/stable-diffusion.cpp/blob/70c1dbc/docs/qwen_image_2.1.md). Les composants téléchargés restent soumis aux conditions de leurs éditeurs, consultables sur leurs pages officielles.
