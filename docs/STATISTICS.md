# Tableau de bord statistique de l'administrateur (F4)

Document de travail pour le rapport : le besoin, ce qui a été construit et pourquoi, les choix écartés, ce qui a mal tourné,
comment on l'a vérifié, les limites, et comment le tester soi-même.

## 1. Le besoin

Le back office permettait de créer des clés API (F1 à F3 : le service lui-même). Il ne disait **rien de leur usage** : combien de
requêtes une application envoie, si elles réussissent, si le service tient l'objectif de 100 ms du cahier des charges. Un
administrateur doit pouvoir répondre à : « quelle clé consomme le plus ? », « y a-t-il des erreurs ? », « le service ralentit-il ? ».

Ce que F4 ajoute : le journal des requêtes enregistre maintenant le **résultat** de chaque requête, trois routes d'administration
le résument, et une page Angular l'affiche (chiffres clés, graphiques, tableau, export CSV).

## 2. Vue d'ensemble

```
POST /api/v1/extract ──► traitement ──► 1 ligne dans api_usage (résultat compris)
                                                  │
        GET /admin/stats/overview | recent | export.csv   (agrégats SQL, administrateur seulement)
                                                  │
                        page Angular  /dashboard/statistics
```

### Fichiers

| Où | Fichier | Rôle |
|---|---|---|
| Backend | `app/models/api_token.py` (`ApiUsage`) | 7 colonnes de résultat + index sur la date |
| | `migrations/versions/d4b7a1e90c53_api_usage_outcome.py`, `sql/step4_usage_stats.sql`, `upgrade_db.bat` | migration (Alembic, ou SQL à la main) |
| | `app/api/routes.py` (`_log_usage`) | écrit la ligne après le traitement |
| | `app/admin/stats.py` | les trois routes de statistiques |
| | `app/demo_data.py`, `app/__init__.py` | commandes `seed-demo-usage` et `clear-demo-usage` |
| | `tests/test_api.py` | 5 tests (44 au total dans le projet) |
| Frontend | `src/app/services/stats.service.ts` | appels HTTP, types des réponses |
| | `src/app/components/statistics/` | la page (filtres, tuiles, graphiques, tableau, export) |
| | `src/app/components/charts/` | `bar-chart`, `line-chart`, `hbar-chart` et `chart-scale.ts` |
| | `app.module.ts`, `app-routing.module.ts`, `app.component.html` | déclaration, route `/dashboard/statistics`, lien du menu |

## 3. Ce qui est enregistré

Chaque requête acceptée de `POST /api/v1/extract` (fichier valide, traité ou en échec pendant le traitement) écrit **une ligne**
dans `api_usage`, après le traitement :

| Colonne | Contenu |
|---|---|
| `created_at`, `ip_address` | arrivée de la requête (UTC), adresse du client (déjà présentes avant F4) |
| `status_code` | code HTTP rendu : 200, 400 (fichier invalide), 500 (erreur interne) |
| `duration_ms` | durée du traitement (extraction) |
| `codes_found`, `pages` | codes trouvés, pages analysées |
| `file_type`, `file_bytes` | `image` ou `pdf`, taille du fichier |
| `thorough` | requête faite avec `?thorough=1` (mode approfondi, voir `docs/REGIONS_DECODING.md`) |

Les lignes d'avant F4 ont ces colonnes vides : elles comptent dans le nombre de requêtes, pas dans les temps ni les erreurs.
Un échec d'écriture du journal ne fait **jamais** échouer la requête de l'utilisateur (erreur journalisée, requête rendue normalement).

