# Validation locale

Essais initiaux effectués le **23 septembre 2026** sous Windows 11, avec **RTX 5060 Ti 16 Go**, 32 Go de RAM et pilote NVIDIA 616.92. Moteur : stable-diffusion.cpp `master-905-70c1dbc`, commit `70c1dbc01e10e5da8227cb43e99daa01ea910af1`. Aucune API de génération en ligne n’a été utilisée.

## Modèles et CUDA

Les quatre modèles et les deux archives officielles ont été vérifiés par SHA-256. Les journaux du moteur reconnaissent **Qwen Image 2.1**, chargent `ggml-cuda.dll` et utilisent **CUDA0 — NVIDIA GeForce RTX 5060 Ti**, capacité de calcul 12.0.

Une édition réelle a chargé `mmproj-F16.gguf` avec `Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf`, activé la vision et traité une référence. Le modèle a transformé une tasse rouge en tasse bleue. Les images ont été inspectées : le changement demandé apparaît, avec également des modifications de textures du fond et de la table.

## Calculs réels

Les images de référence utilisées pour ces validations sont des démonstrations générées localement, parfois agrandies. Ces essais ne mesurent pas la conservation de détails fins de photos personnelles.

| Essai | Entrée | Sortie finale | Étapes | Durée totale | Code |
|---|---:|---:|---:|---:|---:|
| Création de la référence | Sans photo | 512 × 512 | 20 | 35,67 s | 0 |
| Retouche avec vision | 512 × 512 | 512 × 512 | 20 | 44,77 s | 0 |
| Retouche via l’interface | 512 × 512 | 768 × 768 | 20 | 107,47 s | 0 |
| Import 2K, sortie 1K | 2 048 × 2 048 | 1 024 × 1 024 | 20 | 216,91 s | 0 |
| Retrait des marges 4:3 | 2 048 × 1 536 | 1 365 × 1 024 | 1 | 33,19 s | 0 |

Paramètres communs : Euler, CFG 6, graine 42 et profil mémoire de `config.json`. Pour la sortie 1K carrée, le pic observé était **7 779 Mio, soit 7,60 Gio**. Les relevés `nvidia-smi` étaient espacés de trois secondes et incluaient toute la mémoire GPU occupée, y compris Windows et les autres applications ; un pic entre deux mesures peut ne pas être capturé.

Le dernier essai vérifie la géométrie : le moteur accepte `fit-pad`, calcule **1 376 × 1 024**, puis la finition retire 5 pixels à gauche et 6 à droite pour produire **1 365 × 1 024**, sans redimensionnement final. **Une seule étape valide ce chemin technique, pas la qualité visuelle.**

## Interface et tests isolés

Le navigateur a confirmé l’import local, les aperçus, le lancement, le résultat, l’historique et les liens vers les journaux. Avec une image 3 072 × 2 048, le sélecteur propose bien **1 536 × 1 024 en 1K** et **3 072 × 2 048 en 2K**.

Les dix tests isolés initiaux du serveur ont réussi : santé et fichiers statiques, validation des requêtes et des origines, import, cycle de retouche, erreurs moteur, annulation, concurrence, limites de résolution, dimensions finales et retrait des marges, arrêt propre. Ils utilisent un moteur factice, sans GPU ni téléchargement. La syntaxe Python/JavaScript et les calculs de dimensions paysage/portrait ont aussi été vérifiés.

Après le déplacement vers la nouvelle structure locale, les dix tests du serveur ont de nouveau réussi. Les calculs de dimensions disposent aussi d’un test autonome, à lancer avec `node app/test_resolution.js`. Le serveur a redémarré avec le moteur prêt et l’historique conservé ; aucun nouveau benchmark GPU n’était nécessaire pour ce déplacement de fichiers.

Les preuves brutes de l’installation locale sont conservées dans **`data/results/` et `data/logs/`**, exclus du dépôt. Elles peuvent contenir des consignes et des chemins propres à la machine ; les anciens chemins enregistrés décrivent leur exécution d’origine.

## Limites

Les durées et besoins mémoire des résolutions **2K, 3K et 4K n’ont pas encore fait l’objet d’un benchmark contrôlé sur ce GPU**. À format identique, 2K calcule quatre fois plus de pixels que 1K, et 4K seize fois plus. La durée et la mémoire varient également avec le format de la photo et les applications ouvertes.

L’entrée 2K du test carré a été automatiquement réduite par le moteur à 1K pour la vision et le VAE, conformément au prétraitement de Qwen. Accepter une grande photo dans l’interface ne signifie donc pas analyser systématiquement tous ses pixels natifs.
