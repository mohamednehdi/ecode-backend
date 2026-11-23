# F9. Durcissement de la sécurité : modèle de menaces et mesures

Ce document sert de base à la section « sécurité » du rapport. Il dit ce qu'on protège, contre qui, ce qui existait déjà, ce qui a été
ajouté en F9, comment chaque mesure a été vérifiée, et ce qui reste **non protégé**.

## 1. Ce qu'on protège (les « actifs »)

| Actif | Pourquoi il compte |
|---|---|
| Le compte administrateur | il crée, modifie et supprime les clés API et voit les statistiques |
| Les clés API des clients | une clé volée = un tiers consomme le quota d'un client |
| Les fichiers envoyés | des documents de clients (bons, factures) : ils ne doivent ni fuiter ni être gardés |
| La disponibilité du service | le décodage coûte du processeur et de la mémoire : un envoi hostile peut le saturer |
| Le journal d'audit | il ne vaut que s'il est complet et impossible à modifier par l'interface |

## 2. Qui attaque (les « attaquants »)

1. **Un inconnu sur Internet** : accès à la page publique gratuite et à la page de connexion, sans aucun compte.
2. **Un client titulaire d'une clé** : peut envoyer beaucoup de fichiers, ou laisser fuiter sa clé.
3. **Un administrateur dont le mot de passe ou la session est volé** : agit « en tant que » l'administrateur.
4. **Un administrateur malhonnête ou maladroit** : modifie une clé et nie l'avoir fait.

Hors périmètre : un attaquant qui a déjà la main sur le serveur ou la base de données.

## 3. Menaces, mesures existantes, mesures ajoutées

| # | Menace | Déjà en place (avant F9) | Ajouté en F9 |
|---|---|---|---|
| T1 | Deviner un mot de passe par essais successifs | bcrypt (hachage lent) | **verrou par adresse e-mail** : 5 échecs ⇒ 429 pendant 15 minutes ; limite de 20 essais par minute et par IP |
| T2 | Découvrir quelles adresses ont un compte (« énumération ») | message d'erreur identique | une adresse **inconnue** est verrouillée exactement comme une adresse réelle ; un faux compte coûte le même temps de calcul (bcrypt sur un faux haché) |
| T3 | Inonder la réinitialisation du mot de passe (courriels, devinette du code) | code à usage unique | 3 demandes par heure et par adresse, 5 par heure et par IP, 20 étapes par heure |
| T4 | Clé API volée ou perdue | clés hachées en base, affichées une seule fois ; liste d'IP, quotas, validité | **renouvellement de la clé** avec période de grâce (0 à 168 h) : l'ancienne clé reste valable jusqu'à l'heure dite, puis meurt ; en-tête `X-API-Key-Replaced-Until` pour prévenir le client |
| T5 | Un administrateur modifie ou supprime une clé sans trace | aucune | **journal d'audit** : qui, quoi, sur quelle clé, depuis quelle IP, succès ou échec ; aucune route d'écriture ni de suppression |
| T6 | Fuite de secrets dans le journal | — | les champs `password`, `secret`, `api_key`, `token_hash`, `jwt`, `authorization` sont masqués avant écriture |
| T7 | Injection de formules dans l'export CSV du journal (Excel exécute une cellule qui commence par `=`) | — | toute cellule commençant par `= + - @` ou une tabulation est préfixée d'une apostrophe |
| T8 | Image « bombe de décompression » (quelques ko qui déclarent 100 000 × 100 000 pixels) | limite de taille du fichier (10 Mo) | l'en-tête est lu **avant** le décodage : plus de 50 millions de pixels ⇒ 400 « Image trop grande » |
| T9 | PDF avec une page géante, ou beaucoup de pages | limite de pages (20) | le facteur d'agrandissement est réduit pour rester sous 50 millions de pixels par page et 100 millions par document ; une page absurde est refusée |
| T10 | Clickjacking, détection de type, mise en cache de réponses sensibles | — | en-têtes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Cache-Control: no-store`, `Content-Security-Policy` ; `Strict-Transport-Security` seulement sur une requête arrivée en HTTPS |
| T11 | Un journal qui bloque l'action quand il tombe en panne | — | l'écriture du journal ne lève jamais d'erreur : l'action de l'administrateur aboutit quand même (testé) |
| T12 | Journal qui grossit sans fin | — | commande `flask --app run purge-audit --keep-days 365` |

## 4. Comment chaque mesure a été vérifiée

Le backend passe de 47 à **75 tests** ; le site Angular passe de 86 à **107 tests unitaires** et de 5 à **6 tests de bout en bout**.

- **Verrou** : 5 échecs ⇒ 429 ; adresse inconnue = adresse réelle (même code, même message) ; les connexions réussies ne comptent pas ;
  le verrou se lève quand la fenêtre se termine ; la limite par IP existe ; un test mesure que le temps de réponse d'un compte inconnu
  et celui d'un compte réel ne diffèrent pas de façon exploitable.
- **Journal** : chaque événement est écrit ; aucun mot de passe ni clé n'y apparaît ; un non-administrateur reçoit 403 ; aucune route
  `POST/PUT/DELETE` ; filtres, pagination et validation des paramètres ; export CSV neutralisé ; panne du journal sans effet sur l'action.
- **Renouvellement** : ancienne clé valable pendant la grâce, morte à 0 h, morte après expiration (testé en vieillissant la date en base),
  deux renouvellements de suite, validation du paramètre, accès réservé à l'administrateur.
- **Fichiers hostiles** : PNG construit à la main qui déclare une taille énorme (rejeté sans décoder), PDF à page géante (rendu réduit).
- **En-têtes** : présents partout, la page `/api/docs/` n'a pas ceux qui casseraient Swagger, HSTS absent en HTTP.
- **Tests prouvés capables d'échouer** : on a cassé le code exprès (par exemple retirer la neutralisation CSV, ne plus compter les échecs
  d'une adresse inconnue) et vérifié que le test prévu échoue, puis restauré.
- **Sur une vraie base MySQL/MariaDB** (une base jetable, la vraie base de l'utilisateur n'a pas été touchée) : migration montée, descendue,
  remontée ; filtres, pagination, export CSV, purge, verrou et renouvellement exécutés.
- **Dans un vrai navigateur** : page « Audit log » et panneau de renouvellement regardés ; la colonne d'actions, trop serrée, a été corrigée.

## 5. Ce qui a mal tourné en chemin

- Un premier test de l'export CSV utilisait des majuscules alors que la connexion met les adresses en minuscules : test corrigé, pas le code.
- Un test de durée oubliait `import time`.
- La première version d'une « cassure volontaire » ne s'était pas appliquée (mauvais motif de recherche) : elle a été refaite pour que la
  preuve soit réelle.
- Au départ la MySQL de l'utilisateur était arrêtée : la migration a été essayée sur une instance jetable (port 3307), puis supprimée.

## 6. Limites connues (honnêtement)

| Limite | Conséquence |
|---|---|
| **Le HTTPS n'est pas dans `docker-compose`** (choix assumé : hors périmètre de la démonstration, voir `DEPLOYMENT.md`) | la démo tourne en HTTP sur `localhost`, sans risque ; **en production le HTTPS est obligatoire**, mis en place devant l'application avec le domaine de l'entreprise ; l'en-tête HSTS est déjà prêt |
| Les compteurs du verrou sont **en mémoire** par défaut | un redémarrage les efface, et plusieurs serveurs ne les partagent pas : il faut `RATELIMIT_STORAGE_URI=redis://…` (déjà prévu pour F1) |
| Un PDF hostile peut encore consommer jusqu'à environ 0,5 Go sur la page publique | borné par les limites de pages et de pixels et par la limite de débit, pas supprimé |
| Le verrou par e-mail permet à un attaquant de **verrouiller** un administrateur en essayant son adresse | compromis assumé (15 min) ; la limite par IP et le journal permettent de le voir |
| Le journal est dans la même base que les données | un attaquant qui a la base peut le modifier ; une copie vers un système externe n'est pas faite |
| Pas d'authentification à deux facteurs, pas de rôle intermédiaire | un seul niveau d'administrateur |
| Les requêtes refusées par le service web (401, 403, 429) ne sont pas dans le journal d'audit | l'audit couvre l'administration et la connexion, pas l'usage de l'API |
| Analyse de sécurité faite par les tests de l'équipe, **pas d'audit externe ni de test d'intrusion** | à dire tel quel dans le rapport |

