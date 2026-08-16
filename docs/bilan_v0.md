# Bilan V0 — Pipeline CO automatique

> Consolidation des mesures au 2026-08-15. Terrain de référence : Grimbosq (forêt de feuillus,
> 6 tuiles IGN LiDAR HD, hull FFCO 324 ha). Config figée : σ=1.0, mode=ratio, p95_local,
> seuils [0.20, 0.45, 0.85], min_area 406=100/408=100/410=75 m².

---

## 1. Ce que le pipeline produit

### 1.1 Recall par classe

Deux métriques distinctes, deux questions distinctes :

| Classe ISOM | Recall détection (any-class) | Recall classe exacte |
|---|---|---|
| **406** course lente | **35%** | **28%** |
| **408** marche | **61%** | **26%** |
| **410** progression difficile | **82%** | **48%** |

**Recall détection (any-class)** : fraction de la surface FFCO couverte par *n'importe quelle*
classe pipeline. Mesure le temps gagné — chaque hectare couvert est un hectare que le cartographe
n'a pas à dessiner de zéro, quelle que soit la correction de classe à faire ensuite.

**Recall classe exacte** : fraction couverte par la *bonne* classe. Mesure la qualité sans retouche —
un polygone ici peut être importé directement sans changement de symbole.

Lecture pratique :
- 410 : 82% détectés, 48% directement utilisables.
- 408 : 61% détectés, seulement 26% avec la bonne classe (une grande partie est capturée mais en 406 ou 410).
- 406 : 35% détectés — limite physique, pas de calibration (voir §3.1).

Surface de référence (FFCO Grimbosq) : 406=86.6 ha, 408=27.1 ha, 410=19.2 ha.

### 1.2 Métriques de forme

Mesurées sur `vegetation_masked.gpkg` (post-masque) via `report_shape_metrics()` dans `src/qa.py`.

| Classe | Compacité 4πA/P² | % polygones troués | Cible FFCO 406 |
|---|---|---|---|
| **406** | 0.441 | 12.1% | 0.663 / 1.1% |
| **408** | 0.528 | 13.3% | — |
| **410** | 0.659 | 1.5% | — |

La classe 410 est essentiellement à la cible de compacité FFCO (0.659 vs 0.663).
La classe 406 est à 0.441 — un écart de 0.222 par rapport à la cible, non comblable
en aval du seuillage (voir §3.2, chantier forme).

### 1.3 Couverture globale et géométrie

Mesures TP/FP/FN sur hull FFCO (326 ha) :
- Surface FFCO : 132 ha (40% du hull)
- TP=62 ha (47%), FP=47 ha (36%), FN=70 ha (53%)
- Recall=47%, Précision=57%

La carte d'erreur à 100m montre une erreur spatialement structurée (pas aléatoire) :
44% des cellules en sous-détection (delta < −10%), 26% en sur-détection, 29% en accord.
La répartition N/S est entièrement expliquée par la distribution des classes FFCO
(r=−0.689 entre fraction 406 par cellule et delta-coverage, p < 10⁻⁵⁰).

---

## 2. Domaine de validité par classe

Le domaine n'est pas défini par terrain mais par classe. Un terrain peut être dans le domaine
pour 410 et hors domaine pour 406 — c'est le cas de Grimbosq lui-même.

### 2.1 Synthèse corpus (4 terrains)

| Terrain | 406 | 408 | 410 | Mode de défaillance |
|---|---|---|---|---|
| **Grimbosq** (feuillus, France) | hors domaine | dans le domaine | dans le domaine | HAG 406 indiscernable du blanc |
| **Airelles** (résineux/lande, France) | hors domaine | hors domaine | hors domaine | Indiscernabilité inter-classes : lande praticable ≡ sous-bois gênant en HAG[0.3:3m] |
| **Kilemaed** (Estonie, lande/forêt) | hors domaine | — | — | Désaccord sémantique : végétation basse en terrain ouvert (ISOM 403/404) ≡ sous-bois couvert |
| **Kuti** (Estonie, épicéas) | hors domaine | hors domaine | — | Signal uniforme dense (p95/p50=3.3) : p95_local compresse tout en [0.3–0.8] |

Grimbosq est le seul terrain dans le domaine. Ceci empêche de calibrer un critère de
fiabilité automatique — n=1 in-domain ne suffit pas.

