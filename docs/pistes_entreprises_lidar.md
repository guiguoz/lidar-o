# Panorama — les entreprises qui exploitent le LiDAR (et ce qui s'y transpose)

> Question posée (2026-10-08) : « regarder du côté des entreprises qui exploitent le lidar ? »
>
> Objet : qui fait quoi dans ce marché, ce qui est **transposable** à Lidar'O, ce que ça
> change au plan. Complète `docs/revue_plan_signaux_lidar.md`,
> `docs/pistes_contenu_fichiers_lidar.md` et `docs/pistes_symboles_isom.md` sans les répéter.
>
> Statuts : **ÉTABLI** (mesuré dans le dépôt), **SOURCE** (page vérifiée),
> **INTERPRÉTÉ**, **NON VÉRIFIÉ**.

---

## 0. Réponse courte

1. **Personne ne vend ce que fait ce projet.** Le marché LiDAR est organisé autour de
   l'**acquisition** et de **l'analyse** (forêt, réseaux, infra) ; les cartes de course
   d'orientation à partir de LiDAR sont produites par des **individus** (MapAnt, Cassini,
   Karttapullautin) et outillées par **un éditeur** (OCAD). Aucune société trouvée dont le
   produit soit « un fond de carte CO automatique ». (NON VÉRIFIÉ au sens strict : absence de
   preuve, pas preuve d'absence.)
2. **Trois apports techniques concrets** (§2) : la réponse de l'industrie à notre artefact de
   bande (`overage removal`, implémentée par 4 outils indépendants) ; des métriques de
   structure de végétation **déjà industrialisées** par la filière forestière ; et l'outillage
   de contrôle de **l'intensité par ligne de vol**, qui répond directement au blocage B1.
3. **Deux avertissements** : les chiffres de marché cités plus bas viennent de cabinets de
   veille, à prendre comme ordres de grandeur ; et le modèle économique dominant (service à
   l'hectare, contrats long terme) **ne s'applique pas** à un projet CO bénévole — ce qui est
   une bonne nouvelle pour le projet et une mauvaise pour une hypothétique valorisation.

---

## 1. Le paysage en cinq segments

| Segment | Acteurs | Ce qu'ils vendent | Rapport à Lidar'O |
|---|---|---|---|
| **Producteurs de données** | IGN + consortiums : Geofit/Geofly, Sintegra/Pixair/Bluesky, Eurosense/SFS, Avineon/APEI | Le nuage HD (10 pts/m²), la classification, les MNx | Nos données viennent de là — leur procédé explique nos classes |
| **Éditeurs d'outils de traitement** | Terrasolid (Fi), rapidlasso/LAStools (De), Bentley, Esri ; libre : PDAL, GDAL, CloudCompare, lidR (R), FUSION (USFS) | Chaînes de production : recalage de lignes, classification, MNT | **Le plus transposable** : ce sont leurs recettes pour nos problèmes |
| **Fabricants capteurs/plateformes** | RIEGL, Leica/HxGN, Trimble, Teledyne Optech, YellowScan, Phoenix, DJI | Scanners aéroportés et drone | Ce qu'ils corrigent à la source (amplitude calibrée) reste à notre charge sur un jeu livré |
| **Analyse forestière & végétation** | Arbonaut (Fi), NV5 Geospatial (US), Woolpert (US), Fugro, GeoDigital, Silvalytics (UK/IE), AiDash (satellite) | Inventaires, structure de peuplement, biomasse, abords de lignes HT | Métriques voisines des nôtres, usage opposé (risque/exploitation, pas équité sportive) |
| **Bulle « course d'orientation »** | OCAD AG (Ch), Trailblaze/Blaze (Fi), + individus : J. Ryyppö (Karttapullautin), MapAnt.fi, N. Rio (Cassini/Mapant.fr), Terje Mathisen | Logiciels d'édition, fonds de carte, cartes papier | Notre niche réelle : elle est **mixte** logiciel éditeur / production bénévole |

### 1.1 Producteurs — ce que leur procédé implique pour nous

**SOURCE** (IGN, presse spécialisée) : l'acquisition et une partie du traitement sont
sous-traitées à quatre consortiums — Geofit/Geofly, Sintegra/Pixair/Bluesky, Eurosense/SFS,
Avineon/APEI. Geofit déclare par ailleurs classifier les données brutes **par un modèle de
deep learning développé par son service innovation** (LinkedIn Geofit) ; le catalogue IGN
distingue des blocs « Optimisé » (corrections manuelles) et « Classé » (automatique par IA).

**Conséquence pour nous** (INTERPRÉTÉ) : nos terrains ne viennent pas tous du même chaîne de
production ni du même procédé de classification. Cela **complète** la piste 5 de
`docs/pistes_contenu_fichiers_lidar.md` (date + procédé par dalle) : les écarts de qualité
entre Grimbosq, Airelles, Kuti et Kilemäed peuvent être en partie **documentaires**, pas
seulement terrain.

### 1.2 Éditeurs d'outils — c'est là que se trouve la matière transposable

| Outil | Éditeur | Fonction | Lien avec nos problèmes |
|---|---|---|---|
| **TerraMatch** | Terrasolid (Finlande, 30+ ans) | Calibration et **ajustement de bandes** : compare les bandes de vol en recouvrement, calcule angle de désalignement et erreurs XYZ par ligne (« cut the overlap ») | **NON TESTÉ chez nous** — c'est la solution industrielle de l'artefact de bande (§2.1) |
| **TerraScan** | Terrasolid | Classification, gestion des nuages | Référence du métier ; hors budget (licences MicroStation/Bentley) |
| **lasoverlap** | rapidlasso (LAStools) | **Contrôle qualité** : rasters de recouvrement (combien de lignes couvrent la zone) et d'écart vertical/horizontal ; option `-intensity` pour vérifier la **calibration d'intensité entre lignes de vol** | Répond directement au blocage B1 (comparabilité de l'intensité inter-lignes) |
| **lasoverage** | rapidlasso | Repère et **retire les points « overage »** (couverts par plus d'une ligne) selon l'angle de scan | La correction de bande standard (§2.1) |
| **Classify LAS Overlap** | Esri (ArcGIS) | Classe en recouvrement les points les plus éloignés du nadir, garde les meilleurs | Même principe, 4ᵉ implémentation |
| **PDAL / GDAL / CloudCompare / lidR / FUSION** | open source & USFS | Lecture COPC, MNT/MNS, métriques de canopée, nuages | Déjà notre boîte à outils ; `lidR`/FUSION apportent les métriques forestières (§2.2) |

**Précision légale/pratique** : les outils LAStools cités sont sous licence, mais
**testables gratuitement jusqu'à ~3–5 millions de points** (SOURCE, README LAStools) — assez
pour un test sur une fenêtre, pas sur un terrain entier.

### 1.3 Fabricants — la réflectance calibrée

**SOURCE** (fiches RIEGL et distributeurs) : les scanners RIEGL (série VQ-1560, dont le
VQ-1560 II-S à double canal) fournissent des « **calibrated amplitudes and reflectance
estimates** » — des amplitudes calibrées et des estimations de réflectance, par opposition à
l'intensité brute. La littérature de calibration radiométrique (thèse HAL) rappelle que
l'intensité brute dépend fortement de la **géométrie de mesure** (portée, angle d'incidence)
et du traitement interne du capteur — ce qui est cohérent avec notre mesure maison
(r = 0,034 seulement sur nos populations, donc pas de conclusion générale).

**Conséquence** : si nos dalles ne portent qu'un `Intensity` brut, leur comparabilité
inter-forêts et inter-lignes est **notre problème**, pas celui du capteur. C'est exactement
l'objet du blocage B1 — et `lasoverlap -intensity` en est l'outil prêt à l'emploi (§2.3).
(NON VÉRIFIÉ : quel capteur a volé **nos** dalles — à lire dans les métadonnées, piste 5.)

### 1.4 Analyse forestière & végétation — le métier le plus proche du nôtre

- **Arbonaut** (Joensuu, Finlande, 1994) : **30 M+ hectares inventoriés au LiDAR aéroporté**,
  détection d'arbres individuels depuis 1998, méthode LAMP avec WWF, projet de **biomasse de
  sous-étage** sur 130 000 ha (pour pellets, suivi et risque incendie), inventaire d'arbres
  morts sur pied. Vendu à Metsähallitus, au Centre forestier finlandais, etc. (SOURCE,
  site + ESRI partner page).
- **NV5 Geospatial** (ex-Quantum Spatial, US) : délinéation d'arbres individuels, hauteur,
  couverture de canopée, densité de tiges, couronne ; **identification d'espèces par
  hyperspectral** ; programme « Transmission Vegetation Management » (> 75 000 miles de
  lignes), avec un exercice remarquablement proche du nôtre : extraction de polygones
  « IVM » pour la végétation **entre 18 pouces et 6 pieds (≈ 0,45–1,8 m)**, surface minimale
  1/10 d'acre, pour cibler les interventions de débroussaillage (SOURCE, PDF NV5).
- **Woolpert**, **Fugro**, **GeoDigital**, **Silvalytics/Bluesky**, **AiDash** (satellite) :
  même famille — inventaire, risque, emprise, conformité.

**Ce que ça dit** (INTERPRÉTÉ) : notre bande basse (0,3–3,0 m) et l'idée de « zones à
végétation gênante » sont **déjà industrialisées** — mais pour la **sécurité des réseaux** ou
la **ressource bois**, jamais pour la **franchissabilité sportive**. Le vocabulaire diffère
(« encroachment », « ladder fuels », « understory biomass ») et la grandeur mesurée aussi
(mètres de dégagement, tonnes/ha). Aucun de ces acteurs ne vend « gêne à la course » : la
référence sur ce sujet reste **Trier 2015**, dix ans après.

### 1.5 La bulle CO — notre niche réelle

- **OCAD AG** (Suisse) : éditeur du logiciel, et fournisseur d'outils LiDAR intégrés
  (Point Cloud Manager, DEM Wizard, Feature Map) — c'est le seul acteur **commercial** de la
  bulle, et il vend des **outils**, pas des cartes.
- **Trailblaze Software** (Finlande) : Blaze ; son CRT (Apache 2.0) est déjà réutilisé par ce
  dépôt (ÉTABLI, `docs/etat_existant.md` §4).
- **MapAnt.fi** (Jarkko Ryyppö, Joakim Svensk, Mats Troeng) : carte de course d'orientation
  nationale de la Finlande générée automatiquement — ~100 ordinateurs, ~10 To traités,
  image de 150 gigapixels à 0,7 px/m, données laser 2008–2016, Karttapullautin au cœur du
  procédé (SOURCE, MapAnt « About »).
- **Cassini / Mapant.fr** (Nicolas Rio) : même approche en France, Rust + PDAL/GDAL,
  inspiration Karttapullautin + pipeline Terje (SOURCE, GitHub + tutoriel mapant.fr).
- **Karttapullautin** (J. Ryyppö) et **le pipeline de Terje Mathisen** (JWOC 2015) :
  outils/pipelines individuels, largement repris par les clubs — c'est aussi ce que ce
  dépôt utilise déjà (ÉTABLI).

**Lecture** : la bulle CO est **petite, bénévole et outillée gratuitement**. Personne n'y
monétise un fond de carte automatique ; la valeur ajoutée reconnue y est l'**édition et le
travail de terrain**, pas la génération.

---

## 2. Trois enseignements transposables

### 2.1 L'artefact de bande : l'industrie **retire** les points de recouvrement

Notre bilan §7 a mesuré une densité **84,6 vs 41,2 pts/m²** entre bandes, et la note
multi-passes a qualifié l'artefact de seul défaut mesuré du raster. Quatre outils
indépendants en donnent la même réponse — **garder, par cellule, les points d'une seule
ligne de vol, les plus proches du nadir, et jeter les autres** :

| Implémentation | Principe |
|---|---|
| LAStools `lasoverage` | « finds the overage points that get covered by more than a single flightline », selon l'angle de scan |
| Esri `Classify LAS Overlap` | « Points in the bin that do not belong to the chosen flight path are classified as overlap » — le choix se fait par angle minimal |
| Terrasolid TerraMatch | ajustement des lignes, puis « cut the overlap » dans le flux de production |
| **OCAD** « Overlap Points from » | le champ du Point Cloud Manager qui décide **à partir de quel seuil bas** les points de recouvrement comptent comme sous-bois (cf. `docs/revue_plan_signaux_lidar.md` §2.3) |

C'est une **quatrième stratégie** à côté des trois déjà documentées (Trier : décaler la borne
basse à 0,2 m ; nous : fusionner des looks moyennés, protocole L2 ; OCAD : seuil dédié) —
et la seule qui soit un **standard de fait**.

**Protocole (NON TESTÉ, aucun code nouveau nécessaire en apparence)** :
1. sur une dalle, par cellule de 2 m et par `PointSourceId`, ne garder que les points de la
   ligne au |`ScanAngleRank`| minimal (les « voisins du nadir ») ;
2. reconstruire `density_hag` + `total_count` ; mesurer le contraste bande/bande et la
   fraction de cellules à ≥ 3 sources (référence : 83,2 % vs 2,8 %) ;
3. rejouer l'AUC conditionnelle (plancher actuel **0,4919**).
Deux chemins : LAStools `lasoverage` (natif, licence, essai gratuit sur une fenêtre) ou un
passage Python sur la dalle — nos scripts lisent déjà les dalles en numpy
(`diag_hag_feasibility.py`).
**Articulation avec L2** : c'est la même famille que la fusion multi-looks ; si L2 est
exécuté d'abord, réutiliser sa stratification `n_looks`. Sinon, *overage removal* est plus
simple et mieux adossé à l'usage du métier.

### 2.2 La structure de végétation est un métier — sauf notre question

La filière forestière vend depuis vingt ans ce que nous essayons de calculer : couverture de
canopée, densité de tiges, biomasse de sous-étage, hauteur dominante, strates. Ses méthodes
(gap fraction par inversion de Beer-Lambert, métriques par voxel, régression bayésienne sur
placettes — méthode LAMP d'Arbonaut) sont **publiées et documentées**.

**À prendre** : les **définitions** et les conventions de calcul (nous réinventons parfois des
métriques standard), et le réflexe « métrique + validation terrain ».
**À ne pas prendre** : leurs produits et leur unité de vente (m³/ha, mètres de dégagement).
Ils répondent à « combien de bois / quel risque » ; nous répondons à « à quelle vitesse un
coureur passe ici ». Trier 2015 reste, à notre connaissance, la seule référence qui pose la
question dans nos termes — et il conclut lui-même à la difficulté de la classe « fight »
(0–4 % de bonne classification, cf. revue §3.4).

### 2.3 L'intensité : ce que le marché a résolu, ce qu'il laisse à l'utilisateur

- Ce que le **fabricant** corrige : les amplitudes calibrées / estimations de réflectance
  (RIEGL) — disponibles seulement si le capteur et le traitement le permettent (NON VÉRIFIÉ
  pour nos dalles).
- Ce que **l'éditeur d'outils** fournit : `lasoverlap -intensity` — un raster des **écarts
  d'intensité entre lignes de vol** dans les zones de recouvrement. C'est, littéralement, le
  test « variance inter-lignes vs variance inter-types » que B1 demande, disponible en une
  commande (fenêtre d'essai gratuite).
- Ce qui reste **à l'utilisateur** : la normalisation radiométrique et l'interprétation
  (la thèse HAL citée montre que l'intensité dépend de la portée et de l'incidence — donc une
  normalisation par ligne de vol est un pré-requis, pas un raffinement).

---

## 3. Ce que ce panorama change (ou pas) dans le plan

| # | Action | Où ça s'insère | Coût |
|---|---|---|---|
| 1 | **Tester `overage removal`** (garder le nadir d'une ligne par cellule) et re-mesurer le contraste de bande + l'AUC | Avant ou à la place de L2 (§2.1) | ½ j |
| 2 | **`lasoverlap -intensity`** sur une fenêtre → chiffrer la comparabilité de l'intensité inter-lignes | Débloque B1 avant B2 | 1 h + essai gratuit |
| 3 | **Lire procédé/date par dalle** (piste 5 du doc contenu) et corréler avec les échecs par terrain | Avant les conclusions multi-terrains | 30 min |
| 4 | **Reprendre les définitions forestières** (gap fraction, couverture) plutôt que réinventer | Quand un canal « structure » sera testé | lecture |
| 5 | **Ne pas chercher de concurrent à battre** : la niche est bénévole, l'éditeur vend des outils | §9 du plan (finir le livrable) | — |

Ce qui **ne change pas** : les paramètres de production restent intouchés jusqu'à jugement
sur planche ; les trois pistes refermées restent refermées ; l'ordre général
(audit ini → banc vertical → ordre de généralisation → overlap → Phase A → B2 → C) reste
valide — l'action 1 s'y substitue simplement à la variante lourde du multi-looks, et
l'action 2 débloque B1.

---

## 4. Limites de ce panorama

- **Chiffres de marché** (ex. « vegetation management LiDAR » ~1,8 Md$ en 2025, ~5,7 Md$ en
  2034 ; « utility vegetation analytics » ~2,1 → 5,8 Md$) : issus de cabinets de veille
  commerciaux, **non recoupés** — ordres de grandeur seulement.
- **Non vérifié** : le ou les capteurs ayant acquis nos dalles ; la présence d'un attribut de
  réflectance dans nos fichiers ; l'existence éventuelle d'un prestataire facturant des fonds
  de carte CO en France.
- **Absence de preuve ≠ preuve d'absence** : le tour d'horizon n'a pas trouvé de société dont
  le produit soit un fond CO automatique ; il ne prouve pas qu'il n'en existe aucune.
- Prix : la plupart des outils cités sont « sur devis » (TerraMatch, TerraScan) — aucun
  chiffrage n'est possible ici.

---

## 5. Références

- **IGN / producteurs** : ign.fr programme LiDAR HD (consortiums Avineon/APEI, Geofit/Geofly,
  Eurosense/SFS, Sintegra/Pixair/Bluesky) ; geofit.fr « Le LiDAR HD de l'IGN » ; LinkedIn
  Geofit (classification par deep learning) ; decryptageo.fr (accord-cadre 2020) ;
  inairtech.fr (services d'exploitation).
- **Outils** : terrasolid.com TerraMatch (« Calibration and Strip Adjustment », « cut the
  overlap ») ; rapidlasso.de (lasoverlap, lasoverage ; essai gratuit jusqu'à ~3–5 M de
  points ; README lasoverlap) ; doc Esri « Understand overlap classification » ; PDAL, GDAL,
  CloudCompare, lidR, FUSION.
- **Capteurs** : riegl.com VQ-1560 II-S et communiqués RIEGL (« calibrated amplitudes and
  reflectance estimates ») ; HAL tel-03307700 (dépendance géométrique de l'intensité).
- **Analyse forestière** : arbonaut.com (30 M+ ha, LAMP, sous-étage, bois mort) ; NV5
  Geospatial (forestry et Transmission Vegetation Management, polygones IVM 18 pouces–6
  pieds) ; woolpert.com/lidar ; Silvalytics + Bluesky.
- **Bulle CO** : ocad.com (Point Cloud Manager, DEM Wizard) ; mapant.fi/about ; github
  NicoRio42/cassini + mapant.fr « Cassini pour les nuls » ; Karttapullautin (Ryyppö) ;
  pipeline Terje Mathisen (JWOC 2015).
- **Dépôt** : `docs/bilan_v0.md` §7 (bandes), §12 (vectorisation), §14 (domaine) ;
  `docs/pistes_raster_multipasses.md` (L2, PointSourceId) ; `docs/test_intensite.md` ;
  `docs/etat_existant.md` §4 (CRT Blaze) ; `docs/revue_plan_signaux_lidar.md` ;
  `docs/pistes_contenu_fichiers_lidar.md` ; `docs/pistes_symboles_isom.md`.
