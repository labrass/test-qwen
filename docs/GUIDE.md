# Qwen Image 2.1 — atelier local

## Ouvrir

Double-cliquez sur **Lancer.vbs à la racine du projet**. L’interface s’ouvre sur **http://127.0.0.1:8766**. Aucun compte ni service de génération en ligne n’est utilisé. Le serveur écoute uniquement sur votre PC. Les calculs sont effectués par `bin/sd-cli.exe` sur la NVIDIA ; l’interface Python n’effectue pas l’inférence. Tous les chemins cités dans ce guide sont relatifs à la racine du projet.

1. Choisissez le mode **Retoucher une photo**.
2. Ajoutez votre photo PNG, JPEG ou WebP, jusqu’à 32 Mio. Les photos 1K, 2K et 4K sont acceptées ; au-delà de 4 096 pixels sur le côté long, une copie est réduite localement à cette limite. L’original sur votre disque reste intact. Les dimensions d’origine et celles de l’entrée préparée sont affichées.
3. Décrivez la modification souhaitée, choisissez la résolution (1K par défaut), puis lancez l’essai. Les proportions sont reprises automatiquement dès l’import ; les dimensions finales sont affichées avant le lancement.
4. Consultez l’avant/après et l’historique ; téléchargez le résultat ou le journal.

Exemple : `Change the color of the red ceramic mug to cobalt blue. Keep the same mug shape, handle, wooden table, beige background, lighting, shadows, camera angle and composition. Change only the color of the mug.`

Le mode de création sans photo est également disponible. Les consignes peuvent être écrites en français ; l’essai de validation emploie l’anglais. Les modèles se chargent à chaque essai, puis la mémoire du moteur est libérée à la fin. Un seul calcul peut tourner à la fois ; **Annuler** arrête le calcul en cours et conserve ses logs.

## Réglages de départ

- **1K par défaut = 1 024 pixels sur le côté le plus court**, 20 étapes, CFG 6, Euler, graine 42. Le ratio de la photo est repris automatiquement, à l’arrondi d’un pixel près.
- Le sélecteur propose **1K / 2K / 3K / 4K**, soit 1 024 / 2 048 / 3 072 / 4 096 pixels sur le côté le plus court. Il ne fixe ni le côté long ni le nombre total de pixels.
- Pour une photo paysage 3:2 : 1K → 1 536 × 1 024 ; 2K → 3 072 × 2 048 ; 3K → 4 608 × 3 072 ; 4K → 6 144 × 4 096. En portrait, largeur et hauteur sont inversées. Pour une photo 4:3, 1K donne 1 365 × 1 024.
- Le mode création sans photo propose un choix de formats. Les limites techniques de l’interface sont 16 384 pixels par côté et 64 Mi pixels sur la surface de calcul ; une combinaison excessive est refusée explicitement, sans réduire silencieusement la résolution.
- À proportions identiques, 2K calcule quatre fois plus de pixels que 1K, et 4K seize fois plus. Les tests contrôlés documentés concernent principalement 1K ; les durées et besoins mémoire de 2K à 4K n’ont pas fait l’objet d’un benchmark contrôlé sur ce GPU.
- Une graine fixe facilite la comparaison des consignes ; une graine aléatoire est enregistrée dans les paramètres de l’essai.
- Une retouche générative peut aussi modifier des textures ou des détails que la consigne demande de préserver. Le premier exemple à 512 pixels montre cette limite ; ce n’est pas une retouche déterministe pixel par pixel.

`config.json` fixe CUDA0, l’offload RAM, Flash Attention, le VAE par tuiles, un budget de 14 Gio et la désactivation du cache de préfixe. Ces réglages évitent de conserver tous les composants simultanément en VRAM. Le plafond de 14 Gio concerne les allocations gérées par le moteur, pas toute la mémoire consommée par Windows et les autres applications.

