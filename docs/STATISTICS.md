# Tableau de bord statistique de l'administrateur (F4)

Page **Statistics** du back office (`/dashboard/statistics`) : combien de requêtes reçoit le service web, avec quel résultat et
quelle rapidité, pour quelle clé API.

## 1. Ce qui est enregistré

Chaque requête acceptée de `POST /api/v1/extract` (fichier valide, traité ou en échec pendant le traitement) écrit **une ligne**
dans `api_usage` (une seule écriture par requête, après le traitement) :

| Colonne | Contenu |
|---|---|
| `created_at`, `ip_address` | arrivée de la requête (UTC), adresse du client (déjà présentes) |
| `status_code` | code HTTP rendu : 200, 400 (fichier invalide), 500 (erreur interne) |
| `duration_ms` | durée du traitement (extraction) |
| `codes_found`, `pages` | codes trouvés, pages analysées |
| `file_type`, `file_bytes` | `image` ou `pdf`, taille du fichier |
| `thorough` | requête faite avec `?thorough=1` (mode approfondi) |

Les lignes d'avant F4 ont ces colonnes vides (`NULL`) : elles comptent dans le nombre de requêtes mais pas dans les temps ni les
erreurs. Migration : `d4b7a1e90c53` (`.\upgrade_db.bat`, ou `sql/step4_usage_stats.sql` à la main ; sous Docker, `init-db` s'en charge).

## 2. L'API (administrateur seulement)

| Route | Rôle |
|---|---|
| `GET /admin/stats/overview?days=30&token_id=` | totaux, courbe par jour (jours vides inclus), détail par clé, types de fichiers, codes de réponse |
| `GET /admin/stats/recent?days=30&limit=50&token_id=` | dernières requêtes |
| `GET /admin/stats/export.csv?days=30&token_id=` | journal de la période en CSV (UTF-8 avec BOM : Excel lit les accents), 100 000 lignes au plus |

`days` : 1 à 365. Les jours sont des jours **UTC**.

Tout est calculé par des agrégats SQL (le coût ne dépend pas du nombre de requêtes autrement que par le parcours de l'index sur la période).
Les **percentiles** (médiane, p95) viennent d'un histogramme par tranches de 10 ms (un seul `GROUP BY`) : MySQL n'a pas de fonction
percentile et trier toutes les durées coûterait cher. La valeur rendue est le centre de la tranche : **juste à ±5 ms près**.

## 3. La page

Filtres : période (7, 30, 90 jours) et clé API. Cinq chiffres clés (requêtes, taux d'erreur, temps moyen, 95 % des requêtes en
moins de…, codes trouvés), quatre graphiques (requêtes par jour avec les erreurs en rouge, temps moyen par jour avec la ligne du
p95, requêtes par clé, types de fichiers et codes de réponse), un tableau des 20 dernières requêtes, un bouton d'export CSV.
Les graphiques sont de simples SVG/HTML écrits pour le projet (aucune bibliothèque) ; chacun a une info-bulle au survol et le
graphique principal a un tableau de chiffres déroulant.

## 4. Données de démonstration : INVENTÉES

Un tableau de bord sur un journal vide ne montre rien. Deux commandes créent du trafic fictif :

```powershell
flask --app run seed-demo-usage --days 30 --per-day 300     # 3 clés "[DEMO] ..." + ≈ 7 400 lignes
flask --app run clear-demo-usage                            # tout retirer
```

Les lignes de démonstration utilisent des adresses IP de la plage de documentation `203.0.113.0/24` ; les clés « [DEMO] » ne sont
pas utilisables (leur secret n'existe pas). **Toute capture d'écran faite à partir de ces données doit le dire** : le trafic
(rythme jour/nuit, week-ends calmes, 2,4 % d'erreurs, une journée lente) est généré par un programme, pas observé.

## 5. Vérifié, et limites

Vérifié : 5 tests automatiques (44 au total) : enregistrement du résultat de chaque requête, chiffres exacts d'un jeu de lignes connu
(totaux, taux d'erreur, jours vides, par clé, percentiles à ±5 ms), filtres, validations, accès refusé sans session et sans droit
d'administrateur, export CSV, commandes de démonstration. Les requêtes ont aussi été exécutées sur un vrai MySQL (jeu de
démonstration, base jetable) et la page a été regardée dans un navigateur (filtres période et clé, 1 440 px de large).

Limites :
- **Les requêtes refusées ne sont pas enregistrées** (clé inconnue 401, clé désactivée ou IP refusée 403, quota dépassé 429) :
  le taux d'erreur ne compte que les requêtes acceptées. Les enregistrer ouvrirait une table à remplir à volonté par un attaquant.
- **Conservation** : `flask --app run purge-usage --keep-days N` supprime les lignes plus vieilles que N jours (35 par défaut) ;
  pour une période de 90 jours à l'écran, il faut `--keep-days 90` au moins.
- Le journal est écrit après le traitement : en mode quotas « base de données » (sans Redis), des requêtes simultanées peuvent
  dépasser un peu le quota (avec Redis, le comptage est atomique, voir `docs/DEPLOYMENT.md`).
- La page n'a pas été testée sur téléphone ni avec de vraies données de production ; pas de test automatique côté Angular.
