# Tests et intégration continue (F7)

Document de travail pour le rapport : le besoin, ce qui a été construit, ce qu'on a trouvé en route, comment c'est vérifié,
et surtout **ce qui n'a pas pu être vérifié**.

## 1. Le besoin

À ce stade, le backend avait des tests (47) mais ils ne tournaient que quand on y pensait ; le site Angular avait 11 tests qui ne
testaient rien. Rien ne disait automatiquement « ce commit casse quelque chose ». F7 apporte : des tests qui comptent, mesurés
(couverture), lancés **automatiquement à chaque `push`** par GitHub Actions, et un test de bout en bout du parcours principal.

## 2. Ce qui a été construit

| Où | Quoi |
|---|---|
| Backend | `pytest.ini`, `.coveragerc` (couverture instructions + branches), `ruff.toml` (lint), `requirements-dev.txt` allégé (tests seulement) et `requirements-bench.txt` (études), `README.md`, `.github/workflows/ci.yml` |
| Frontend | **86 tests unitaires** (Jasmine/Karma), `karma.conf.js` (ordre aléatoire, lanceur sans fenêtre pour la CI), **5 tests de bout en bout** (Playwright : `e2e/`, `playwright.config.ts`), `.npmrc`, `README.md`, `.github/workflows/ci.yml` |

### Les pipelines (GitHub Actions)

| Dépôt | Job | Ce qu'il fait |
|---|---|---|
| Backend | Lint | `ruff check .` |
| | Tests et couverture | installe les bibliothèques système, `pytest --cov`, **échoue sous 90 %** (mesuré : 92 % sous Windows, 91,6 % sous Linux), publie la couverture |
| | Docker | construit l'image, la démarre, appelle `/health` |
| Frontend | Build et tests unitaires | `npm ci`, `npm run build`, tests avec couverture dans Chrome sans fenêtre |
| | Bout en bout | récupère le dépôt du backend, prépare une base SQLite et un administrateur, démarre backend et site, lance Playwright |

## 3. Les chiffres

| Mesure | Valeur |
|---|---|
| Tests backend | **47** (tous passent) |
| Couverture backend | **92 %** sous Windows, **91,6 %** sous Linux (instructions et branches) ; le plus faible : l'envoi des e-mails par SMTP (`app/auth/services.py`, 58 %), impossible à tester sans serveur de messagerie |
| Tests unitaires frontend | **86** (11 avant, dont 9 en échec) ; ordre aléatoire, deux exécutions de suite sans échec |
| Couverture frontend | **95,8 % des lignes**, 95,0 % des instructions, 92,9 % des fonctions, **73,6 % des branches** (20 fichiers testés) |
| Bout en bout | **5 tests** : page publique (lecture d'un code QR ; refus d'un mauvais type), accès refusé à un visiteur, mauvais mot de passe, et le parcours complet de l'administrateur (connexion → création d'une clé → appel du service web avec cette clé → la requête apparaît dans les statistiques → désactivation, le service refuse → suppression) |

## 4. Ce qu'on a trouvé en route