Migration : révision `d4b7a1e90c53` (`.\upgrade_db.bat`, ou `sql/step4_usage_stats.sql` à la main ; sous Docker, `init-db` s'en charge).

## 4. Les routes (administrateur seulement)

| Route | Rôle |
|---|---|
| `GET /admin/stats/overview?days=30&token_id=` | totaux, série par jour (jours vides inclus), détail par clé (10 premières), types de fichiers, codes de réponse |
| `GET /admin/stats/recent?days=30&limit=50&token_id=` | dernières requêtes (limite de 1 à 500) |
| `GET /admin/stats/export.csv?days=30&token_id=` | journal de la période en CSV, UTF-8 avec BOM (Excel lit les accents), 100 000 lignes au plus |

`days` : 1 à 365 ; les jours sont des jours **UTC**. Sans session : 401 ; avec une session qui n'est pas celle d'un administrateur : 403.

### Calcul des percentiles (médiane, « 95 % en moins de »)

MySQL n'a pas de fonction percentile, et trier toutes les durées d'une période coûterait cher. Les durées sont donc regroupées en
**tranches de 10 ms** par un seul `GROUP BY` (`durée // 10`), puis le percentile est lu sur les effectifs cumulés. La valeur rendue est
le **centre de la tranche : juste à ±5 ms près**. Le calcul fonctionne sur toutes les bases (SQLite des tests, MySQL).

## 5. La page `/dashboard/statistics`

- **Filtres** : période (7, 30, 90 jours) et clé API (toutes, ou une).
- **Cinq chiffres clés** : requêtes (et pages), taux d'erreur (en rouge à partir de 5 %), temps moyen (et médiane), « 95 % des requêtes
  en moins de… » (avec rappel « objectif du cahier : 100 ms »), codes trouvés (et nombre de requêtes en mode approfondi).
- **Quatre graphiques** : requêtes par jour (réussies en bleu, en erreur en rouge, empilées) avec un tableau de chiffres déroulant ;
  temps moyen par jour avec la ligne pointillée du p95 ; requêtes par clé ; types de fichiers et codes de réponse.
- **Tableau** des 20 dernières requêtes (heure locale, clé, résultat en pastille verte/orange/rouge, durée, codes, pages, fichier, mode, IP).
- **Bouton « Exporter en CSV »**.

Pas de bouton « actualiser » : on recharge la page (F5) ou on change un filtre.

## 6. Choix de conception, et alternatives écartées

| Question | Choix | Écarté, et pourquoi |
|---|---|---|
| Quand écrire la ligne ? | **Une seule fois, après le traitement** | L'écrire avant (comme auparavant) puis la mettre à jour = deux écritures par requête. Contrepartie : en mode quotas « base de données », deux requêtes simultanées peuvent dépasser un peu le quota (avec Redis, le comptage est atomique : `docs/DEPLOYMENT.md`) |
| Percentiles | Histogramme de 10 ms, ±5 ms | Trier toutes les durées (lent), ou charger les durées en Python (mémoire) |
| Requêtes refusées (401, 403, 429) | **Non enregistrées** | Les enregistrer ouvrirait une table qu'un attaquant peut remplir à volonté en envoyant de mauvaises clés. Conséquence : le taux d'erreur ne compte que les requêtes acceptées |
| Graphiques | **SVG/HTML écrits pour le projet** (3 petits composants) | Chart.js : une dépendance de plus, un canevas peu adapté au rendu côté serveur déjà utilisé par l'application, et plus de personnalisation que de besoin |
| Données pour la démonstration | Commandes `seed-demo-usage` / `clear-demo-usage` | Remplir à la main (long), ou fausses données mélangées aux vraies sans marquage |

## 7. Données de démonstration : INVENTÉES

Un tableau de bord sur un journal vide ne montre rien. Deux commandes créent du trafic fictif :

```powershell
flask --app run seed-demo-usage --days 30 --per-day 300     # 3 clés "[DEMO] ..." et ≈ 7 400 lignes
flask --app run clear-demo-usage                            # tout retirer
```

Les lignes utilisent des adresses de la plage de documentation `203.0.113.0/24` ; les clés « [DEMO] » ne sont pas utilisables (leur secret
n'existe pas). Le trafic (rythme jour/nuit, week-ends calmes, 2,4 % d'erreurs, une journée trois fois plus lente) est **généré par un
programme, pas observé**. **Toute capture d'écran faite à partir de ces données doit le dire** dans sa légende.

## 8. Comment on l'a vérifié

| Vérification | Résultat |
|---|---|
| 5 tests automatiques | enregistrement du résultat de chaque requête (y compris un fichier invalide, compté) ; chiffres exacts sur un jeu de lignes connu (totaux, taux d'erreur, jours vides, par clé, types, codes de réponse, percentiles à ±5 ms, période plus longue) ; filtres et validations ; accès refusé sans session et sans droit d'administrateur ; liste et export CSV (BOM, en-têtes, nombre de lignes) ; commandes de démonstration |
| Suite complète | 44 tests passent |
| Requêtes sur un vrai MySQL | base jetable remplie avec la démonstration : 7 113 requêtes sur 30 jours, 2,4 % d'erreurs, médiane 75 ms, p95 375 ms, 30 jours rendus, filtre par clé, CSV de 1 586 lignes sur 7 jours. La base jetable a été supprimée |
| Page regardée dans un navigateur | à 1 440 px de large, sur cette base jetable : tuiles, quatre graphiques, tableau, filtres période et clé (7 jours + une clé : 482 requêtes, répartition 472 + 8 + 2 = 482) |

## 9. Ce qui a mal tourné

1. **Type du fichier** : le premier code utilisait la variable de l'extension, qui n'existe que dans une autre fonction (`NameError`, trouvé par
   les tests existants). Remplacé par la détection du contenu réel (`is_pdf`), plus fiable de toute façon.
2. **Export CSV** : le fichier est produit au fil de l'eau ; sans contexte de requête, la lecture de la base échouait
   (« Working outside of application context »). Corrigé avec `stream_with_context`.
3. **Un test** créait trois fois le même utilisateur (contrainte d'unicité) : erreur du test, pas du produit.
4. **Texte illisible dans le graphique « Requêtes par clé »** : le premier graphique en barres horizontales était un SVG dont la taille se
   réduit avec la colonne ; le texte devenait minuscule. **Seul le regard sur la page l'a révélé** (les tests passaient). Réécrit en HTML
   avec une taille de texte normale.

## 10. Limites (à dire au jury)

- **Les requêtes refusées ne sont pas enregistrées** (clé inconnue, clé désactivée ou IP refusée, quota dépassé) : pas de courbe des refus.
- **Conservation** : `flask --app run purge-usage --keep-days N` supprime les lignes plus vieilles que N jours (35 par défaut) ; pour la
  période de 90 jours, il faut `--keep-days 90` au moins.
- Le coût de l'écriture supplémentaire par requête **n'a pas été mesuré** (la ligne était déjà écrite une fois par requête ; elle l'est
  maintenant après le traitement).
- La page n'a pas été testée sur téléphone ni avec du vrai trafic ; pas de test automatique côté Angular.
- Les jours sont en UTC, les heures du tableau en heure locale du navigateur.

## 11. Le tester soi-même

1. Base à jour : `flask --app run db current` doit afficher `d4b7a1e90c53 (head)` (sinon `.\upgrade_db.bat`). Redémarrer le backend (`python run.py`).
2. Se connecter à `http://localhost:4200` (lien « Administration »), ouvrir **Statistics** dans le menu. Vide au départ : normal.
3. Créer une clé « Test statistiques » (page API Tokens, liste d'IP vide) puis envoyer des requêtes :

```powershell
1..20 | ForEach-Object { curl.exe -s -o NUL -X POST http://localhost:5000/api/v1/extract -H "X-API-Key: ecode_VOTRE_CLE" -F "file=@sample_barcodes.pdf" }
"not an image" | Set-Content bad.png
curl.exe -X POST http://localhost:5000/api/v1/extract -H "X-API-Key: ecode_VOTRE_CLE" -F "file=@bad.png"
curl.exe -X POST "http://localhost:5000/api/v1/extract?thorough=1" -H "X-API-Key: ecode_VOTRE_CLE" -F "file=@sample_barcodes.pdf"
```

4. Recharger la page (F5). Attendu : **22 requêtes**, **4,5 % d'erreur** (1 sur 22), 1 requête en mode approfondi, PDF 21 et Image 1,
   résultats `200` 21 et `400` 1, un trait rouge sur la barre du jour, la dernière requête en tête du tableau.
5. Essayer les filtres, l'export CSV (ouvrir dans Excel), les info-bulles, « Voir les chiffres par jour ».
6. Pour une page bien remplie (**données inventées**) : `flask --app run seed-demo-usage`, puis `flask --app run clear-demo-usage` après.

## 12. Captures à prévoir pour le rapport

| Capture | Légende suggérée |
|---|---|
| Page complète avec la démonstration (tuiles + graphiques) | « Tableau de bord de l'administrateur, **sur des données de démonstration inventées** » |
| Tableau des dernières requêtes avec les pastilles de résultat | idem, ou sur de vraies requêtes de test (section 11) |
| Même page avec une seule clé et 7 jours | « Filtres par clé et par période » |

## 13. Ce qu'on peut dire à la soutenance

« Le journal des requêtes enregistre le résultat de chaque appel ; trois routes d'administration le résument par des agrégats SQL, et
une page Angular l'affiche avec des graphiques que j'ai écrits sans bibliothèque. Les percentiles viennent d'un histogramme parce que
MySQL n'a pas de fonction percentile. Je ne journalise pas les requêtes refusées pour qu'un attaquant ne puisse pas remplir la
table. J'ai vérifié les requêtes sur MySQL et regardé la page dans un navigateur, ce qui a révélé un graphique illisible que les tests
n'avaient pas vu. Les chiffres de démonstration sont inventés et je le dis. »