## 7. Comment l'essayer

```powershell
pytest -k "lock or audit or rotat or header or hostile"        # tests de F9
flask --app run purge-audit --keep-days 365                     # purge du journal
```

- Verrou : se tromper 6 fois de mot de passe sur la page de connexion ⇒ « Trop de tentatives de connexion. Réessayez dans N minute(s). »
- Journal : menu **Audit log** du back office (filtres par action, succès, texte ; export CSV).
- Renouvellement : page **API Tokens**, bouton **Renouveler** sur une clé ; la nouvelle clé est affichée une fois.
- Migration : `.\upgrade_db.bat` (la base doit être à la révision `e8c2f6a41b7d`).

## 8. Variables de configuration ajoutées

`LOGIN_MAX_FAILURES` (5), `LOGIN_LOCK_MINUTES` (15), `LOGIN_RATE_LIMIT` (`20 per minute`), `RESET_REQUEST_LIMIT`, `RESET_EMAIL_LIMIT`,
`RESET_STEP_LIMIT`, `MAX_IMAGE_PIXELS` (50 000 000), `MAX_DOCUMENT_PIXELS` (100 000 000), `HSTS_SECONDS` (31 536 000).

## 9. En une phrase pour le rapport

Un inconnu ne peut plus deviner un mot de passe à la chaîne ni savoir quels comptes existent ; une clé volée se remplace sans coupure ;
chaque action d'administration laisse une trace qu'on ne peut pas effacer depuis l'interface ; un fichier piégé est refusé avant d'user la
mémoire. Pour une mise en production : le HTTPS devant l'application, le stockage partagé des compteurs (Redis), et un audit extérieur.
