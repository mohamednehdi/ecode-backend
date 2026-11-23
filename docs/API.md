# API eCode : guide du développeur

Service web d'extraction de codes-barres (1D, QR Code, DataMatrix…) pour images et PDF. Une seule route à connaître :
`POST /api/v1/extract`.

> **Documentation interactive** : `http://<serveur>/api/docs/` (Swagger : on y saisit sa clé, on envoie un fichier, on voit la réponse).
> La description complète au format OpenAPI 3 est sur `/api/v1/openapi.json` : elle s'importe telle quelle dans Postman ou dans un
> générateur de code client.

## 1. En 30 secondes

```powershell
curl.exe -X POST http://localhost:5000/api/v1/extract -H "X-API-Key: ecode_VOTRE_CLE" -F "file=@document.pdf"
```

## 2. Authentification

Chaque requête porte l'en-tête **`X-API-Key`** avec la clé donnée par l'administrateur (de la forme `ecode_…`). La clé n'est affichée
qu'une fois à sa création : la conserver dans un coffre de secrets ou une variable d'environnement, jamais dans le code source ni
côté navigateur. L'administrateur peut limiter une clé à certaines adresses IP, à certains types de codes, à une période de
validité et à des quotas.

**Renouvellement.** Si l'administrateur renouvelle votre clé avec une période de grâce, l'ancienne clé continue de marcher jusqu'à une
heure fixée ; chaque réponse obtenue avec l'ancienne clé porte alors l'en-tête **`X-API-Key-Replaced-Until`** (date et heure UTC de la fin).
Passez à la nouvelle clé avant cette heure : après, l'ancienne donne 401.

## 3. La requête

`POST /api/v1/extract`, en `multipart/form-data` :

| Élément | Détail |
|---|---|
| Champ `file` (obligatoire) | une image **PNG** ou **JPG**, ou un **PDF**. 10 Mo au plus par défaut. Le contenu doit correspondre à l'extension |
| PDF | 20 pages au plus par défaut ; les pages sont rendues à 200 dpi |
| `?thorough=1` (facultatif) | mode approfondi : voir §6 |

## 4. La réponse (200)

```json
{
  "file_type": "pdf",
  "page_count": 3,
  "barcodes": [
    { "page": 1, "type": "QRCODE", "data": "HELLO-QR",
      "coordinates": { "x": 207, "y": 402, "w": 363, "h": 363 },
      "polygon": [[207, 402], [570, 403], [570, 764], [207, 765]] }
  ],
  "unread_regions": []
}
```

| Champ | Sens |
|---|---|
| `file_type` | `image` ou `pdf` |
| `page_count` | nombre de pages analysées (1 pour une image) |
| `barcodes[]` | un élément par code lu ; **vide** (et statut 200) si aucun code n'a été trouvé |
| `page` | numéro de la page, à partir de 1 |
| `type` | `QRCODE`, `DataMatrix`, `CODE128`, `EAN13`, `EAN8`, `UPCA`, `UPCE`, `CODE39`, `CODE93`, `CODABAR`, `I25`, `DATABAR`, `DATABAR_EXP`, `PDF417`, `Aztec`, `MaxiCode` |
| `data` | contenu du code |
| `coordinates` | boîte englobante en pixels de l'image d'origine (pour un PDF : de la page rendue à 200 dpi) : `x`, `y` = coin haut gauche, `w`, `h` = largeur et hauteur |
| `polygon` | les 4 coins `[x, y]` du contour réel : suit l'inclinaison du code |
| `unread_regions[]` | zones qui **ressemblent** à un code mais n'ont pas pu être lues, avec une confiance `score` de 0 à 1. Seulement quand la localisation a été faite (§6). Environ 4 sur 5 sont de fausses alertes : un indice, pas un résultat |

Les accents sont échappés dans le JSON (`é`) : un lecteur JSON les restitue normalement.

## 5. Les erreurs

Toute erreur a la forme `{"error": "message lisible"}`.

| Statut | Cause | Que faire |
|---|---|---|
| **400** | pas de champ `file` ; extension et contenu différents ; image illisible ; PDF illisible ou protégé par mot de passe ; PDF trop long ; image trop grande en pixels (plus de 50 millions) | corriger le fichier ; **ne pas réessayer tel quel** |
| **401** | en-tête `X-API-Key` absent, ou clé inconnue | vérifier la clé |
| **403** | clé désactivée, pas encore valide, expirée, ou adresse IP non autorisée | contacter l'administrateur |
| **413** | fichier trop gros | réduire le fichier |
| **415** | extension autre que PDF, PNG, JPG | convertir le fichier |
| **429** | quota de la clé dépassé (par heure ou par mois) | attendre ; le message dit quel quota |
| **500** | erreur interne | réessayer plus tard, signaler si elle persiste |

