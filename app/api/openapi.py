"""OpenAPI 3 description of the web service (served at /api/v1/openapi.json, shown by Swagger UI at /api/docs).

It is built from the code and the settings, not typed once and forgotten: the list of barcode types, the upload limit
and the page limit come from the running configuration. tests/test_api.py checks that every documented answer
(status code, message, JSON shape) is what the service really sends.
"""
from app.scans.decoder import SUPPORTED_TYPES


def _error_examples(*pairs):
    return {name: {'summary': name, 'value': {'error': message}} for name, message in pairs}


def _error_response(description, *pairs):
    return {'description': description,
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Error'},
                                             'examples': _error_examples(*pairs)}}}


def build_spec(config):
    max_mb = config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    max_pages = config['PDF_MAX_PAGES']
    dpi = config['PDF_DPI']
    max_pixels = config['MAX_IMAGE_PIXELS']

    description = f"""
Service web de **localisation et d'extraction de codes-barres** (1D, QR Code, DataMatrix…) dans des images et des PDF
de plusieurs pages. Il répond en JSON.

## Authentification
Chaque appel doit porter l'en-tête **`X-API-Key`** avec la clé fournie par l'administrateur (clé `ecode_…`).
La clé n'est affichée qu'une fois à sa création. Une clé peut être limitée à certaines adresses IP, à certains types de
codes, à une période de validité et à des quotas.

## Fichiers acceptés
PNG, JPG/JPEG et PDF (champ multipart `file`), **{max_mb} Mo au plus**. Un PDF peut avoir **{max_pages} pages au plus** ;
ses pages sont rendues à {dpi} dpi. Le contenu du fichier doit correspondre à son extension.

## Quotas
Une clé peut avoir un quota **par heure** (fenêtre glissante) et un quota **par mois** (mois civil, UTC). Toute requête
acceptée compte, même si le fichier se révèle illisible. Au-delà : réponse **429**.

## Deux modes de lecture
- **Rapide** (défaut) : lecture directe de la page ; si rien n'est trouvé, les codes sont localisés puis lus un par un
  (découpés, redressés, agrandis). Ordre de grandeur mesuré sur un portable 4 cœurs : ≈ 50 ms pour une image d'environ
  1 mégapixel, ≈ 190 ms pour un scan A4, ≈ 350 ms pour un PDF d'une page.
- **Approfondi** (`?thorough=1`) : les codes sont localisés sur **chaque** page, même si un code a déjà été lu. Trouve les autres
  codes d'une page (sur des pages de documents à plusieurs codes : 93 % lus contre 77 %) pour environ 50 ms de plus par page.

## Position des codes
`coordinates` est la boîte englobante (x, y = coin haut gauche, largeur et hauteur en pixels de l'image d'origine ; pour un PDF,
de la page rendue). `polygon` donne les 4 coins du contour réel, utile quand le code est incliné.
Pour un code 1D, la boîte est celle du code entier en mode approfondi, ou lorsque la lecture s'est faite par localisation ;
en lecture rapide directe, ce n'est que la ligne de balayage lue.

## Zones non lues
`unread_regions` liste les zones qui **ressemblent** à un code-barres mais n'ont pas pu être lues (uniquement quand la localisation a
été faite). Beaucoup sont de fausses alertes (environ 4 sur 5 dans nos mesures) : à utiliser comme indice, pas comme résultat.
""".strip()

    coordinates = {
        'type': 'object', 'required': ['x', 'y', 'w', 'h'],
        'properties': {k: {'type': 'integer', 'minimum': 0, 'description': d} for k, d in
                       (('x', 'Abscisse du coin haut gauche (pixels)'), ('y', 'Ordonnée du coin haut gauche (pixels)'),
                        ('w', 'Largeur (pixels)'), ('h', 'Hauteur (pixels)'))},
    }

    return {
        'openapi': '3.0.3',
        'info': {'title': "eCode : extraction de codes-barres", 'version': '1.0.0', 'description': description},
        'servers': [{'url': '/', 'description': 'Ce serveur'}],
        'tags': [{'name': 'Extraction', 'description': 'Lire les codes-barres d\'un fichier'},
                 {'name': 'Service', 'description': 'État du service'}],
        'paths': {
            '/api/v1/extract': {'post': {
                'tags': ['Extraction'],
                'summary': 'Extraire les codes-barres d\'une image ou d\'un PDF',
                'operationId': 'extract',
                'security': [{'ApiKeyAuth': []}],
                'parameters': [{
                    'name': 'thorough', 'in': 'query', 'required': False,
                    'description': 'Mode approfondi : localiser et lire les codes de chaque page, même si un code a déjà été lu '
                                   '(un peu plus lent). Accepte `1`, `true` ou `yes`.',
                    'schema': {'type': 'boolean', 'default': False}}],
                'requestBody': {'required': True, 'content': {'multipart/form-data': {
                    'schema': {'type': 'object', 'required': ['file'], 'properties': {
                        'file': {'type': 'string', 'format': 'binary',
                                 'description': f'Image PNG ou JPG, ou PDF ({max_mb} Mo au plus)'}}},
                    'encoding': {'file': {'contentType': 'image/png, image/jpeg, application/pdf'}}}}},
                'responses': {
                    '200': {'description': 'Fichier analysé. `barcodes` est vide si aucun code n\'a été trouvé.',
                            'content': {'application/json': {
                                'schema': {'$ref': '#/components/schemas/ExtractResponse'},
                                'examples': {'Un code QR': {'value': {
                                    'file_type': 'image', 'page_count': 1,
                                    'barcodes': [{'page': 1, 'type': 'QRCODE', 'data': 'HELLO-QR',
                                                  'coordinates': {'x': 50, 'y': 50, 'w': 140, 'h': 140},
                                                  'polygon': [[50, 50], [190, 50], [190, 190], [50, 190]]}],
                                    'unread_regions': []}}}}}},
                    '400': _error_response(
                        'Requête ou fichier invalide.',
                        ('Aucun fichier', 'Aucun fichier reçu (champ multipart "file")'),
                        ('Extension et contenu différents', 'Le contenu du fichier ne correspond pas à son extension'),
                        ('Image illisible', "Le fichier n'est pas une image valide"),
                        ('Image trop grande', f'Image trop grande (max {max_pixels // 1_000_000} millions de pixels)'),
                        ('PDF invalide', 'Le fichier PDF est invalide ou protégé par mot de passe'),
                        ('PDF trop long', f'Le PDF contient trop de pages (max {max_pages})')),
                    '401': _error_response(
                        'Clé API absente ou inconnue.',
                        ('Clé absente', 'Clé API manquante (en-tête X-API-Key)'),
                        ('Clé inconnue', 'Clé API invalide')),
                    '403': _error_response(
                        'Clé reconnue mais refusée.',
                        ('Clé désactivée', 'Clé API désactivée'),
                        ('Pas encore valide', 'Clé API pas encore valide'),
                        ('Expirée', 'Clé API expirée'),
                        ('Adresse IP refusée', 'Adresse IP non autorisée pour cette clé')),
                    '413': _error_response('Fichier trop volumineux.',
                                           ('Trop volumineux', f'Fichier trop volumineux (max {max_mb} Mo)')),
                    '415': _error_response('Extension non prise en charge.',
                                           ('Format inconnu', 'Format non supporté (PDF, PNG ou JPG uniquement)')),
                    '429': _error_response(
                        'Quota de la clé dépassé.',
                        ('Quota horaire', 'Quota horaire dépassé (100 requêtes par heure)'),
                        ('Quota mensuel', 'Quota mensuel dépassé (5000 requêtes par mois)')),
                    '500': _error_response('Erreur interne pendant le traitement.',
                                           ('Erreur interne', 'Erreur interne lors du traitement du fichier')),
                },
            }},
            '/health': {'get': {
                'tags': ['Service'], 'summary': 'Le service répond-il ?', 'operationId': 'health', 'security': [],
                'responses': {'200': {'description': 'Le service fonctionne.', 'content': {'application/json': {
                    'schema': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ok']}}},
                    'example': {'status': 'ok'}}}}}}},
        },
        'components': {
            'securitySchemes': {'ApiKeyAuth': {
                'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key',
                'description': 'Clé fournie par l\'administrateur, de la forme `ecode_…`.'}},
            'schemas': {
                'Error': {'type': 'object', 'required': ['error'],
                          'properties': {'error': {'type': 'string', 'description': 'Message lisible (en français)'}}},
                'Coordinates': coordinates,
                'Barcode': {
                    'type': 'object', 'required': ['page', 'type', 'data', 'coordinates'],
                    'properties': {
                        'page': {'type': 'integer', 'minimum': 1, 'description': 'Numéro de la page (1 pour une image)'},
                        'type': {'type': 'string', 'enum': list(SUPPORTED_TYPES), 'description': 'Type du code'},
                        'data': {'type': 'string', 'description': 'Contenu du code'},
                        'coordinates': {'$ref': '#/components/schemas/Coordinates'},
                        'polygon': {'type': 'array', 'minItems': 4, 'maxItems': 4,
                                    'items': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'integer'}},
                                    'description': 'Les 4 coins [x, y] du contour du code (suit son inclinaison)'}}},
                'UnreadRegion': {
                    'type': 'object', 'required': ['page', 'coordinates', 'score'],
                    'properties': {
                        'page': {'type': 'integer', 'minimum': 1},
                        'coordinates': {'$ref': '#/components/schemas/Coordinates'},
                        'score': {'type': 'number', 'minimum': 0, 'maximum': 1,
                                  'description': 'Confiance du localisateur que c\'est bien un code (0 à 1)'}}},
                'ExtractResponse': {
                    'type': 'object', 'required': ['file_type', 'page_count', 'barcodes', 'unread_regions'],
                    'properties': {
                        'file_type': {'type': 'string', 'enum': ['image', 'pdf']},
                        'page_count': {'type': 'integer', 'minimum': 1},
                        'barcodes': {'type': 'array', 'items': {'$ref': '#/components/schemas/Barcode'}},
                        'unread_regions': {'type': 'array', 'items': {'$ref': '#/components/schemas/UnreadRegion'},
                                           'description': 'Zones qui ressemblent à un code mais n\'ont pas pu être lues'}}},
            },
        },
    }
