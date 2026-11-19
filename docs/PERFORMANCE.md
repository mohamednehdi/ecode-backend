# Performances, test de charge et configuration matérielle

Objectifs du cahier des charges : répondre à une demande d'extraction en **moins de 100 ms**, supporter
**1000 demandes par seconde**, réaliser un **stress test** et proposer une **configuration matérielle**.

Date des mesures : 19/11/2026. Tous les chiffres ci-dessous sont mesurés (scripts dans `stress/`), sauf
mention « estimation ».

## 1. Environnement de mesure

| Élément | Valeur |
|---|---|
| Machine | portable Intel Core i5-7300HQ (4 cœurs, 2,5 GHz), 8 Go de RAM, Windows 10 |
| Serveur | `serve.py` (waitress), 4 threads, Flask, SQLAlchemy |
| Base de données | MySQL local (même machine), base de test dédiée supprimée après les essais |
| Générateur de charge | Locust, **sur la même machine** (il consomme une partie des 4 cœurs) |

Les résultats sont donc **prudents** : sur une vraie installation, le générateur de charge, MySQL et le
serveur d'application tournent sur des machines séparées.

## 2. Le goulot d'étranglement trouvé : le décodage DataMatrix

Première mesure, avec les bibliothèques initiales (`pyzbar` pour les codes 1D/QR, `pylibdmtx` pour DataMatrix) :

| Image | pyzbar | pylibdmtx (DataMatrix) |
|---|---|---|
| Recadrage 300×300 (1 QR) | 3,5 ms | **2 184 ms** |
| Image 1200×900, 3 codes | 39 ms | **10 161 ms** |
| Page A4 200 dpi, 3 codes | 131 ms | **11 338 ms** |
| Page A4 vide | 97 ms | **1 624 ms** |

`pylibdmtx` fouille l'image sans limite de temps : **100 fois trop lent** pour l'objectif de 100 ms, quelle
que soit la puissance de la machine. Le décodeur a donc été remplacé par **zxing-cpp** (open source,
C++), qui lit QR, DataMatrix, Code 128/39/93, EAN/UPC, ITF, Codabar, PDF417, Aztec, MaxiCode… en un seul
passage.

| Image | Avant (pyzbar + pylibdmtx) | Après (zxing-cpp) |
|---|---|---|
| 1200×900, 3 codes | ≈ 3 000 ms (avec limite de temps) à 10 000 ms | **≈ 29 à 39 ms** |
| Page A4 200 dpi, 3 codes | > 11 000 ms | **≈ 85 ms** |
| Page A4 vide | 1 624 ms | **≈ 130 ms** |

### Qualité de lecture (scans de mauvaise qualité)

Le cahier insiste sur les mauvais scans. Image de test 1200×900 avec 3 codes :

| Dégradation | Ancien décodeur | Nouveau décodeur |
|---|---|---|
| Flou moyen, faible contraste, rotation 15°, rotation 90° | 3 codes | 3 codes |
| Bruit fort + flou | 1 code | **3 codes** |
| Compression JPEG qualité 10 | 2 codes | **3 codes** |
| Bruit fort | 2 codes | **3 codes** |

Fonctionnement en deux étapes (`app/scans/decoder.py`) :

1. **Passe rapide** : image en niveaux de gris, un seul appel au décodeur.
2. **Passes de nettoyage**, uniquement si la passe rapide ne trouve rien, dans un budget de temps
   (`DECODE_FALLBACK_BUDGET_MS`, 2 s par document) : inversion des couleurs, amélioration du contraste,
   binarisation adaptative, réduction du bruit, rotations de ±45°, agrandissement ×2. Les coordonnées
   renvoyées restent celles de l'image d'origine (testé).

