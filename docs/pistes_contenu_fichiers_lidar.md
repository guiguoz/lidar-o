# Pistes — le contenu des fichiers LiDAR HD (au-delà du XYZ)

> Question posée (2026-10-08) : « autres pistes d'amélioration en lien avec le contenu des
> fichiers lidar ? »
>
> Un fichier LiDAR HD n'est pas qu'un nuage de points : il porte une **classification** en
> 11 catégories, des **attributs par point** (intensité, retours, angle de scan, ligne de
> vol, drapeaux), des **métadonnées d'acquisition** (date, mission, procédé de
> classification) et il appartient à une **famille de produits** (MNT, MNS, MNH). Ce document
> inventorie ce que le dépôt en exploite aujourd'hui — peu de chose — et les pistes qui en
> découlent, classées par coût.
>
> Statuts : ÉTABLI (mesuré dans le dépôt), SOURCE (doc externe vérifiée), INTERPRÉTÉ,
> NON TESTÉ.

---

## 0. Réponse courte

Sept pistes, dont quatre à moins d'une heure :

| # | Piste | Contenu mobilisé | Ce que ça changerait concrètement | Coût |
|---|---|---|---|---|
| 1 | **Audit du contenu réel des dalles** (schéma + histogramme des classes + dimensions extra) | tout le fichier | conditionne les pistes 2–7 : on ne sait pas aujourd'hui ce que nos dalles contiennent exactement | 15 min |
| 2 | **Filtrer les points virtuels (66) et artefacts (65)** | Classification | retire des retours fictifs (surfaces d'eau interpolées, sous-ponts) du raster végétation | 1 h |
| 3 | **Ratio construit sur les classes IGN 3/4/5** au lieu de notre bande HAG | Classification | stratifie la végétation aux seuils IGN (0–50 / 50–150 / >150 cm) ; si comparable, `hag_nn` disparaît (une étape en moins) | 2 h, 0 PDAL |
| 4 | **MNT/MNH IGN en validation externe de notre HAG** | produits dérivés | valide (ou invalide) la base sur laquelle reposent toutes nos mesures ; option `hag_dem` = `hag_nn` en moins | ½ j |
| 5 | **Date et procédé de classification par dalle** | métadonnées | documente le domaine de validité ; teste si l'échec feuillus/Airelles est saisonnier (feuilles tombées) | 30 min |
| 6 | **Fraction de pénétration (impulsions ≠ retours)** | ReturnNumber / GPS time | métrique de canopée indépendante, standard en foresterie ; soutient la Phase B2 | ½–1 j |
| 7 | **Hygiène multi-dalles** (doublons de bord, lecture COPC par emprise) | COPC / coordonnées | garantit des comptages non gonflés aux bords ; accélère les essais | 1 h + ½ j |

**Rien de tout cela ne remplace l'ordre déjà acté** (audit de l'ini KP → banc vertical →
ordre V5/V6 → overlap → Phase A → B2 → C) ; les pistes 1, 2, 3, 5 s'y insèrent à coût quasi
nul (voir §4).

---

## 1. Ce que contient un fichier — et ce que le dépôt en utilise

### 1.1 La classification (11 catégories)

**SOURCE** (IGN, documentation produit et data.gouv.fr) : le nuage classé comporte
8 classes ASPRS + 3 classes personnalisées :

| Code | Classe | Utilisée par le dépôt ? |
|---|---|---|
| 1 | non classé (éléments de sursol non identifiés) | non — **incluse** dans `total_count` et dans le HAG |
| 2 | sol | oui — `filters.hag_nn` s'appuie dessus (ÉTABLI, doc PDAL) ; densité sol mesurée par `diag_hag_feasibility.py` |
| 3 | végétation basse (0–50 cm) | **non** |
| 4 | végétation moyenne (50 cm–1,50 m) | **non** |
| 5 | végétation haute (> 1,50 m) | **non** (le masque canopée équivalent a été réfuté, bilan levier 6) |
| 6 | bâtiment | non (BD TOPO utilisée à la place) |
| 9 | eau | non (BD TOPO) |
| 17 | tablier de pont | non |
| 64 | sursol pérenne | non — contenu à inspecter (murets ? pylônes ?) |
| 65 | artefacts | non — **incluse** dans `total_count` et dans le HAG |
| 66 | points virtuels | non — **incluse** dans `total_count` et dans le HAG |
| 67 | bâti divers / bâtiments incertains | non |

> Note de nomenclature : selon les millésimes et les procédés de classification, la liste
> varie légèrement (le produit 2025 ajoute `DTM_MAKER`/`DSM_MAKER` ; certaines campagnes
> partenaires documentent 12 à 15 classes, avec bruit bas/haut, pylône…). La liste
> **autoritative est l'histogramme de nos dalles** — c'est la piste n°1.

