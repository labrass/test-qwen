# Interface locale

Serveur Python avec Pillow : `python app/server.py --no-browser`. Le lanceur utilise le runtime local déjà installé, qui inclut Pillow. Le serveur écoute exclusivement `127.0.0.1:8766`. `--root` peut désigner le dossier contenant `config.json` ; `--port` permet de choisir un autre port local.

La page utilise uniquement des fichiers locaux. Le navigateur convertit les photos PNG/JPEG/WebP en PNG, avec un côté long limité à 4 096 px et un poids maximal de 32 Mio. Il affiche les dimensions d’origine et préparées. La sortie reprend automatiquement le ratio de la photo d’origine, à l’arrondi au pixel près. Le sélecteur fixe le côté le plus court : 1K (1 024 px, valeur par défaut), 2K, 3K ou 4K. En création sans photo, un sélecteur propose les formats usuels. Le moteur conserve son redimensionnement automatique de référence vers une surface voisine de celle de la sortie. Un essai recharge les modèles dans un nouveau processus `sd-cli`. Un seul essai peut fonctionner à la fois.

## API

- `GET /api/status` : version 1.2, état du serveur, présence des cinq fichiers (moteur et quatre modèles) et capacités de résolution.
- `GET /api/state` : `csrf_token`, `active_job`, `engine`, `root`, historique `jobs` (100 derniers essais).
- `POST /api/uploads` : corps binaire PNG ou JPEG, maximum 32 Mio. Réponse `upload_id`, largeur et hauteur. L’interface convertit WebP avant cet envoi.
- `POST /api/jobs` : objet JSON `{ "mode": "edit", "upload_id": "identifiant.png", "prompt": "Consigne", "width": 1376, "height": 1024, "output_width": 1365, "output_height": 1024, "steps": 20, "cfg": 6, "seed": 42 }`. Mode `generate` sans `upload_id`. `seed=-1` ou `null` choisit une graine aléatoire enregistrée. Dimensions moteur : 256 à 16 384, multiples de 32, surface maximale de 67 108 864 pixels ; étapes : 1 à 100 ; CFG : 1 à 20. Ces plafonds logiciels ne garantissent pas la capacité mémoire du GPU.
- `output_width` et `output_height` sont facultatifs mais doivent être fournis ensemble. Chaque dimension finale vaut au moins 256 et diffère de la dimension moteur correspondante de 0 à 31 pixels. Sans ces champs, la sortie conserve les dimensions moteur. L’interface calcule la taille finale au pixel près, puis arrondit les dimensions moteur au multiple de 32 supérieur.
- `GET /api/jobs/{id}` : métadonnées, adresses des fichiers et 48 Ko de fin de journal (`log_tail`). États : `queued`, `preparing`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`, `interrupted`.
- `POST /api/jobs/{id}/cancel` avec `{}` : arrête le processus et conserve les journaux.
- `POST /api/shutdown` avec `{}` : arrête proprement le serveur lorsqu’il est inactif ; refuse avec HTTP 409 si un essai est en cours.
- `GET /api/jobs/{id}/{fichier}` : `output.png`, `engine-output.png`, `input.png` ou `input.jpg`, `engine.log`, `metadata.json`, `command.json`, `diagnostics.json` uniquement.

Tous les POST doivent fournir `Origin: http://127.0.0.1:8766` et `X-Qwen-Token: <csrf_token>`. Adapter le port si nécessaire. `localhost` est aussi admis pour le même port. Le serveur refuse les hôtes et origines externes, sans configuration CORS. Le navigateur ajoute lui-même Origin. Les clients Python/PowerShell doivent le préciser.

Pour une édition dont les dimensions finales diffèrent de celles du moteur, la commande applique `--image-preprocess target=ref,index=0,mode=fit-pad,width=…,height=…,anchor=center,filter=lanczos`. Après calcul, Pillow vérifie la taille produite et retire les marges d’alignement au centre, sans étirement. L’image brute est conservée dans `engine-output.png` et les décalages sont enregistrés dans `alignment_crop`. Le résultat est publié après cette finition.

## Fichiers conservés

- `data/inputs/` : photos envoyées.
- `data/results/{id}/` : photo de départ copiée, image finale, commande structurée, journal complet stdout/stderr, métadonnées avec dates/durée/code de sortie, diagnostic `nvidia-smi` avant l’essai.
- `data/logs/interface.log` : erreurs du serveur HTTP et de l’application, rotation 4 Mio × 4 fichiers.

Les essais et les photos restent conservés sur disque. L’historique est reconstruit au lancement. Un essai inachevé au redémarrage est indiqué « Interrompu ». Fermer l’onglet n’arrête pas le moteur ; utiliser le bouton Annuler ou arrêter le serveur.

## Vérification isolée

`python app/test_server.py` exécute dix tests HTTP et de processus avec un faux moteur. Ils vérifient les routes, le chargement de photo, la commande, les journaux, les erreurs, l’annulation, l’unicité du processus, le refus d’un second serveur, les grandes résolutions, les limites, le retrait des marges et l’arrêt propre du serveur. Ils n’utilisent ni GPU ni modèle et créent leurs fichiers temporaires sous `app/`. Les vrais essais CUDA sont consignés dans `../docs/VALIDATION.md`.
