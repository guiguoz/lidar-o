# Plan v5 — végétation Ovector, après session 2026-08-04

> Remplace le plan v1–v4 (`PLAN_vegetation_406.md`), dont les Étapes B/C/D reposaient sur une
> hypothèse métrique désormais éliminée. Ce document repart des résultats mesurés, pas des
> hypothèses initiales.
>
> **Ce que je ne sais pas** (à compléter par l'auteur avant exécution) : temps disponible par
> session, livrables attendus et pour quand, terrains accessibles au-delà de Grimbosq/Airelles,
> suite éventuelle de l'échange avec Terje Wiig Mathisen. Les priorités ci-dessous sont classées
> par rapport information/effort, sans contrainte de calendrier.

---

## Acquis — ne pas rouvrir sans raison mesurée

**σ = 1.0 (était 3.0).** Cause racine du blob 406 : un gaussien σ=3 m sur grille 1 m comblait les
creux entre patches voisins et fabriquait une vallée de densité continue dans le raster, *avant*
toute généralisation vectorielle. Effet mesuré sur Grimbosq : concentration du plus gros polygone
51,3 % → 7,2 % du 406 (cible FFCO 5,4 %), couverture 24,4 % → 16,6 % (cible 15,0 %).
Validé sur Airelles (structure archipel, max%406 = 3,4 %). Tags `v1_vegetation_baseline` /
`v2_vegetation_sigma1`.

**Domaine de validité mesuré.** Grimbosq (feuillus) : Δcov +1,6 %, Δmax +1,8 % — résidu dans le
bruit cartographique. Airelles (lande d'altitude à airelles + résineux épars) : ×4,8 vs cible 406
seul (×2,6 vs 406+407) — hors portée, cause démontrée ci-dessous.

**Trois hypothèses réfutées par la mesure**, avec les tests qui les ont tuées :
- *Fusion trop agressive* → run de contrôle `fusion_distance[406]=0` : blob de 75 ha toujours
  présent avant toute fusion.
- *Branches basses de résineux (halos sous canopée)* → intersection spatiale du 406 pipeline avec
  la légende FFCO : 53,7 % du surplus tombe en **terrain découvert**, pas sous couvert.
- *Masque de canopée* → séparabilité `count_high/total` : Airelles open_terrain 0,441 vs veg_406
  0,438 ; Grimbosq médiane qui *monte* à l'érosion (biais de bord réfuté) ; contexte spatial
  50–100 m sans séparation. Réfutée localement et régionalement.

**Cause racine du résidu Airelles.** ISOM code la **praticabilité du sol**, pas la structure
verticale. Une lande d'airelles (30–60 cm, praticable → 403/404 jaune) et un sous-bois ralentissant
(→ 406 vert) ont des profils HAG[0,3:3 m] identiques : `density_hag` médiane 4 dans les deux, ratio
0,02 dans les deux, et le pipeline classe même *plus* de pixels en 406 sur terrain découvert
(34,7 %) que sur du 406 réel (30,4 %). L'information est absente du signal de hauteur — ce n'est
pas un problème de seuil, de lissage ni de métrique dérivée.

**Corollaire : l'Étape B (NRD) est sans objet sur Airelles.** Le NRD travaille sur la même bande ;
là où `density_hag` ne discrimine pas, il ne discriminera pas non plus. Elle garde un objet
possible sur Grimbosq uniquement (résidu +1,8 pt), avec une priorité faible — voir §4.

---

## H3 — Intensité de retour (priorité 1)

**Pourquoi.** Seule piste identifiée qui apporte une *dimension physique nouvelle* sans nouvelle
acquisition : le champ `Intensity` est déjà dans les COPC en cache. La physique plaide pour une
séparation — feuilles coriaces et cireuses des airelles (Vaccinium) vs frondes de fougère ou
ronces, réflectance proche infrarouge différente.

**Précaution méthodologique, à intégrer dès la première passe.** L'intensité brute n'est pas
comparable d'une ligne de vol à l'autre : elle dépend de la portée, de l'angle d'incidence et du
gain capteur. D2 a mesuré ~149 retours/m² sur Grimbosq, cohérent avec ~5 lignes de vol en
recouvrement — donc une même surface est vue sous des angles très différents. **Sans ce contrôle,
la piste risque d'être enterrée pour un artefact plutôt que pour un vrai résultat.**

1. Passe PDAL sur la bande végétation, en conservant `Intensity`, `ScanAngleRank` et
   `PointSourceId` (ligne de vol) — même structure que `run_count_high.py`.
2. **Test préalable obligatoire** : la variance d'intensité *entre lignes de vol sur une même
   zone* est-elle plus grande que celle *entre classes FFCO* ? Si oui → normaliser (par angle,
   par ligne de vol) avant toute conclusion. Si non → passer directement au test de séparabilité.
3. Séparabilité par zone FFCO avec `diag_canopy_separability.py` inchangé (open_terrain /
   scattered_trees / veg_406), sur Airelles **et** Grimbosq.
4. Critère de décision : recouvrement des distributions. Une séparation même partielle
   (médianes distinctes, IQR qui se chevauchent partiellement) est exploitable en pondération ;
   des distributions superposées comme pour H2 closent la piste.

**Issue si H3 échoue.** Ce serait la quatrième réfutation, et elle porterait la conclusion à :
*le LiDAR HD seul, dans ses dimensions accessibles, ne distingue pas praticabilité de gêne en
lande basse*. C'est un résultat publiable et utile — il borne ce que tout outil de ce type peut
faire, pas seulement Ovector. À écrire comme tel, pas comme un échec.

### Résultats H3 (2026-08-04)

**Méthode : test de dépendance angulaire préalable (à conserver comme protocole)**

Avant tout test de séparabilité, la variance d'intensité entre tranches d'angle de 5° a été
comparée à la variance globale (`std_between_angles / std_global`). Ce ratio doit être < 0,3
pour que le test de classe soit interprétable sans normalisation préalable.

- Airelles : r = −0,001, ratio = 0,05 → **pas de dépendance angulaire**
- Grimbosq : r = 0,034, ratio = 0,09 → **pas de dépendance angulaire**

Le test est propre sur les deux terrains. Il resservira pour toute future piste basée sur un
attribut de retour individuel (intensité, forme d'impulsion, etc.).

**Airelles — séparabilité : réfutée**

| Zone | n | médiane | IQR |
|------|---|---------|-----|
| Terrain découvert (403/404) | 758 707 | 30,7 | [18,0–53,5] |
| Végétation 406 | 135 444 | 29,0 | [17,5–50,3] |

Écart de 1,7 unités sur un IQR de ~35. Distributions superposées. **H3 réfuté sur Airelles.**
C'est la quatrième réfutation.

**Grimbosq — signal de réflectance confirmé, non généralisable**

Test en deux étapes pour discriminer atténuation par canopée et réflectance.

*Étape 1 — test 406 / 408 / 410 sous couvert :*

| Zone | n | médiane | IQR |
|------|---|---------|-----|
| Végétation 406 (course lente) | 657 744 | 520 | [416–739] |
| Végétation 408 (marche) | 262 755 | 651 | [473–927] |
| Terrain découvert (403/404) | 57 356 | 752 | [466–1149] |
| Végétation 410 (lutte) | 234 005 | 803 | [588–1092] |

Ordre non monotone : 406 < 408 < découvert < 410. L'atténuation prédisait le gradient
inverse (plus de couvert → moins d'intensité). Réfutée.

*Étape 2 — test contrôlé par count_high (couvert équivalent) :*

| count_high bin | open (médiane) | 406 (médiane) | delta |
|---|---|---|---|
| [0, 2) | 1132 | 792 | −340 |
| [2, 50) | ~635–715 | ~468–516 | ~−165 à −200 |
| [50, 300) | 736 | 536 | −200 |

**Le delta persiste à tous les niveaux de couvert**, y compris à [0,2) où il n'y a quasiment
pas de canopée. C'est la signature de la réflectance : la végétation au sol en zone 406
(probablement fougères, *Pteridium aquilinum*) réfléchit systématiquement moins en NIR que
le terrain découvert comparable, indépendamment du couvert aérien.

**Conclusion Grimbosq : signal de réflectance confirmé, exploitabilité à déterminer.**
Signal stable (delta ~−165 à −200 sur les bins peuplés), mécanisme identifié : réflectance
différentielle de la végétation basse, pas atténuation. L'espèce responsable n'est pas établie
par la mesure — hypothèse de travail : fougères, ronces, régénération ou lierre, selon la zone.

Delta ~200 sur IQR ~300–700 : signal utilisable en **pondération** (variable auxiliaire qui
déplace la probabilité de classe), pas en seuil dur. Le test décisif d'exploitabilité : est-ce
que l'intensité améliore la classification 406 sur Grimbosq quand on l'ajoute à `density_hag` ?
Mesurable directement avec les métriques en place.

Le signal est **absent sur Airelles** — cohérent avec la cause racine : en lande, *Vaccinium*
est présent des deux côtés de la frontière cartographique (praticable et gênant), donc aucune
réflectance ne peut les séparer. En forêt, les végétations au sol diffèrent réellement d'une
classe à l'autre. L'intensité discrimine des espèces, pas des niveaux de gêne.
Le signal existe sur Grimbosq, il n'est pas généralisable.

**Conclusion H3**

Quatre dérivés testés sur Airelles ne séparent pas praticable (403/404) de gênant (406)
en lande basse :

1. Densité HAG[0,3:3 m] (`density_hag`) — médiane 4 vs 4
2. Ratio canopée local (`count_high / total`) — 0,441 vs 0,438
3. Contexte spatial 50–100 m (blur de `count_high`) — 0,502 vs 0,521
4. Intensité moyenne HAG[0,3:3 m] — 30,7 vs 29,0

**Périmètre.** Ces quatre dérivés ne couvrent pas l'espace complet des attributs LiDAR.
Non testés : variance de hauteur dans la bande HAG, nombre de retours par impulsion
(full-waveform), données multi-temporelles (feuilles on/off), classification ASPRS native IGN
(sans recalcul HAG). Un résultat négatif sur ces quatre dérivés ne borne pas l'ensemble du
signal LiDAR — il borne ce qui a été mesuré.

**Formulation défendable du résultat.** Les quatre dérivés testés (densité en bande basse,
ratio de canopée local, contexte spatial 50–100 m, intensité moyenne) ne séparent pas
praticabilité de gêne en lande basse sur Airelles. C'est un résultat publiable qui borne ce
qu'un algorithme de ce type peut faire sur ce type de terrain, pas seulement Ovector.

---

## Critère de fiabilité automatique (priorité 2)

**Objectif.** Que le pipeline signale lui-même les terrains hors domaine, au lieu de produire
silencieusement du 406 faux. C'est la formalisation de l'« option 2 » retenue en session.

**Contrainte de conception : pas de circularité.** Le critère doit se calculer **sans FFCO**,
sinon il ne sert à rien en production (le FFCO est justement ce qu'on cherche à produire).

**Piste proposée en session** : variance spatiale de `count_high` sur l'emprise — forêt =
hétérogène (clairières + couvert), lande à résineux épars = uniforme. **À valider avant de
formaliser** : on ne dispose que de deux points (Grimbosq fiable, Airelles non), ce qui ne permet
pas de calibrer un seuil. Deux terrains ne définissent pas une frontière.

Étapes :
1. Calculer la variance de `count_high` (et de `density_hag/total`) sur Grimbosq et Airelles —
   vérifier d'abord que les deux terrains se séparent réellement sur cet indicateur.
2. Ne fixer aucun seuil avant d'avoir un troisième terrain (§3).
3. Sortie visée : un champ dans `run_metadata.json` (`domain_confidence: high|low|unknown`) et un
   avertissement explicite en fin de `run_terrain.py`, dans le même esprit que les garde-fous
   mtime et nodata déjà en place.

---

## Troisième terrain (priorité 2, bloquant pour §2)

**Pourquoi c'est devenu structurel.** Le corpus n=2 a suffi tant qu'il s'agissait de valider une
correction (σ=1.0, testée sur deux structures forestières opposées — c'était le bon usage). Il ne
suffit plus dès qu'il s'agit de **calibrer un critère de frontière** entre domaines valide et
invalide : deux points ne définissent pas un seuil. C'est la limite signalée dès l'autocritique
du plan v1, et elle est maintenant bloquante, pas théorique.

**Profil recherché**, par ordre d'utilité :
1. **Un terrain intermédiaire** (forêt claire, pinède, taillis) — c'est là que le critère de
   fiabilité doit trancher, et on n'a aujourd'hui que deux cas extrêmes.
2. Un second terrain feuillu, pour vérifier que le succès sur Grimbosq n'est pas propre à Grimbosq.
3. Idéalement, une carte FFCO récente (< 3 ans d'écart avec l'acquisition LiDAR) — l'écart
   temporel est un plafond structurel sur l'IoU en végétation basse.

**Prérequis techniques déjà réglés** (rien à réinventer) : garde-fou de fraîcheur mtime, garde-fou
nodata, `run_metadata.json` avec `tiles_count`/`tile_ids`, clip sur emprise FFCO avec dénominateur
commun, séparation 406/407 dans `load_ffco()`.

### Kilemäed (Estonie) — diagnostic HAG faisabilité (2026-08-05)

Profil OOM : 169×406 + 42×403 + 70×404 + 35×408, terrain intermédiaire, 5,5 km². Carte en
convention ISOM anglaise (pas de surrogates, mapping `isom_en.yaml` disponible).

Données Maa-amet, tuile 482412, scan standard 2021 (`482412_2021_tava.laz`, 45 MB).  
LiDAR Maa-amet : format LAZ 1.4, classification ASPRS, `readers.las` (pas COPC).

**Résultats `diag_hag_feasibility.py` sur la tuile centrale (1 km²) :**

| Indicateur | Valeur | Verdict |
|---|---|---|
| Densité totale | 3,77 pts/m² | — (mieux que les 2,1 pts/m² redoutés) |
| Densité sol | 1,69 pts/m², espacement ~0,8 m | OK |
| Relief sol | range=11,6 m, std=1,10 m | Modéré (collines confirmées) |
| CV pair/impair k=8 | std=4,9 cm, p95=9,9 cm, >30cm=0,1 % | OK |
| CV pair/impair k=1 | std=6,6 cm, p95=13 cm, >30cm=0,4 % | OK (borne haute réaliste) |
| Flip zone ratio | 3,87 ([0,30:0,50m] / [0,50:0,70m]) | ATTENTION (>2) |
| Contamination flip/veg | 10,2 % de HAG[0,30:3m] | Point de vigilance |

**Lecture de l'étape 3.** La précision DEM est réelle (pas d'auto-inclusion : split pair/impair
évite toute circularité). L'écart k=8 vs k=1 (+35 % seulement) confirme que le 4,9 cm n'est pas
un artefact de lissage IDW. Mais le test est « facile » par construction : 1,69 pt sol/m² laisse
chaque point test à ~0,8 m de son voisin entraînement — l'interpolation est quasi-triviale.
La borne réaliste de l'erreur DEM est ~6,6 cm (k=1), non 4,9 cm.

**Lecture de l'étape 4.** Le ratio 3,87 (ATTENTION) masque la valeur absolue : 0,29 % du total des
retours dans [0,30:0,50m]. Le chiffre pertinent est le ratio rapporté à la bande végétation :
**10,2 %** de HAG[0,30:3m] provient du flip zone. Ce bruit touche précisément la végétation la
plus basse — la bande qui distingue lande praticable de sous-bois. Il affectera surtout les
`rough open land` (403/404), à ne pas confondre avec un vrai signal de sur-détection lors de
l'analyse Kilemäed.

**Verdict : Kilemäed est viable.** Le verrou technique (densité suffisante pour hag_nn à 0,30 m)
est levé. Adaptations à prévoir : `readers.las`, résolution 1 m directement utilisable,
`hag_count=8` inchangé. Point de vigilance : contamination flip zone 10 % sur les zones ouvertes.

### Kilemäed — pipeline complet + intersection FFCO (2026-08-05)

**Généralisation (min_h=0,30 m, σ=1,0, résolution 1 m) :**

| Classe | Polygones | Surface | Médiane |
|---|---|---|---|
| 406 | 1 411 | 533,7 ha | 241 m² |
| 408 | 4 001 | 231,4 ha | 136 m² |
| 410 | 3 669 | 112,2 ha | 66 m² |

**Intersection FFCO/ISOM (mapping `isom_en.yaml`, corrigé) :**

FFCO couvre 5,48 km² sur 16 km² LiDAR total. 429 polygones (169×veg_406, 87×scattered, 85×skip
dont 79×marais, 45×open_terrain, 35×veg_408, 4×forest).

Pour la classe 406 (533,7 ha) :
- Hors emprise FFCO : **75,6 %** — dont 65,5 % hors limite géographique carte, 3 % blanc implicite
  dans bbox, reste sur skip (marais)
- Classifié dans FFCO : **32,73 ha** (6,1 %)

| Groupe | Surface | % total | % dans FFCO |
|---|---|---|---|
| veg_406 (correct) | 12,67 ha | 2,4 % | **38,7 %** |
| scattered_trees | 10,75 ha | 2,0 % | 32,9 % |
| open_terrain | 7,54 ha | 1,4 % | 23,0 % |
| veg_408 | 1,72 ha | 0,3 % | 5,3 % |
| forest | 0,05 ha | 0,0 % | 0,1 % |

**Fraction ouverte (open + scattered) dans FFCO : 55,9 %** — vs 90,5 % Airelles.

**Prédiction CONFIRMÉE, mais pas écrasante.** Le 406 pipeline est majoritairement en veg_406
correct (38,7 %) contre 9,5 % sur Airelles. Surplus en terrain ouvert 55,9 % (< 90,5 % Airelles,
mais > seuil de réfutation 40 %). La confirmation est réelle ; la variante h50 dira si une partie
est du bruit de bande.

**Troisième mode de sur-détection identifié (à tracer, non effacé par skip).** ~19 % du 406
classifié dans la FFCO tombe sur des marais (79 polygones Indistinct/Marsh passés en skip). La
végétation humide de rive — hélophytes, joncs, roseaux — génère des retours HAG[0,3–3 m] identiques
au sous-bois, mais ISOM la code en bleu (308–312). C'est un mode distinct de sur-détection :
ni « ouvert vs couvert » ni débordement 405, mais confusion végétation humide / végétation gênante.
Piste de masque : couche hydrographie BD TOPO (France) ou équivalent Maa-amet (Estonie) ; le masque
routes/haies du plan v4 est extensible aux zones humides sur les trois terrains.

**Limite structurelle.** La FFCO estonienne n'a que 4 polygones Forest — le comportement sous
couvert dense (18,6 % sur Airelles) reste non répliqué. Grimbosq demeure le seul terrain de forêt
fermée. Trois terrains mais un seul avec canopée dense : insuffisant pour calibrer le critère de
fiabilité du plan v5.

**Variante h50 (min_h=0,50 m) — résultat.** La fraction ouverte ne bouge quasiment pas :
55,9 % → 55,2 % (−0,7 pp) alors que la surface totale 406 chute de 14,2 %. Aucune baisse
différentielle : le bruit flip-zone n'explique pas les 55,9 %. La végétation en terrain ouvert
s'étend bien au-delà de 0,50 m (landes, fougères, arbustes). Le surplus est du vrai signal,
pas un artefact de seuil. La confirmation de la prédiction est donc robuste à cette variante.

---

## Étape B — NRD (priorité 3, portée réduite)

Ne concerne plus que le résidu Grimbosq (+1,8 pt de concentration, +1,6 pt de couverture).
Protocole factoriel B0–B3 du plan v4 toujours valide *pour ce terrain seul* : δ₁ et δ_R sur
IoU_406 à résolution fixée, B0/B2 déjà disponibles depuis l'Étape A.

**Réserve honnête** : l'Étape A a montré que la résolution ne déplace pas la structure du 406
(surface stable à 0,5 % près, IoU inter-résolutions 0,776 entre 1 m et 4 m), et que 34–43 % des
cellules restent sous `n_min=8` même à 4 m. Le NRD y aurait donc peu de matière. Le gain attendu
est faible et le résidu visé est possiblement sous le bruit de la référence FFCO. **À ne lancer
que si H3 et §2 sont clos** — ou à abandonner explicitement si l'effort est mieux placé ailleurs.

Question ouverte associée, jamais testée : `median_size: 9` et `majority_radius: 3` font une
partie du même travail de comblement que σ. Le vrai correctif est peut-être « moins de lissage »
en général, pas « σ=1 » en particulier. Un run avec `median_size` réduit coûte peu.

---

## Ce qui n'a pas bougé et reste vrai

- **Cadrage sémantique** : le LiDAR mesure la matière végétale, le cartographe symbolise la gêne à
  la course. La session l'a converti d'intuition en mesure — c'est exactement ce que dit le
  résultat Airelles. Il existe un plafond d'IoU indépendant de la qualité de l'algorithme.
- **Discipline expérimentale** : une variable par run, contrôle systématique (le run `fd=0` a
  sauvé la session), comparaison avant/après sur les deux terrains, réfutations documentées.
- **Pistes du plan v4 non traitées, toujours ouvertes** : saisonnalité des blocs LiDAR HD
  (feuilles-on/off en feuillus), classification ASPRS native IGN comme second regard décorrélé,
  masque routes/haies BD TOPO, heuristiques de recouvrement dur.
- **Dette connue** : `min_area_m2` / `remove_isolated` n'ont jamais été retestés depuis que le
  diagnostic a changé (T10 les avait réglés en croyant traiter des « petites taches diffuses »,
  alors que le problème était l'agglomération). Le rapport 3875 polygones pipeline / 420 FFCO sur
  Airelles n'a toujours pas été regardé à l'échelle d'impression dans OOM.

---

## Ordre suggéré

1. **H3 intensité** — test de dépendance aux lignes de vol, puis séparabilité. Le plus fort
   rapport information/effort, et il décide de la suite du projet sur les landes.
2. **Variance de `count_high` sur les deux terrains** — vérification préalable, quelques minutes,
   dit si le critère de fiabilité a une chance.
3. **Troisième terrain** — débloque la calibration du critère et teste la généralité de σ=1.0.
4. **Inspection OOM** du GeoPackage Airelles à l'échelle d'impression — dette de la session
   précédente, dit si l'archipel est lisible ou confetti.
5. Étape B / `median_size`, seulement si 1–4 sont clos.