**ÉTABLI (lecture du code)** : les pipelines lisent **tous** les points et ne filtrent
aucune classe. `hag_nn` utilise la classe 2 comme sol (SOURCE, doc PDAL), mais tout point
non-sol reçoit un HAG — y compris les points virtuels et les artefacts. Leur poids réel
dans nos rasters est **NON TESTÉ**.

### 1.2 Les attributs par point

| Attribut | Utilisé par le dépôt ? |
|---|---|
| X, Y, Z | oui (tout) |
| `Intensity` | une fois — réfutation n°15 (`docs/test_intensite.md`) ; Phase B2 en cours |
| `ReturnNumber`, `NumberOfReturns` | **non** (KP les utilise via ses paramètres, jamais réglés — archive du plan §5) |
| `ScanAngleRank` / `ScanAngle` | en diagnostic une fois (r = 0,0339) |
| `PointSourceId` (ligne de vol) | protocole L2 de la note multi-passes (non exécuté faute de données) |
| GPS time, `ScanDirectionFlag`, `EdgeOfFlightLine` | **non** |
| Dimensions extra éventuelles (`DTM_MAKER`, `DSM_MAKER`, `ScannerChannel`…) | **non** — présence inconnue dans nos dalles (piste n°1) |

### 1.3 Les métadonnées d'acquisition

Disponibles par dalle via le WFS de métadonnées de la Géoplateforme (`url_npl`,
`code_mission`, dates — ÉTABLI, notes de session) : **date d'acquisition**, mission,
densité, et le **procédé** de classification (« Optimisé » avec correction manuelle, vs
« Classé » automatisé par IA — SOURCE, catalogue). Le dépôt ne lit aucune de ces
métadonnées aujourd'hui : `scripts/fetch.py` télécharge la géométrie, pas la fiche.

### 1.4 Les produits dérivés de la même famille

**SOURCE** (IGN, mars 2025) : le programme diffuse, dalle par dalle (1 km × 1 km,
GeoTIFF) le **MNT**, le **MNS** et la **MNH** (= MNS − MNT), dérivés des mêmes nuages.
Le dépôt **recalcule son propre sol** (`hag_nn`, k = 8) au lieu d'utiliser ces produits —
choix légitime, mais jamais confronté à la version IGN.

---

## 2. Les pistes, une par une

### 2.1 Audit du contenu réel des dalles (15 min) — à faire avant tout le reste

```bash
pdal info --schema   LIDAR/LHD_FXX_0449_6885_PTS_LAMB93_IGN69.copc.laz   # dimensions + types
pdal info --metadata ... | grep -i "minz\|maxz\|count\|scale\|offset"     # bornes, nb de points
pdal info --stats    ...    # par dimension : min/max/mean/skew (Intensity notamment)
```
puis un **histogramme des classes** (une passe Python sur la colonne `Classification`,
comme le fait déjà `scripts/diag/diag_hag_feasibility.py` étape 1).

**Sortie attendue** : la liste réelle des classes et leurs effectifs ; la présence (ou non)
de 65/66 ; la présence de `DTM_MAKER`/`DSM_MAKER` ; l'intensité effective (min/max/saturation).

**Gain concret** : chacune des pistes 2–7 ci-dessous est décidée par cette réponse. Sans
elle, on spécule.

### 2.2 Filtrer les points virtuels (66) et artefacts (65) — 1 h

**Ce que c'est** (SOURCE) : les **points virtuels** sont des points interpolés ajoutés par
l'IGN pour rendre les surfaces continues (plans d'eau, sous les ponts) ; les **artefacts**
sont des retours inexpliqués.

**Ce que ça changerait** : ces points sont aujourd'hui comptés dans `total_count` et
reçoivent un HAG ; s'ils tombent dans [0,3 ; 3,0] m, ils créent ou déplacent du vert. Le
test est une variante de pipeline (`filters.expression "Classification != 65 && Classification != 66"`)
et une comparaison : Δ sur `density_hag`, sur les surfaces classées, et sur l'AUC
conditionnelle (0,4919 aujourd'hui).

**Gain concret** : un raster dont chaque point est un vrai retour laser — supprime une
classe entière de faux positifs possibles, notamment au bord des plans d'eau.

**Statut** : NON TESTÉ. Coût : une variable de plus dans un pipeline existant.

### 2.3 Un ratio construit sur les classes IGN (3/4/5) — 2 h, sans PDAL

**L'idée** : l'IGN fournit gratuitement une stratification de la végétation aux seuils
0–50 cm / 50–150 cm / > 150 cm. On peut construire, par cellule :

```
ratio_classes = (|3| + |4|) / (|2| + |3| + |4| + |5|)
```

et lui faire passer **exactement les mêmes tests** que notre ratio HAG : AUC conditionnelle,
AUC inter-classes (406/408 : 0,6026 ; 408/410 : 0,4807), surfaces classées.

**Gain concret, si c'est comparable** : `hag_nn` (et son k = 8, et l'interpolation
maison) **disparaît** du chemin végétation — une étape en moins, un paramètre en moins, et
une meilleure robustesse là où notre normalisation a échoué (Kuti, p95 compressé). Si c'est
moins bon, on documente et on ferme.

