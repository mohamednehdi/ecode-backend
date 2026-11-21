# eCode : plateforme de localisation et d'extraction de codes-barres

[![CI](https://github.com/mohamednehdi/Python-merged/actions/workflows/ci.yml/badge.svg)](https://github.com/mohamednehdi/Python-merged/actions/workflows/ci.yml)

Projet de fin d'études, Progress Engineering. Ce dépôt est le **backend** (Flask). Le site (Angular) est dans le dépôt
[new-angular-barcode](https://github.com/mohamednehdi/new-angular-barcode).

Ce que fait la plateforme : lire les codes-barres **1D, QR Code et DataMatrix** d'images (PNG, JPG) et de PDF de plusieurs pages, et
rendre le résultat en JSON, par :
- une **page publique gratuite** (dépôt d'un fichier, résultat à l'écran) ;
- un **service web** réservé aux applications munies d'une clé API (adresses IP, types de codes, quotas et période de validité par clé) ;
- un **back office** d'administration (clés API, statistiques d'utilisation).

## Démarrage rapide (développement, Windows)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                       # puis remplir .env (SECRET_KEY, JWT_SECRET_KEY, DATABASE_URL...)
.\upgrade_db.bat                             # base MySQL : crée / met à jour les tables
flask --app run create-admin                 # crée le compte administrateur
python run.py                                # http://localhost:5000
```

Documentation interactive du service : `http://localhost:5000/api/docs/`. Toute la plateforme en conteneurs (Nginx, 2 serveurs,
Redis, MySQL) : `docker compose up -d --build` (voir `docs/DEPLOYMENT.md`).

## Tests, lint et intégration continue

```powershell
pip install -r requirements-dev.txt
pytest                                       # 47 tests
pytest --cov=app --cov=config --cov-report=term-missing     # avec la couverture
ruff check .                                 # lint
```

| Mesure | Valeur |
|---|---|
| Tests du backend | **47**, tous passent |
| Couverture (instructions et branches) | **92 %** sous Windows, **91,6 %** sous Linux, mesurée le 20/11/2026 ; le plus faible : l'envoi d'e-mails par SMTP (`app/auth/services.py`, 58 %), non testable sans serveur de messagerie |
| Lint | `ruff` (erreurs de type pyflakes : imports inutiles, noms indéfinis) |

À chaque `push` et chaque demande de fusion, GitHub Actions (`.github/workflows/ci.yml`) lance : le lint, les tests avec couverture
(échec sous 90 %), et la construction du conteneur Docker suivie d'un appel à `/health`. Le détail de ce qui est vérifié, et de ce qui ne
l'est pas, est dans `docs/TESTING_CI_F7.md`.

## Les documents du projet (`docs/`)

| Document | Sujet |
|---|---|
| `API.md` | guide du développeur : utiliser le service web |
| `PERFORMANCE.md` | temps de réponse, test de charge, configuration matérielle proposée |
| `DEPLOYMENT.md` | Docker, Nginx, Redis, montée en charge |
| `DECODER_STUDY.md` | comparaison de sept décodeurs sur 704 images dégradées |
| `LOCALIZER_STUDY.md`, `REGIONS_DECODING.md` | localisation des codes et lecture par régions |
| `STATISTICS.md` | tableau de bord statistique de l'administrateur |
| `API_DOCS_F5.md`, `TESTING_CI_F7.md` | notes de réalisation de la documentation d'API, des tests et de l'intégration continue |
| `PROJECT_TRACKER.md` | backlog, critères d'acceptation et journal de travail |

## Organisation du dépôt

```
app/            le backend : auth, admin (clés, statistiques), api (service web), scans (décodeur, localisation)
tests/          les tests automatiques
bench/          études de comparaison des décodeurs et de la localisation (jeux d'images générés)
stress/         test de charge (Locust)
migrations/     évolutions de la base de données (Alembic)
docker/, Dockerfile, docker-compose.yml     déploiement
docs/           documentation
```
