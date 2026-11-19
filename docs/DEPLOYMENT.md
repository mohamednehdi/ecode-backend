# Déploiement : Docker, Nginx, Redis (F1)

## Architecture

```
                     ┌────────────────────────────── docker compose ─────────────────────────────┐
 clients ──HTTP──►   │  Nginx :8080  ──►  app (conteneur 1)  ┐                                     │
 (site, API)         │  répartition       app (conteneur 2)  ├──►  MySQL   (tables, journal)       │
                     │  de charge         app (conteneur N)  ┘──►  Redis   (quotas, limites)       │
                     └────────────────────────────────────────────────────────────────────────────┘
```

| Élément | Rôle |
|---|---|
| **Nginx** | Point d'entrée unique, répartit les requêtes entre les conteneurs `app`, limite la taille des envois, transmet l'adresse IP réelle du client. |
| **app** (×N) | Flask servi par gunicorn : `WEB_WORKERS` processus × `WEB_THREADS` threads. Sans état : on en ajoute avec `--scale`. |
| **Redis** | Compteurs de quotas et limite par IP de la page publique, **partagés** par tous les conteneurs. |
| **MySQL** | Comptes admin, clés API (hachées), journal des requêtes `api_usage`. |
| **init-db** | Tâche unique au démarrage : crée les tables (1er démarrage) ou applique les migrations. |

## Démarrage

Dans `.env` : `SECRET_KEY`, `JWT_SECRET_KEY`, `MYSQL_ROOT_PASSWORD` (lettres et chiffres seulement).

```powershell
docker compose up -d --build
docker compose run --rm app flask --app run create-admin
```

Le service répond sur `http://localhost:8080` (`/public/extract`, `/api/v1/extract`, `/auth`, `/admin`, `/health`).
Plus de conteneurs : `docker compose up -d --scale app=4`.

## Pourquoi Redis pour les quotas

Avec plusieurs conteneurs, compter les lignes de `api_usage` pose deux problèmes :
1. **Exactitude** : deux conteneurs peuvent lire « 99 requêtes sur 100 » en même temps et accepter tous les deux la 100ᵉ… ou plus.
2. **Coût** : un `COUNT(*)` sur une table qui grossit à chaque requête, deux fois par requête.

Avec Redis (`REDIS_URL` défini) :
- **Quota horaire** : un ensemble trié par clé (un élément par requête, noté avec son heure). On retire les éléments de plus d'une heure, on ajoute la requête, on compte : fenêtre glissante exacte, en une seule transaction Redis.
- **Quota mensuel** : un compteur par clé et par mois (`INCR`). S'il n'existe pas (premier appel du mois, ou Redis redémarré), il repart du nombre de lignes de `api_usage`.
- **Principe « compter d'abord, vérifier ensuite »** : une requête au-delà du quota se retire elle-même. Deux conteneurs ne peuvent donc jamais se partager la dernière place.
- **Fichier refusé** (format invalide) : la place est rendue, comme avant.
- **Redis en panne** : retour automatique aux compteurs MySQL (le service reste disponible, un avertissement est journalisé).
- Une clé **sans quota** ne fait aucun appel à Redis.

Le journal `api_usage` reste écrit à chaque requête acceptée (audit, base du futur tableau de bord F4).

## Adresse IP derrière Nginx

Les règles « IP autorisées » et la limite par IP lisent l'adresse du client. Derrière Nginx, l'application verrait l'adresse
de Nginx : `TRUSTED_PROXIES=1` lui fait lire l'en-tête `X-Forwarded-For`, que Nginx **réécrit** (il ne l'additionne pas à celui du
client). Sans proxy, la valeur reste `0` : un en-tête forgé est alors ignoré (un test le vérifie).

## Ce qui est vérifié, et ce qui ne l'est pas

| Élément | État |
|---|---|
| Compteurs Redis : horaire, mensuel, clé sans quota, place rendue, reprise depuis le journal, secours MySQL | Testés (`fakeredis`) |
| 8 « workers » concurrents se disputant 50 places : exactement 50 acceptées | Testé (`fakeredis`) |
| `X-Forwarded-For` ignoré sans proxy, utilisé avec proxy | Testé |
| `init-db` sur une base **vide** (4 tables + version de migration), puis relancé | Testé sur MySQL |
| Syntaxe de `docker-compose.yml` | Lue par un parseur YAML ; **non exécutée** |
| `Dockerfile`, `nginx.conf`, démarrage complet des conteneurs | **Non exécutés** : Docker n'est pas installé sur le poste de développement |
| Redis réel (au lieu de `fakeredis`) | **Non exécuté** : aucun serveur Redis sur le poste |
| Courbe de montée en charge (1, 2, 4, 8 conteneurs) | **Non mesurée** (voir ci-dessous) |

## Mesure de la montée en charge (F1c)

Script prêt : `stress/run_scaling.ps1` (1, 2, 4, 8 conteneurs, mêmes charges que `docs/PERFORMANCE.md`).
À lancer après `docker compose up`, avec une clé API sans quota. Résultats dans `stress/results/scaling_*`.
Sur un portable 4 cœurs, la courbe plafonnera dès que les cœurs sont saturés : les chiffres à 1000 req/s ne peuvent venir que
d'une machine (ou plusieurs) avec assez de cœurs. À écrire ici une fois mesurée, avec le matériel exact.