**Limite honnête** : les classes IGN sont produites avec **leur** DTM et **leur**
algorithme ; on compare deux chaînes complètes, pas un attribut isolé. Et la bande
« végétation basse » IGN (0–50 cm) recoupe la piste sous-bois déjà refermée — on n'en
attend pas un miracle sur le 406, plutôt une simplification et un contrôle indépendant.

**Statut** : NON TESTÉ. Aucune donnée nouvelle, aucun PDAL : lecture des dalles + comptage.

### 2.4 MNT/MNH IGN : valider — ou remplacer — notre sol (½ j)

**Ce qu'on a déjà** : `diag_hag_feasibility.py` mesure, par dalle, la proportion de sol, le
relief, et une validation croisée interne (points sol pairs → modèle, impairs → test ; verdict
contre le seuil de 0,30 m). C'est une validation **interne**.

**Ce qui manque** : la confrontation **externe**. Télécharger le MNT/MNH IGN de la même
dalle et comparer :
1. notre interpolation du sol (`hag_nn`, k = 8) vs **MNT IGN** — écart par cellule ;
2. notre hauteur de canopée (max/P95 de HAG par cellule) vs **MNH IGN** — écart par cellule.

**Gain concret** : la base sur laquelle reposent toutes les mesures (AUC, recall, surfaces)
cesse d'être auto-référencée. Et si le MNT IGN est meilleur, la variante
`filters.hag_dem` (SOURCE, doc PDAL) **supprime `hag_nn`** : une étape, un paramètre et un
risque en moins (règle de l'avenant n°02 §0 : supprimer une étape).

**Statut** : NON TESTÉ. Coût : deux téléchargements + un script de comparaison.

### 2.5 Date et procédé de classification par dalle (30 min)

**Ce qu'on peut lire** (SOURCE) : le WFS de métadonnées expose `code_mission`, les dates et
`url_npl` par dalle ; le catalogue documente aussi le procédé (O = optimisé, corrigé à la
main ; C = classé par IA).

**Le test** : récupérer ces champs pour nos dalles (Grimbosq, Airelles, Kuti, Kilemäed…) et
les croiser avec les modes de défaillance déjà documentés (bilan §14) :
- une acquisition **feuilles tombées** rend les feuillus transparents au LiDAR → moins de
  retours dans la bande → sous-détection du 406 ; c'est exactement le biais saisonnier que
  la documentation KP signale (décidus vs conifères) ;
- une dalle classée par procédé **C** (IA) peut avoir des classes moins fiables → piste 2.3.

**Gain concret** : transforme « le pipeline échoue sur Airelles » en « le pipeline échoue
sur Airelles, acquise en X, et voici ce que ça implique ». C'est du domaine de validité
documenté, pas du réglage.

**Statut** : NON TESTÉ (les dates sont accessibles ; le croisement n'a jamais été fait).

### 2.6 Fraction de pénétration (impulsions, pas retours) — ½ à 1 j

**La distinction** : tous nos comptages sont des **retours**. Une **impulsion** émise peut
produire plusieurs retours (canopée puis sol). La « gap fraction » — proportion d'impulsions
qui atteignent le sol — est LA métrique de couverture de canopée en foresterie, et elle est
calculable depuis le fichier : une impulsion = les points partageant un même `ReturnNumber == 1`
(ou un même GPS time), les retours sol de cette impulsion = `Classification == 2`.

**Ce que ça changerait** : une mesure de **fermeture de canopée** indépendante de notre
bande HAG ; utile pour les limites de peuplement (Phase B2) et pour comprendre pourquoi
deux forêts denses ne se ressemblent pas dans nos rasters. La littérature (revue multi-passes)
la relie par inversion de Beer-Lambert à la densité de végétation.

**Gain concret** : un canal de plus, orthogonal aux précédents, sur la même dalle — sans
nouvelle acquisition.

**Statut** : NON TESTÉ. Coût : un pipeline PDAL + un raster (`output_type: mean`,
`dimension: ReturnNumber`) puis les mêmes tests AUC.

### 2.7 Hygiène multi-dalles et lecture ciblée — 1 h + ½ j

Deux vérifications sans glamour mais qui protègent les mesures :
- **Doublons de bord** : nos terrains lisent 6 dalles contiguës ; si les dalles se
  recouvrent, les cellules de bord sont comptées deux fois et le raster ment localement.
  Test : compter les (X, Y, Z, GPS time) en double sur un terrain, et regarder la densité
  le long des jointures.
- **Lecture COPC par emprise** : `readers.copc` accepte un `bounds` (SOURCE, doc PDAL) ;
  pour les essais sur une fenêtre (fen1_406, 25 ha), ne lire que l'emprise utile. Gain :
  temps d'itération.

**Statut** : NON TESTÉ (le taux de doublons est inconnu).

---

## 3. Ce qui est déjà tranché — ne pas rouvrir par cette porte

| Piste | Statut | Référence |
|---|---|---|
| Classe 5 (végétation > 1,5 m) comme masque de canopée | **réfutée** — médiane identique terrain ouvert vs veg_406 | bilan, levier 6 |
| Bande basse type sous-bois (0,2–1,0 m) | **refermée** — occupation A 0,062 ≤ C 0,071 ≤ D 0,076 | archive du plan §1 |
| Intensité comme discriminant 406/blanc | **refermée** — réfutation n°15 | `docs/test_intensite.md` |
| `voxeldownsize` comme correctif de recouvrement | **disqualifié** — lave 32–50 % du signal | archive du plan §1 |
| PointSourceId (multi-looks) | **protocole écrit, non exécuté** — ne pas dupliquer | `docs/pistes_raster_multipasses.md` L2 |

**À noter** : « nuage brut » (non classé) existe aussi au téléchargement. Utile uniquement
si l'on décidait de reclasser nous-mêmes — coût disque/CPU élevé, aucune raison aujourd'hui.

---

## 4. Où ces pistes s'insèrent dans l'ordre déjà acté

Ordre actuel (revue du 2026-10-08) : **audit ini KP → banc vertical B0–B4 → V5/V6 →
overlap/`DTM_MAKER` → Phase A → Phase B2 → Phase C**.

- **Avant l'audit ini** : piste 1 (15 min) — elle décide si `DTM_MAKER` existe (et donc si
  la correction d'overlap est faisable en une ligne), combien de 65/66 nous polluons, et
  quelles classes nous avons vraiment.
- **En parallèle du banc vertical** (même famille de question : « quelle définition de la
  végétation sépare le mieux ? ») : piste 3, sans PDAL, sur les rasters et les dalles déjà
  en cache ; piste 2, une variante de pipeline.
- **Indépendant, quand on veut** : piste 4 (validation externe), piste 5 (30 min, à faire
  tôt car elle peut réinterpréter des échecs déjà attribués au terrain).
- **Après la Phase B2** : piste 6 (gap fraction), qui nourrit les mêmes questions de
  peuplement.
- **Avant tout comptage définitif** : piste 7 (doublons), qui conditionne la confiance dans
  les densités de bord.

---

## 5. Ce qu'on ne promet pas

- Aucune de ces pistes n'augmente le **recall du 406** par magie : le plafond mesuré ne vient
  pas du contenu des fichiers mais du signal (bilan §3.4, §14).
- Les classes IGN sont **une source**, pas une vérité : elles viennent d'un algorithme
  (parfois IA, procédé « C ») et d'un DTM qui ne sont pas les nôtres.
- La MNH IGN ne remplace pas la validation terrain — elle compare deux chaînes de calcul.

---

## 6. Références

- **IGN** : documentation produit « Nuages de points LiDAR HD » (11 catégories ; densité
  ≥ 10 pts/m²) ; actualité mars 2025 (MNT/MNS/MNH, `DTM_MAKER`/`DSM_MAKER`, classification
  « Version 5 ») ; catalogue data.gouv.fr / open-datara (liste des classes, procédés
  O/C) ; offre de produits LiDAR 2025-08 (MNT, MNS, MNH = MNS − MNT, dalles 1 km × 1 km).
- **PDAL** : `filters.hag_nn` (sol = classe 2, k voisins pondérés par distance),
  `filters.hag_dem` (DEM raster externe), `readers.copc` (`bounds`).
- **Dépôt** : `scripts/diag/diag_hag_feasibility.py` (validation croisée interne du sol,
  zone de bascule 0,30–0,50 m), `src/run_engine.py` (`undergrowth`, zones KP),
  `scripts/run_terrain.py` (pipelines sans filtre de classe), `docs/bilan_v0.md` (§14
  domaine, leviers 6 et 15), `docs/pistes_raster_multipasses.md` (L2, PointSourceId),
  `docs/test_intensite.md`, `docs/revue_plan_signaux_lidar.md`.