Limites connues : si la passe rapide trouve *au moins un* code, les passes de nettoyage ne sont pas lancées
(on ne peut pas savoir qu'un code a été manqué) ; un code 1D blanc sur fond noir placé sur une page
contenant d'autres codes lisibles peut donc être manqué.

## 3. Résultats du stress test

Commande : `locust -f stress/locustfile.py --headless -u N -t 25s` (N utilisateurs simultanés, chacun envoie
sa requête suivante dès qu'il reçoit la réponse). Toutes les séries : **0 échec**.

| Charge (fichier envoyé) | Utilisateurs | Débit (req/s) | Médiane | p95 | p99 |
|---|---|---|---|---|---|
| Image 1200×900 (3 codes) | 1 | 20 | **47 ms** | **60 ms** | 120 ms |
| Image 1200×900 (3 codes) | 4 | 54 | 64 ms | 110 ms | 290 ms |
| Image 1200×900 (3 codes) | 16 | 55 (saturé) | 280 ms | 390 ms | 580 ms |
| Recadrage 300×300 (1 QR) | 4 | **153** | **25 ms** | **33 ms** | 45 ms |
| Recadrage 300×300 (1 QR) | 16 | 147 (saturé) | 100 ms | 130 ms | 190 ms |
| Mélange (50 % recadrages, 40 % images, 10 % A4) | 4 | 72 | 52 ms | 180 ms | 220 ms |
| Scan A4 200 dpi (JPEG, 3 codes) | 4 | 19 | 190 ms | 240 ms | 340 ms |
| PDF A4 d'une page | 4 | 11 | 350 ms | 460 ms | 550 ms |

Lecture :

- Quand le débit est saturé (16 utilisateurs), le débit ne monte plus et la latence augmente : les requêtes
  attendent dans la file. C'est le comportement attendu d'un serveur dont les cœurs sont tous occupés.
- Le décodeur libère le verrou Python (GIL) : le débit de décodage augmente presque linéairement avec le
  nombre de cœurs (mesuré : 1 → 4 threads = 38 → 135 images/s pour une image 1200×900).

### Où passe le temps (une image 1200×900, machine au repos)

| Étape | Durée |
|---|---|
| Lecture du PNG | 11 ms |
| Recherche des codes | ≈ 25 ms |
| Recherche de la clé API (SELECT) | 1 ms |
| Enregistrement de l'utilisation + validation | 5 ms |
| Comptage des quotas (si définis) | 2 ms chacun |

La base de données n'est **pas** le goulot : MySQL local accepte ≈ **2 700 insertions/s** (un COMMIT par
insertion, réglage de durabilité par défaut), soit plus que les 1000 req/s visés.

## 4. Verdict par rapport au cahier des charges

| Exigence | Résultat |
|---|---|
| Réponse en moins de 100 ms | **Atteint** pour les images jusqu'à ≈ 1 mégapixel (médiane 47 ms, p95 60 ms sans file d'attente) et les recadrages (p95 33 ms). **Non atteint** pour les scans A4 complets (médiane 190 ms) et les PDF (350 ms) sur cette machine : décoder 3,9 mégapixels prend ≈ 85 ms de calcul pur. Leviers : `DECODE_MAX_SIDE` plus petit, `PDF_DPI` plus bas (150), processeur plus rapide, ou envoi du seul recadrage du code. |
| 1000 demandes par seconde | **Non atteint sur cette machine** (≈ 150 req/s au mieux, 54 req/s pour des images 1 Mpx), et **non démontré** : aucun matériel de cette taille n'était disponible. L'architecture est sans état et le débit croît avec le nombre de cœurs (mesuré) : la cible se vise en ajoutant des cœurs, voir §5. |
| Stress test | Réalisé (§3), reproductible (§7). |
| Configuration matérielle | Proposée (§5), calculée à partir des mesures. |

## 5. Configuration matérielle proposée

### Dimensionnement

Débit mesuré par cœur (4 cœurs partagés avec MySQL et le générateur de charge, donc prudent) et nombre de
cœurs nécessaires pour **1000 req/s** avec 30 % de marge (utilisation maximale 70 %) :

| Charge | Débit mesuré | Par cœur | Cœurs pour 1000 req/s |
|---|---|---|---|
| Recadrages / petites images (≈ 0,1 Mpx) | 150 req/s | 37 req/s | ≈ 40 |
| Mélange réaliste | 72 req/s | 18 req/s | ≈ 80 |
| Images ≈ 1 Mpx | 54 req/s | 13,5 req/s | ≈ 105 |
| Scans A4 200 dpi | 19 req/s | 4,9 req/s | ≈ 290 |
| PDF A4 | 11 req/s | 2,8 req/s | ≈ 510 |

Estimation : sans le générateur de charge ni MySQL sur les mêmes cœurs, le besoin réel sera plus faible
(d'après le profil du §3, de l'ordre de 40 % de moins pour les images 1 Mpx). Les processeurs de serveur
récents sont plus rapides qu'un i5 de 2017, mais ce gain n'a pas été mesuré ici : à vérifier sur le
matériel retenu.