Exemples réels :

```
401  {"error": "Clé API invalide"}
400  {"error": "Le fichier n'est pas une image valide"}
400  {"error": "Image trop grande (max 50 millions de pixels)"}
415  {"error": "Format non supporté (PDF, PNG ou JPG uniquement)"}
429  {"error": "Quota horaire dépassé (100 requêtes par heure)"}
```

## 6. Quotas, vitesse et modes de lecture

- **Quotas** : par heure (fenêtre glissante) et par mois (mois civil UTC), fixés par clé. **Toute requête acceptée compte**, même si
  le fichier se révèle illisible (400 ou 500 après réception).
- **Mode rapide (défaut)** : lecture directe de la page ; si rien n'est trouvé, les codes sont localisés puis lus un par un.
  Mesuré sur un portable 4 cœurs : ≈ 50 ms pour une image d'environ 1 mégapixel, ≈ 190 ms pour un scan A4, ≈ 350 ms pour un PDF d'une page
  (détails dans `docs/PERFORMANCE.md`).
- **Mode approfondi (`?thorough=1`)** : les codes sont localisés sur **chaque** page, même si un premier code a été lu. À utiliser quand une
  page peut porter **plusieurs codes** : sur nos pages de test à 1 à 3 codes, 93 % des codes sont lus contre 77 % en mode rapide, pour
  ≈ 50 ms de plus par page (`docs/REGIONS_DECODING.md`).
- **Boîte d'un code 1D** : en mode approfondi (ou quand la localisation a servi à le lire) c'est le code entier ; en lecture rapide
  directe, ce n'est que la ligne de balayage lue. Pour une boîte fiable, utiliser `polygon` en mode approfondi.
- **Pour aller plus vite** : n'envoyer que la zone utile (un recadrage du code) plutôt que la page entière.

## 7. Exemples

Les exemples de ce dossier ont été **exécutés** sur un serveur local avant d'être publiés.

**curl** (Windows : `curl.exe`) :

```powershell
curl.exe -X POST "http://localhost:5000/api/v1/extract?thorough=1" -H "X-API-Key: ecode_VOTRE_CLE" -F "file=@photo.jpg"
```

**Python** : [`docs/examples/extract.py`](examples/extract.py) (paquet `requests`).

```powershell
$env:ECODE_URL = "http://localhost:5000"; $env:ECODE_KEY = "ecode_VOTRE_CLE"
python docs/examples/extract.py sample_barcodes.pdf
```

```
pdf, 3 page(s), 5 code(s)
  page 1  CODE128    ABC-123   at (955, 377) 366x245
  page 1  QRCODE     HELLO-QR   at (207, 402) 363x363
  page 1  DataMatrix HELLO-DM   at (181, 1154) 304x303
  page 2  EAN13      5901234123457   at (239, 381) 493x237
  page 2  QRCODE     https://www.progress.com.tn   at (198, 948) 437x437
```

**JavaScript** (Node.js 18 ou plus, rien à installer) : [`docs/examples/extract.mjs`](examples/extract.mjs) ; même sortie.

```powershell
node docs/examples/extract.mjs sample_barcodes.pdf
```

Le noyau de l'appel, en Python :

```python
import requests
response = requests.post(
    "http://localhost:5000/api/v1/extract",
    headers={"X-API-Key": "ecode_VOTRE_CLE"},
    files={"file": open("document.pdf", "rb")},
    timeout=60,
)
if response.status_code == 200:
    for code in response.json()["barcodes"]:
        print(code["page"], code["type"], code["data"])
else:
    print(response.status_code, response.json()["error"])
```

## 8. Bonnes pratiques

- Mettre un **délai maximal** à l'appel (60 s dans les exemples) : un gros PDF peut prendre plusieurs secondes.
- **Ne réessayer** que les 429 (après attente) et les 500 ; jamais les 400, 401, 403, 413 ou 415.
- Ne pas envoyer en rafale : le quota de la clé est partagé par tous les appels qui l'utilisent.
- Garder la clé côté serveur ; si elle fuit, demander à l'administrateur de la désactiver et d'en créer une autre.