### 2.2 Limite critique — classe 406 sur Grimbosq

La mesure A (séparabilité HAG dans les FN 406) est la mesure-clé :
- Distribution HAG dans les FN_406 : médiane=0.118, >0.20=10%
- Distribution HAG dans les zones FFCO-blanc (ne devrait pas être détecté) : médiane=0.118, >0.20=31%
- AUC Mann-Whitney = 0.487 → distributions indiscernables

Conclusion : le signal HAG est absent dans 90% des 406 manqués. Ce n'est pas un problème
de seuil — c'est une limite physique du LiDAR sur la végétation légère. Même sur Grimbosq,
la classe 406 est hors domaine de détection.

### 2.3 Critère p95/p50 — non opérationnel

Le rapport p95/p50 (non-zero à 2m) était candidat à un critère de fiabilité automatique :
- Grimbosq=7.6, Airelles=7.7, Kilemaed=4.8, Kuti=3.3

Il sépare correctement Kuti (signal uniforme) et Kilemaed, mais échoue sur Airelles
(7.7 ≈ Grimbosq=7.6 alors qu'Airelles est hors domaine). L'échec d'Airelles est d'une
autre nature : c'est l'indiscernabilité inter-classes, pas l'uniformité. Aucune frontière
binaire sur ce critère n'est valide.

---

## 3. Limites caractérisées

### 3.1 Détection 406 — limite physique confirmée

**Test :** `scripts/diag/confusion_interclass.py` + mesure TP/FP/FN sur hull FFCO.

Filtre de taille dans les FN_406 :
- 90% des 406 manqués sont sous T=0.20 (déficit signal réel)
- 8% filtrés par min_area (<100 px) = 4.4 ha seulement

La piste "baisser T_406" est close : AUC=0.487 → baisser le seuil crée plus de FP dans
les zones blanches qu'il ne récupère de TP dans les FN_406.

La piste "réduire min_area" est close : 4.4 ha récupérables sur 70 ha FN totaux — marginale.

### 3.2 Forme 406 — chantier clos, limite caractérisée

Neuf leviers testés sur la forme des polygones, tous insuffisants :

| Levier | Test | Résultat |
|---|---|---|
| remove_holes pré-merge | sweep seuils 0–1000 m² | Indicateur mesuré = médiane tache (invariant au remplissage de trous) — test invalide |
| remove_holes post-merge | sweep avec compacité correcte | Plateau 0.453 au-delà de 200 m² (vs cible 0.663). +7.45 ha pour +0.012 compacité |
| fermeture morphologique raster | comptage candidats | 2/496 polygones candidats — opération inactive |
| Hystérésis | — | Non implémenté |
| σ gaussien (1→3→1) | QA Grimbosq avant/après | σ=1.0 améliore le recall mais laisse compacité à 0.441 |
| grid_resolution_m (1m→2m) | QA complet | 38.1% vs 37.6% — quasi-inchangé |
| fusion_distance sweep | compacité avant/après | fd↓ → compacité 0.472→0.445 (empire) |
| chirurgie isthmes (r=1m) | %<0.3 avant/après | 33.4%→36.5% — dégradé |
| Chaikin passes (1→5) | QA forme avant/après | Chaikin×2 retenu : −2.1 pp %<0.3, +0.03 cpt_med — insuffisant |

**Réfutation structurelle :** bons et mauvais polygones 406 ont des contours identiques
(3.84 m/29.8° vs 3.76 m/31.0° de longueur/angle médian de segment). L'oscillation pixel
n'est pas la cause.

**Pattern Q1–Q4 (compacité vs HAG, r=−0.059, nul) :**
- Q1 (HAG stable bas, 0.215–0.282) : compact_med=0.646 — presque à la cible FFCO (0.663)
- Q2/Q3 (zone de transition 0.282–0.336) : compact_med=0.392–0.457 — les pires
- Q4 (HAG fort, >0.336) : compact_med=0.587

La dégradation de forme est localisée dans la bande de transition du seuillage.
Les polygones Q1 (franchement stables dans leur plage HAG) ont des contours nets.
σ et hystérésis — les deux leviers naturels contre le bruit de seuillage — ont déjà été réfutés.

**Conclusion :** Le pipeline seuille un champ continu → les frontières suivent des isolignes.
Le cartographe délimite des zones de praticabilité homogène → frontières franches.
Aucune opération postérieure au seuillage ne transforme une isoligne en contour cartographique.
La seule piste restante est la segmentation (hors scope V0).

### 3.3 Seuils inter-classes T_408/T_410 — réfuté

**Test :** `scripts/diag/confusion_interclass.py` (matrice pixel) + `scripts/diag/sweep_t410_joint.py`.

Direction des erreurs (matrice de confusion pixel) :
- Frontière 406/408 : **bidirectionnelle** (8.3 ha FFCO 408 → pipe 406, 6.8 ha FFCO 406 → pipe 408). Problème de séparabilité HAG entre 406 et 408 — pas solvable par seuil.
- Frontière 408/410 : légèrement systématique (5.2 ha FFCO 410 sous-classés en 408 vs 3.7 ha en sens inverse).

Sweep joint pondéré par surface FFCO réelle (408=27.1 ha, 410=19.2 ha) :
- À T_410=0.60 (proposé initialement) : r408 baisse 24.9%→11.4% (−13.5 pp, −3.66 ha), r410 monte 54.7%→71.6% (+16.9 pp, +3.25 ha) → **bilan −0.43 ha**
- T optimal (max ha total correct) : T_410=0.81, gain = +0.02 ha (bruit)
- Plateau ha (within 0.1 ha du max) : T_410 ∈ [0.71, 0.92] — le réglage actuel 0.85 est déjà dans ce plateau

Déplacer T_410 transfère des ha entre classes sans en créer. Le levier n'existe pas.

### 3.4 Normalisation — réfutée

**Test :** `fixed_percentile=31.018` (valeur p95_local sur Kuti) testé sur Kuti.

Résultat : QA inchangé. La normalisation p95_local est équivalente à la normalisation globale
sur un terrain à dynamique compressée — c'est la dynamique elle-même qui est le problème, pas la normalisation.

### 3.5 Masque canopée — réfuté

**Test :** `scripts/diag_canopy_separability.py` — histogrammes count_high par zone FFCO.

Résultats Airelles :
- Zones open_terrain médiane count_high=0.441, zones veg_406=0.438 — identiques
- Ratio r2 = count_high/(count_high+density_hag) : 0.926 vs 0.933 — idem
- Contexte spatial 50m : 0.502 vs 0.521 — aucune séparation

Masque réfuté sur signal local ET spatial. La signature canopée est identique entre les
zones praticables (lande) et les zones gênantes (sous-bois) sur terrain de lande.

---

## 4. Inventaire des réfutations

| # | Levier | Test | Résultat |
|---|---|---|---|
| 1 | T_406 seuil de détection | AUC Mann-Whitney FN_406 vs blanc | AUC=0.487 — distributions indiscernables |
| 2 | min_area (filtre taille) | Comptage FN_406 filtrés | 4.4 ha sur 70 ha FN — marginale |
| 3 | σ gaussien (3m) | QA Grimbosq σ=3 vs σ=1 | σ=1 retenu pour recall, compacité reste à 0.441 |
| 4 | grid_resolution_m=2m | QA complet 1m vs 2m | 38.1% vs 37.6% — quasi-inchangé |
| 5 | Normalisation fixed vs p95_local | fixed_percentile=31.018 sur Kuti | QA inchangé — dynamique compressée est le problème |
| 6 | Masque canopée (count_high) | Séparabilité count_high par zone FFCO | Médiane identique open_terrain vs veg_406 sur Airelles |
| 7 | remove_holes (amont) | Sweep seuils — mauvaise métrique | Médiane tache invariante au remplissage de trous |
| 8 | remove_holes (aval) | Sweep compacité corrigée | Plateau 0.453 au-delà de 200 m² (cible 0.663) |
| 9 | Chirurgie isthmes | %<0.3 avant/après | 33.4→36.5% — dégradé |
| 10 | T_408/T_410 inter-classes | Sweep joint pondéré ha | Plateau ha [0.71, 0.92], T actuel 0.85 déjà optimal |
| 11 | Intensité LiDAR HAG[0.3:3m] | AUC Mann-Whitney FN_406 vs blanc | AUC inversé=0.6362 (signal réel mais incohérent physiquement) — gradient FN_406<det_406<blanc inverse la prédiction ; biais d'échantillonnage (peu de retours → moyenne sur retours sol, pas végétation) ; piste close V0 |

---

## 5. Erreurs de méthode

Quatre erreurs commises en cours de développement, documentées pour ne pas les reproduire.

### 5.1 Le ×7 fantôme (mauvais dénominateur)

Les premières mesures de couverture exprimaient `cov%` sur le hull total (326 ha) alors que
la surface FFCO dans ce hull est 132 ha (40%). Un `cov%=5%` mesuré sur le hull correspond
à 12.5% de couverture FFCO réelle. Ce facteur ×7 (hull/FFCO) a produit des chiffres corrects
en apparence mais non comparables à la référence terrain.

**Correction appliquée :** toutes les mesures de recall se font sur les polygones FFCO
directement (intersection pipeline × FFCO), pas sur le hull.

### 5.2 La tautologie cov%=100

En début de projet, un `cov%` de 100% sur le hull propre du pipeline était présenté comme
un résultat. C'est une tautologie : le pipeline couvre toujours 100% de sa propre emprise.
La mesure significative est la couverture FFCO (intersection avec la vérité terrain).

### 5.3 La référence 370 non-reconstructible

Le premier snapshot de référence Grimbosq incluait 370 polygones en classe 410.
Le `density_hag_classified.tif` correspondant a été écrasé par les tests sur H2 et 2m.
La référence 406/408/370 est irreconstruible — le pipeline avec les mêmes paramètres
produit maintenant 465 polygones en 410 (résolution identique, mais un bug dans
l'encodage raster a été corrigé entretemps).

**Conséquence :** la série temporelle avant/après cette date n'est pas directement comparable.
Le snapshot post-correction (942/611/465, 2026-08-13) est la seule référence fiable.

### 5.4 Recalls non pondérés par surface

Comparer des gains de recall en % entre deux classes de surfaces FFCO différentes sans
pondérer est trompeur. Exemple concret (sweep T_410) :
- +16.9 pp sur 410 (19.2 ha FFCO) = +3.25 ha
- −13.5 pp sur 408 (27.1 ha FFCO) = −3.66 ha
- **Bilan net : −0.41 ha**

Vu en % non pondérés : +3.4 pp net (apparemment positif).
Vu en ha pondérés : −0.41 ha (réfutation).

Le rapport de surfaces 408/410 = 1.42 : 1 pp sur 408 vaut 1.42× plus qu'1 pp sur 410.
Toute comparaison de recalls entre classes doit inclure `total_correct_ha = Σ(recall_i × ha_i)`.

---

## 6. Ce qui reste ouvert

### Question cartographe

La seule inconnue non levable par mesure interne : le pipeline est-il suffisamment utile
pour un cartographe qui connaît ces limites ?

Formulation concrète : *Voici ce que l'outil capture — 35%/61%/82% en détection, 28%/26%/48%
en classe exacte, formes correctes en Q1/Q4 (polygones à signal stable). Est-ce que ça fait
gagner du temps, même avec correction manuelle ?*

### Second terrain dans le domaine

Avec un seul terrain dans le domaine (Grimbosq), il est impossible de distinguer si le pipeline
fonctionne sur une *classe* de terrains ou uniquement sur Grimbosq. Les trois modes de
défaillance documentés (indiscernabilité inter-classes / désaccord sémantique / signal uniforme)
sont distincts — un critère de fiabilité automatique a peu de chances de les capter tous.

Candidats prioritaires : forêt de feuillus tempérée, LiDAR HD compatible (>10 pts/m²),
FFCO disponible. Terrain français IGN HD préféré (densité compatible sans adaptation).

### Piste intensité de retour — CLOSE (V0)

Test effectué (`scripts/diag/intensity_406.py`, voir `docs/test_intensite.md`).

AUC FN_406 vs blanc = 0.3638 (inversé : 0.6362) — signal réel, mais gradient observé
(FN_406=506 < det_406=602 < blanc=640) physiquement incohérent : les zones avec le moins
de végétation (FN_406) sont les plus sombres, alors que la physique prédit l'inverse.

Diagnostic : biais d'échantillonnage. Les FN_406 ont peu de retours dans HAG[0.3:3m]
par définition (c'est ce qui explique qu'HAG les rate). La moyenne d'intensité porte
alors sur des retours de nature différente — sol, litter — non représentatifs de
la végétation. L'intensité ne mesure pas la même chose dans les zones denses et dans les zones FN.

Piste close V0 — le signal reflète le biais de sélection, pas la végétation.
