# Documentation de l'API (F5)

Document de travail pour le rapport : ce qui a été fait, pourquoi, comment c'est vérifié, ce qui reste faible.
Le guide destiné aux développeurs tiers est `docs/API.md`.

## 1. Le besoin

Le cahier des charges demande un service web destiné à **d'autres applications**. Une application ne peut pas l'utiliser si elle ne sait
pas : comment s'authentifier, ce qu'il faut envoyer, ce qui revient, ce que signifie chaque erreur, quelles sont les limites. Jusqu'ici
ces informations n'existaient que dans le code. F5 les met à disposition sous trois formes, dont **une qui ne peut pas mentir** (§4).

## 2. Ce qui a été construit

| Livrable | Où | Pour qui |
|---|---|---|
| Description **OpenAPI 3** du service | `GET /api/v1/openapi.json` (code : `app/api/openapi.py`) | outils : Postman, générateurs de clients |
| Page interactive **Swagger** | `/api/docs/` | développeurs : saisir sa clé, envoyer un fichier, lire la réponse |
| **Guide du développeur** | `docs/API.md` | lecture : authentification, réponse, erreurs, quotas, bonnes pratiques |
| Trois **exemples exécutables** | curl (dans le guide), `docs/examples/extract.py`, `docs/examples/extract.mjs` | copier-coller |
| Lien « API documentation » | menu du back office (Angular) | administrateur |

## 3. Choix de conception

| Question | Choix | Écarté, et pourquoi |
|---|---|---|
| Comment produire la description ? | **Construite par le code** (`build_spec`), à partir des réglages en cours | Un fichier YAML écrit une fois : il se périme (la liste des types de codes, la limite de taille et la limite de pages changent avec la configuration) |
| Comment afficher Swagger ? | Paquet `flask-swagger-ui` qui **contient** les fichiers de l'interface | Les charger depuis un CDN : la page ne marcherait pas sans Internet (salle de soutenance) |
| Langue | Français (comme les messages du service) | Anglais : les messages d'erreur du service sont en français, la documentation les cite |
| Exemples | curl, Python, JavaScript **exécutés pour de vrai** | C#, PHP… : je n'ai pas pu les exécuter ici, et je ne publie pas un exemple que je n'ai pas lancé |

## 4. Comment on s'assure que la documentation dit vrai

Trois tests automatiques (`tests/test_api.py`, 47 au total dans le projet) :

1. **La description est un document OpenAPI 3 valide**, servie correctement, la page Swagger répond et ses fichiers sont servis par le serveur
   lui-même ; la liste des types de codes de la description est celle du décodeur.
2. **Les exemples de la description respectent ses propres schémas** (18 exemples vérifiés).
3. **Chaque réponse documentée est ce que le service envoie réellement** : 21 requêtes réelles couvrent les **huit** codes de statut
   documentés (200, 400, 401, 403, 413, 415, 429, 500) et chaque message d'erreur ; pour chacune, le statut, le message (chiffres mis à part) et
   la forme du JSON doivent correspondre à la description. Si l'on change un message du service sans mettre à jour la description,
   **le test échoue**.

Le troisième test a été **éprouvé par une panne volontaire** : en changeant un message documenté (« Clé API invalide » en « Clé API
incorrecte »), il échoue, puis repasse après retour à l'état normal. Un test qui n'a jamais échoué n'a pas prouvé qu'il sait échouer.

Vérifications à la main, sur un serveur local avec une base MySQL jetable (supprimée ensuite) : les exemples Python et Node renvoient
les mêmes 5 codes sur `sample_barcodes.pdf` ; clé fausse → `401`, fichier invalide → `400`, extension `.gif` → `415`, absence de clé → `401` ;
la page `/api/docs/` répond ; dans un navigateur, Swagger affiche les deux opérations, le paramètre `thorough`, le champ `file` obligatoire,
le bouton « Authorize », les huit codes de réponse et les cinq schémas.

## 5. Ce qui a mal tourné

- Une accolade en trop dans la description (erreur de syntaxe Python) : trouvée au premier lancement de la validation.
- Rien d'autre n'a échoué : **les trois tests ont réussi du premier coup**, ce qui est la raison de l'épreuve par panne volontaire (§4).

## 6. Limites (à dire au jury)

- **Le bouton « Try it out » avec un vrai fichier n'a pas été essayé dans le navigateur** (l'outil que j'avais ne permet pas de choisir un
  fichier). Le même appel est prouvé par curl, Python et Node ; Swagger envoie un `multipart/form-data` standard, sans raison de faillir,
  mais je ne l'ai pas vu.
- Exemples vérifiés sur **un serveur local**, pas sur un serveur de production derrière Nginx.
- Un seul numéro de version (`1.0.0`) et une seule route métier : pas de politique de versions ni de dépréciation.
- Les chiffres de vitesse et de taux de lecture de la description (50 ms, 190 ms, 350 ms ; 93 % contre 77 %) viennent de mesures sur un
  portable avec des images **synthétiques** (`docs/PERFORMANCE.md`, `docs/REGIONS_DECODING.md`) : ce sont des ordres de grandeur.
- La description française n'est pas traduite ; pas de client généré (SDK).

## 7. Ce qu'on peut dire à la soutenance

« Pour qu'une autre application utilise le service, il faut une documentation qui ne puisse pas se tromper. La description OpenAPI est
construite par le code lui-même, et un test envoie des requêtes réelles pour chacun des huit statuts documentés et vérifie que les
réponses correspondent. J'ai vérifié que ce test sait échouer en cassant volontairement un message. La page Swagger est servie par le
serveur, sans Internet, et les exemples Python et Node ont été exécutés pour de vrai. »