1. **9 des 11 tests Angular existants échouaient.** C'étaient les squelettes générés par Angular (« should create ») : aucun ne fournissait `HttpClient`,
   donc aucun ne pouvait passer depuis longtemps. Ils ont été remplacés par de vrais tests (un test qui ne vérifie rien n'est pas conservé).
2. **Un simple `npm ci` échouait déjà sur le dépôt d'origine** : les paquets Angular sont sur des versions `17.3.x` différentes
   (`core` 17.3.9, `animations` et `forms` 17.3.8) avec des dépendances croisées exactes. Une machine neuve (donc la CI) n'aurait pas pu installer le site.
   Remède minimal : un fichier `.npmrc` (`legacy-peer-deps=true`). Le remède propre, aligner les paquets `@angular/*`, **n'a pas été fait** (dette technique).
3. **Un faux succès de ma part** : ma première exécution des tests dans un conteneur Linux a rendu le code 0 sans avoir exécuté le lint ni les tests
   (les guillemets du script avaient été abîmés par Windows). Je ne l'ai pas cru, car la sortie s'arrêtait trop tôt ; le script est maintenant un fichier
   monté dans le conteneur, et la sortie montre le lint, l'installation et les tests.
4. **Le lint a trouvé 6 imports inutiles** (dont deux dans `app/quota.py`), corrigés.
5. **Les tests passaient sous Windows et échouaient sous Linux : 16 sur 47.** Cause : `pylibdmtx`, qui sert aux tests à fabriquer des images DataMatrix,
   importe le module `distutils`, **supprimé de Python 3.12**. L'environnement Windows avait `setuptools`, qui le fournit en douce ; un Python 3.12 neuf (celui de
   GitHub) ne l'a pas. Sans l'exécution sous Linux, **le premier passage du pipeline sur GitHub aurait échoué**. Correctif : `setuptools` dans `requirements-dev.txt`.
   (L'image Docker de production n'est pas concernée : elle n'utilise pas `pylibdmtx`.)

## 5. Comment on s'est assuré que les tests savent échouer

Un test qui n'a jamais échoué n'a pas prouvé qu'il savait le faire. Pour les tests ajoutés, des **pannes volontaires** ont été introduites dans le code,
une à la fois, puis annulées :

| Panne introduite | Test qui l'a attrapée |
|---|---|
| la garde d'accès laisse entrer tout utilisateur connecté (plus de contrôle du rôle) | « refuse un utilisateur connecté qui n'est pas administrateur » |
| l'intercepteur envoie le jeton à n'importe quel site | « n'envoie jamais le jeton à un autre site » |
| le graphique empile le total des requêtes au lieu des seules requêtes réussies | « sépare chaque jour en requêtes réussies et en erreur » |
| le lien « Statistics » du menu est renommé | le test de bout en bout (`waiting for getByRole('link', { name: 'Statistics' })`) |

Dans chaque cas un seul test échoue, celui prévu, et les fichiers ont été remis à l'identique.

## 6. Comment on a vérifié les pipelines sans GitHub

**Les pipelines n'ont jamais tourné sur GitHub** (rien n'a été envoyé). Ce qui a été fait à la place :

| Vérification | Résultat |
|---|---|
| `actionlint` (outil de contrôle des fichiers GitHub Actions) sur les deux `ci.yml` | aucune erreur (après correction de deux remarques de `shellcheck`) |
| Étapes du job « Lint » et « Tests » du backend dans un conteneur **Ubuntu 24.04** vierge (le système de `ubuntu-latest`) | lint sans erreur ; **47 tests passent** ; couverture **91,6 %** (seuil 90 %). Un premier passage avait échoué (16 tests, voir §4 point 5) : il a été corrigé puis rejoué en entier |
| Job « Docker » du backend (mêmes commandes, en local) | l'image se construit et démarre ; `/health` répond `{"status":"ok"}` et la page `/api/docs/` répond 200 |
| Commande des tests unitaires du frontend (`npm run test:ci`) | passe, deux fois, avec Edge comme navigateur sans fenêtre |
| Test de bout en bout | passe sur une pile isolée (backend sur le port 5057, base SQLite jetable, copie du site sur le port 4301), avec Edge |

## 7. Limites (à dire au jury)

- **Pas encore d'exécution réelle sur GitHub.** Le badge d'état des README n'affichera rien tant qu'une première exécution n'aura pas eu lieu. Rien n'est garanti
  tant qu'elle n'a pas réussi : un paquet système, un droit d'accès ou une version d'outil peut encore faire échouer le premier passage.
- **Le job de bout en bout du frontend récupère le dépôt du backend** : s'il est privé, il faut créer un secret `BACKEND_REPO_TOKEN` (un jeton qui peut le lire).
- **Navigateurs** : en local, Edge a remplacé Chrome/Chromium ; la CI utilisera Chrome (tests unitaires) et Chromium (bout en bout), non essayés ici.
- **Couverture** : chiffres sur les fichiers que les tests chargent ; les fichiers de modules et de routage ne sont pas comptés. Branches frontend : 73,6 %.
  Backend : l'envoi d'e-mails (58 %) n'est pas testé.
- **Pas de test de charge ni de test de vitesse dans la CI** (voir `docs/PERFORMANCE.md`), **pas de lint du frontend**, un seul navigateur en bout en bout,
  aucun test sur téléphone.
- Les tests du backend utilisent SQLite ; MySQL n'est exercé qu'à la main (par exemple pour les statistiques, `docs/STATISTICS.md`).

## 8. Ce qu'on peut dire à la soutenance

« À chaque envoi de code, un pipeline lance le lint, 47 tests du backend (92 % de couverture) et 86 tests du site, construit le conteneur Docker,
et rejoue le parcours complet de l'administrateur dans un vrai navigateur. J'ai vérifié que les tests savent échouer en cassant volontairement
le code. En le mettant en place j'ai découvert que 9 tests Angular sur 11 ne passaient plus et que le site ne pouvait pas s'installer sur une machine
neuve. Je n'ai pas pu lancer GitHub Actions moi-même : j'ai validé les fichiers avec un outil dédié et rejoué les étapes sur Linux. »
