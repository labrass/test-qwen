# test-qwen

Interface locale pour retoucher des photos avec **Qwen-Image-2.1 en GGUF 4 bits**, exécuté par **stable-diffusion.cpp sous Windows CUDA**. Les images et les consignes restent sur le PC ; aucune API de génération en ligne n’est utilisée.

## Ouvrir et tester

Une fois l’installation prête, double-cliquez sur **`Lancer.vbs`** à la racine. L’interface s’ouvre sur [http://127.0.0.1:8766](http://127.0.0.1:8766).

1. Importez une photo PNG, JPEG ou WebP et décrivez la modification souhaitée.
2. Choisissez **1K, 2K, 3K ou 4K** : ce nombre fixe le côté le plus court, en conservant les proportions de la photo. Le défaut est **1 024 px**.
3. Lancez l’essai, comparez l’avant/après et récupérez l’image ou le journal.

Exemple : une photo 3:2 donne **1 536 × 1 024** en 1K, ou **3 072 × 2 048** en 2K. Les entrées de plus de 4 096 px sur le côté long sont réduites sur une copie locale ; le fichier original reste intact.

Le profil fourni a été essayé sur une **RTX 5060 Ti 16 Go avec 32 Go de RAM**. Les tests contrôlés couvrent notamment une sortie 1K ; **2K à 4K n’ont pas encore fait l’objet d’un benchmark contrôlé sur ce GPU**.

## Dossiers

```text
test-qwen/
├── Lancer.vbs          # Ouverture de l’interface
├── Lancer.ps1          # Lanceur Windows
├── config.json        # Chemins relatifs et options CUDA
├── app/               # Serveur, interface et tests
├── scripts/           # Installation Python et diagnostic
├── docs/              # Installation, guide et validation
├── bin/               # Moteur CUDA et DLL, conservés localement
├── models/            # Les quatre fichiers de modèles, conservés localement
└── data/              # Données privées, exclues de Git
    ├── inputs/        # Copies des photos importées
    ├── results/       # Un dossier par essai : images, paramètres et logs
    └── logs/          # Journaux de l’interface et diagnostics
```

Le dépôt contient le code, la configuration et la documentation. **Les photos, résultats, journaux, modèles et binaires ne sont pas publiés.** Sur une nouvelle machine, suivez [l’installation](docs/INSTALLATION.md) pour récupérer les composants nécessaires.

- [Guide d’utilisation et dépannage](docs/GUIDE.md)
- [Tests réels et limites observées](docs/VALIDATION.md)
- [API locale](app/API.md)
- [Sources, versions et empreintes des fichiers](docs/artifacts.json)

## Vérifier le code

Depuis la racine, avec l’environnement Python préparé et activé :

```powershell
python app/test_server.py
node app/test_resolution.js
```

Ces tests utilisent un moteur factice et ne chargent aucun modèle. Node.js sert uniquement au test des calculs de résolution ; l’interface n’en a pas besoin pour fonctionner.