### Architecture recommandée (cible : charge mixte, 1000 req/s)

```
Internet ──► Nginx (répartition de charge, TLS)
                 ├──► Serveur applicatif 1 ┐
                 ├──► Serveur applicatif 2 ├──► MySQL (principal)
                 └──► Serveur applicatif 3 ┘──► Redis (compteurs de limitation)
```

| Rôle | Quantité | Configuration |
|---|---|---|
| Serveur applicatif | 3 | 32 vCPU (≥ 2,5 GHz), 32 Go RAM, SSD 100 Go. Linux, `gunicorn -w 4 --threads 8 -k gthread run:app` |
| Répartiteur de charge | 1 (+1 secours) | Nginx, 4 vCPU, 8 Go RAM, réseau 10 Gbit/s |
| Base de données | 1 (+1 réplica) | MySQL, 8 vCPU, 32 Go RAM, **SSD NVMe**, `innodb_buffer_pool_size` ≈ 16 Go |
| Redis | 1 | 2 vCPU, 4 Go RAM |
| Poste de test de charge | 1 à 2 | machines **séparées** des serveurs, pour tester 1000 req/s |

Pour des images compactes uniquement : 1 serveur de 48 vCPU suffit. Pour des scans A4/PDF en volume :
prévoir 10 serveurs de 32 vCPU, ou réduire la résolution envoyée.

Autres points de dimensionnement :

- **Mémoire** : ≈ 25 à 50 Mo par requête en cours (page A4 décodée et copies de travail) ; 32 requêtes
  simultanées par serveur ≈ 1,6 Go. 16 Go suffisent, 32 Go donnent de la marge.
- **Réseau** : 1000 req/s × 100 Ko ≈ 0,8 Gbit/s (images) ; × 1 Mo (PDF) ≈ 8 Gbit/s : prévoir du 10 Gbit/s.
- **Journal d'utilisation** (`api_usage`) : une ligne par requête, soit jusqu'à ≈ 86 millions de lignes par
  jour à 1000 req/s soutenues. La commande `flask --app run purge-usage --keep-days 35` supprime les
  anciennes lignes (35 jours conservés : le quota mensuel n'a besoin que du mois en cours) ; à planifier
  chaque nuit. Pour une charge soutenue proche de 1000 req/s, il faudra remplacer ce journal par des
  compteurs agrégés (voir §6).
- **Limitation par IP de la page publique** : avec plusieurs processus ou serveurs, utiliser Redis :
  `RATELIMIT_STORAGE_URI=redis://hote:6379` (sinon chaque processus compte à part).
- **Linux recommandé** en production (`gunicorn`, plusieurs processus) ; `serve.py` (waitress) fonctionne
  aussi, sous Windows compris.

## 6. Limites et améliorations possibles

- Le test à 1000 req/s n'a pas été exécuté (matériel indisponible) ; les chiffres de §5 sont des
  extrapolations de mesures à 4 cœurs.
- Compteurs de quota : lus dans MySQL à chaque requête (2 requêtes SQL). Acceptable jusqu'à plusieurs
  centaines de req/s ; au-delà, passer à des compteurs Redis (`INCR` avec expiration) écrits dans MySQL par
  lots.
- Les passes de nettoyage ne s'appliquent que si la passe rapide ne trouve aucun code (§2).
- Un code incliné à 30° ou 45° est moins bien lu qu'un code droit ; les très petits codes (quelques pixels
  par module) restent illisibles.

## 7. Refaire le stress test

Depuis le dossier du projet, environnement virtuel actif (`pip install -r requirements-dev.txt`) :

```powershell
python stress/make_samples.py                      # fichiers de test dans stress/samples/
python stress/setup_stress_db.py create            # base de test "barcode_stress" + clé API (affichée)
$env:DATABASE_URL = "<url de la base barcode_stress>"; $env:PORT = "5055"; $env:WAITRESS_THREADS = "4"
python serve.py                                    # dans un premier terminal
$env:API_KEY = "ecode_..."; $env:WORKLOAD = "typical"      # typical | small | a4 | pdf | mix
locust -f stress/locustfile.py --headless -u 4 -r 4 -t 30s --host http://127.0.0.1:5055 --csv stress/results/run
python stress/setup_stress_db.py drop              # supprime la base de test
```

Le script `setup_stress_db.py` ne touche qu'à la base `barcode_stress`, jamais à la vraie base.