**Résolution importée et résolution analysée :** le moteur Qwen redimensionne automatiquement la référence pour atteindre environ la surface de la sortie. Ainsi, une entrée 2 048 × 2 048 avec une sortie 1 024 × 1 024 est analysée à 1 024 × 1 024 par le VAE et la vision. L’import accepte donc les grandes photos, mais le modèle ne traite pas systématiquement tous leurs pixels natifs. Ce comportement automatique est conservé pour le premier usage en 1K sur 16 Go de VRAM. [Prétraitement officiel](https://github.com/leejet/stable-diffusion.cpp/blob/70c1dbc/docs/image_preprocessing.md).

**Conservation du ratio :** le moteur calcule sur une surface arrondie au multiple de 32 supérieur. Lorsqu’il faut quelques pixels supplémentaires, la référence est préparée avec des marges, puis ces seules marges sont retirées du résultat. La sortie finale n’est pas étirée. Par exemple, une sortie 1 365 × 1 024 utilise un calcul 1 376 × 1 024 et retire 11 pixels de marges au total. L’image brute est conservée dans `engine-output.png` et les marges sont consignées dans les métadonnées. Cette finition utilise Pillow, installé par `scripts/Installer-Python.ps1`.

## Fichiers et erreurs

Les copies des imports sont conservées dans `data/inputs/`. Chaque essai de l’interface crée un dossier dans `data/results/` :

- `output.png` : image produite ; `input.png` ou `input.jpg` : référence utilisée.
- `engine.log` : sorties complètes de sd-cli, y compris erreurs CUDA et progression.
- `metadata.json` : consigne, paramètres, durée, statut et code de sortie.
- `command.json` : arguments exacts du processus.
- `diagnostics.json` : état NVIDIA au lancement.

Les erreurs du serveur sont dans `data/logs/interface.log` avec rotation. Le lanceur écrit également ses sorties et erreurs dans `data/logs/`. Le panneau de logs donne le journal complet de l’essai et un conseil de dépannage. Les anciens journaux restent conservés. Le dossier `data/` est privé et exclu de Git.

Pour un diagnostic indépendant, lancez `scripts/Diagnostic.ps1` avec PowerShell (depuis la racine : `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Diagnostic.ps1`). Il écrit un fichier daté dans `data/logs/` et vérifie NVIDIA, la version du moteur et les chemins des modèles.

En cas de manque de mémoire, revenez au palier 1K et fermez les autres applications utilisant le GPU. Une photo très panoramique demande davantage de mémoire, même en 1K. En cas d’arrêt du serveur pendant un calcul, son essai est marqué interrompu au prochain démarrage. Ne lancez pas simultanément un autre sd-cli manuellement.

Fermer l’onglet ne ferme pas le serveur local ; il reste disponible et ne garde pas les modèles en mémoire entre deux essais. Le lanceur réutilise le serveur déjà ouvert. Pour une nouvelle installation ou un Python manquant, suivez [INSTALLATION.md](INSTALLATION.md).

## Installation vérifiée

Moteur Windows CUDA : **stable-diffusion.cpp master-905-70c1dbc**, commit `70c1dbc01e10e5da8227cb43e99daa01ea910af1`. `--version` affiche « version unknown » avec ce commit ; l’identifiant de commit et le manifeste identifient précisément le binaire. Le backend chargé est `ggml-cuda.dll`, GPU **NVIDIA GeForce RTX 5060 Ti**, capacité de calcul **12.0**. Le pilote observé est **616.92**.

Quatre fichiers de modèles seulement ont été téléchargés, sans cloner les dépôts :

| Composant | Fichier | Taille décimale |
|---|---|---:|
| Générateur | qwen-image-2.1-Q4_K_M.gguf | 4,20 Go |
| Encodeur | Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf | 5,15 Go |
| Vision | mmproj-F16.gguf | 1,16 Go |
| VAE dédié 2.1 | qwen_image_2.1_vae_bf16.safetensors | 0,68 Go |

Le dossier `models/` représente environ **10,41 Gio**. Deux archives officielles supplémentaires ont fourni le moteur et ses DLL CUDA. Les révisions des dépôts, tailles exactes et SHA-256 vérifiés sont dans [artifacts.json](artifacts.json). Après installation, les modèles restent sur le disque ; aucun téléchargement n’est nécessaire pour les essais suivants.

Les premiers tests réels et leurs mesures sont détaillés dans [VALIDATION.md](VALIDATION.md). Les preuves brutes de l’installation d’origine restent dans `data/results/` et `data/logs/`, exclus du dépôt. Les anciennes commandes conservent les chemins utilisés lors de leur exécution.

Sources officielles consultées : [documentation Qwen Image 2.1](https://github.com/leejet/stable-diffusion.cpp/blob/70c1dbc/docs/qwen_image_2.1.md), [version Windows CUDA](https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-905-70c1dbc), [générateur Unsloth](https://huggingface.co/unsloth/Qwen-Image-2.1-GGUF), [encodeur et vision Unsloth](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF), [VAE Comfy-Org](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/main/vae).
