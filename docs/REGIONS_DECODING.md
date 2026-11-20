# Lecture par régions (F3b)

La localisation (F3a, `docs/LOCALIZER_STUDY.md`) trouve où sont les codes. F3b s'en sert pour mieux les lire : chaque région
trouvée est **découpée, redressée (quel que soit l'angle), agrandie ou réduite à environ 140 px de côté**, puis lue avec quelques
variantes de l'image (telle quelle, inversée, contraste renforcé, binarisée, débruitée). Les régions qui ressemblent à un code
mais ne sont pas lues sont **signalées** (en orange sur la page publique).

## 1. Où ça se place dans la lecture

1. **Lecture rapide** de la page entière (inchangée : c'est elle qui tient les 100 ms sur une image normale).
2. Si elle ne trouve **rien** : on localise les codes, puis on lit chaque région (`DECODE_REGIONS=first`, défaut).
3. Si rien n'est encore lu : passes de nettoyage de la page entière (inversion, contraste, rotations ±45°…), comme avant.
4. **Mode approfondi** (`DECODE_ALL_REGIONS=1`, ou `?thorough=1` pour l'API) : l'étape 2 est faite sur **toutes** les pages,
   même si la lecture rapide a déjà trouvé un code, ce qui permet de trouver **les autres codes de la page**.
   La page publique est toujours en mode approfondi ; l'API reste rapide par défaut.

Réponse JSON : `unread_regions` (API) / `unread` (page publique) = `[{page, coordinates:{x,y,w,h}, score}]`.

## 2. Protocole

Cinq stratégies comparées avec `bench/eval_decode.py`, sur les mêmes jeux que F3a : pages de documents (plusieurs codes par page)
et un code sur page blanche. Réglage (stratégie par défaut, taille de région) sur les jeux de **réglage**, puis **un seul** passage
sur les jeux **finaux** (graines différentes). Un code est lu si son contenu exact figure parmi les textes décodés de la page.
*Lecture fausse* = un texte décodé qui n'est le contenu d'aucun code de la page.

## 3. Résultats finaux (jeux jamais utilisés pour régler)

### Pages de documents (468 codes, 1 à 3 par page)

| Stratégie | Codes lus | Lectures fausses | Temps moyen | Médiane | p95 |
|---|---|---|---|---|---|
| Avant : passes de la page entière seulement | 76,7 % | 0 | 156 ms | 58 ms | 694 ms |
| **Régions d'abord, puis page entière (défaut)** | **78,6 %** | 0 | 106 ms | 60 ms | 290 ms |
| Page entière d'abord, puis régions | 79,1 % | 0 | 190 ms | 55 ms | 786 ms |
| Régions seulement | 77,6 % | 0 | 89 ms | 56 ms | 230 ms |
| **Régions sur toutes les pages (approfondi)** | **93,4 %** | 0 | 128 ms | 109 ms | 164 ms |

Lecture par type, avant → approfondi : Code 128 63,3 → 91,7 % ; DataMatrix 77,7 → 95,9 % ; EAN-13 76,4 → 85,5 % ; QR 89,7 → 100 %.
Par défaut du code : inversé 33,3 → 87,5 % ; incliné 73,6 → 94,4 % ; faible contraste 73,4 → 86,1 % ; réduit 85,2 → 95,1 % ;
flou 88,0 → 96,0 %.

### Un code sur page blanche (704 images, 22 dégradations)

| Stratégie | Codes lus | Lectures fausses | Temps moyen | Médiane | p95 |
|---|---|---|---|---|---|
| Avant | 90,8 % | 3 | 72 ms | 18 ms | 339 ms |
| **Régions d'abord (défaut)** | **91,9 %** | 3 | 47 ms | 17 ms | 201 ms |
| Approfondi | 91,9 % | 3 | 64 ms | 41 ms | 200 ms |

Le trou de l'étude F2 est comblé : **code incliné de 30° : 68,8 → 93,8 %** (Code 128 : 81,8 → 86,4 % au total).

### Ce qu'il faut en retenir

- **Le mode par défaut est meilleur et plus régulier** : un peu plus de codes lus (+1,1 à +1,9 point), moyenne plus basse et surtout
  **p95 divisé par 2,4 (694 → 290 ms) et 1,7 (339 → 201 ms)** : les images difficiles ne perdent plus de temps en passes à l'aveugle.
  La lecture rapide d'une image normale n'est pas touchée.
- **Le mode approfondi est le vrai gain sur les pages à plusieurs codes : +16,7 points (76,7 → 93,4 %)**, pour environ +50 ms de
  médiane. La lecture rapide s'arrête au premier code lu ; les régions retrouvent les autres, notamment blanc sur noir.
- Réglage et examen final concordent (documents : 74,4 → 75,5 → 92,9 % au réglage ; 76,7 → 78,6 → 93,4 % au final).

## 4. Ce qui n'a PAS marché comme annoncé

1. **Les lectures fausses ne disparaissent pas.** Sur le jeu de réglage, la stratégie par régions avait ramené 3 lectures fausses
   à 0 ; sur le jeu final : 3 et 3. Les deux lectures fausses d'EAN-13 incliné à 30° (étude F2) viennent de la **lecture rapide
   elle-même** (zxing-cpp rend un autre EAN-13 valide) ; comme elle « réussit », l'étape par régions ne s'exécute pas. Au réglage,
   les fausses lectures venaient des passes de nettoyage, que les régions remplacent. Piste (F2b) : vérifier une lecture 1D inclinée
   avec la région redressée.
2. **Les zones signalées « illisibles » sont souvent de fausses alertes.** Parmi les zones signalées (score ≥ 0,9), seulement
   **24 % (pages de documents, mode approfondi) et 18 % (un code sur page blanche)** correspondent à un vrai code non lu ; le reste
   est du texte gras ou des fragments. Le texte affiché le dit (« certaines peuvent être de fausses alertes »). Régler
   `UNREAD_MIN_SCORE` à 1,01 désactive le signalement.

## 5. Réglages

| Variable | Défaut | Effet |
|---|---|---|
| `DECODE_REGIONS` | `first` | `first` régions puis page entière ; `last` l'inverse ; `off` comme avant F3b |
| `DECODE_ALL_REGIONS` | `0` | `1` : approfondi pour toutes les requêtes (l'API peut le demander avec `?thorough=1`) |
| `UNREAD_MIN_SCORE` | `0,9` | confiance minimale pour signaler une zone non lue |

Exemple API : `POST /api/v1/extract?thorough=1` avec l'en-tête `X-API-Key`.

## 6. Limites

- Données synthétiques (voir `docs/LOCALIZER_STUDY.md` : aucune image réelle testée).
- Le mode approfondi ajoute la localisation (≈ 65 ms par page 800×1000) à chaque page : à réserver aux clients qui veulent tous les codes.
- Une région mal localisée (code coupé en morceaux, texte collé) n'est pas lue ; les codes très flous (σ ≥ 2) ou réduits à ≈ 1 px
  par module ne sont lus par aucune stratégie.
- La taille de région visée (140 px) a été comparée à 90 et 200 px sur le jeu de réglage : écarts de 0,3 point, sans importance.

## 7. Refaire l'étude

```powershell
python bench/eval_decode.py bench/documents_tuning     # réglage (stratégies côte à côte)
python bench/eval_decode.py bench/documents            # jeu final : à ne lancer qu'une fois
python bench/eval_decode.py bench/dataset
```
