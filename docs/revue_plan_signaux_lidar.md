# Revue du « Plan — Signaux LiDAR inexploités »

> Revue contradictoire, 2026-10-08. Méthode : chaque affirmation du plan est confrontée
> (1) aux documents du dépôt, (2) aux sources primaires (article de Trier 2015 en texte
> intégral, wiki OCAD, code source de Karttapullautin v2.12.1 et de Cassini, documentation
> IGN). Les divergences sont signalées explicitement, y compris quand elles contredisent le
> plan **ou** ce dépôt.
>
> Verdict global : **le plan est bon, deux de ses affirmations centrales sont à corriger, et
> le croisement fait apparaître un levier publié que ni le plan ni la campagne n'ont testé**
> (§3.1). L'ordre des phases change en conséquence (§5).

---

## 1. Vérification affirmation par affirmation

| # | Affirmation du plan | Source externe | Ce que dit le dépôt | Verdict |
|---|---|---|---|---|
| 1 | OCAD calcule la NDVD de Trier, seuils entre −1 et +1 | Wiki OCAD *LiDAR Point Cloud Manager* : « The calculation based on the NDVD (Normalized Difference Vegetation Density). The thresholds for the undergrowth and the vegetation shall be between -1.0 and +1.0 » | `docs/archive/PLAN_vegetation_406.md` cite Trier 2015 et Schaad 2017 | **Confirmé** |
| 2 | Les seuils se calculent à partir d'échantillons (« Statistics ») | Même page : « The thresholds can be calculated with samples in the **Statistics** function » | Aucun mécanisme équivalent dans le dépôt : seuils fixes | **Confirmé, et c'est le cœur du plan** |
| 3 | Les valeurs par défaut OCAD sont optimisées pour une forêt suisse précise | Même page : « The default values are optimized for Steinhauserwald in Switzerland and LiDAR data from Canton Zürich. The settings depend on the forest type and the LiDAR data » | — | **Confirmé** |
| 4 | L'intensité discrimine feuillus / résineux | Wiki OCAD (*Intensity Map* : forêt noire = conifères, grise = feuillus, limites de végétation plus nettes que sur la carte de hauteur) ; blog OCAD 2026-06 | **Déjà testée et close** : réfutation n°15 du bilan, `docs/test_intensite.md`, `docs/archive/CONSIGNE_intensite_406_v2.md` | **Vrai pour l'essence, faux pour « jamais lue »** → §2.1 |
| 5 | La `Feature Map` 2024 exploite les points non-sol sous 2 m | Wiki *DEM Import Wizard*, blog 2024-07 (exemples : 0,5 m de cellule, seuils 0,0–2,0 m, 13–29 pts/m²) | Bande proche-sol mesurée non discriminante (A 0,062 ≤ C 0,071 ≤ D 0,076) | **Confirmé** ; non contradictoire, mais c'est une autre question → §4.3 |
| 6 | NDVD « déjà connu du projet, déjà reproduit via omapmaker, rien de nouveau » | Trier 2015, éq. 1 : `NDVD = (V − G)/(V + G)` | Bilan §5 : `ratio` HAG/total vs `NRD = bande/(bande+dessous)` → écart max **0,0006** | **Confirmé, et plus fort que dit** : NDVD = 2·NRD − 1, donc **transformation affine de la métrique déjà calculée** → §2.3 |
| 7 | KP exploite le nombre de retours « aux valeurs par défaut » | Code KP : défauts `firstandlastreturnfactor = 0.0`, `lastreturnfactor = 0.0` ; `pullauta.default.ini` livré : `1` et `1` | Notre `src/run_engine.py` **n'injecte pas ces clés** dans l'ini minimal | **Vrai, mais les « valeurs par défaut » dépendent d'un fichier non versionné** → §2.4 |
| 8 | Cassini : gaussien sur les densités, r=4 / σ≈2 m, avant seuillage | `NicoRio42/cassini` : `vegetation.rs` convolue les rasters de **comptage** (`output_type: count`, 1 m, `binmode`) par des noyaux gaussiens (`radius 4 → σ = 2`), puis compare à `green_threshold_*` | — | **Confirmé** |
| 9 | KP : médians sur les indices après seuillage | Code KP : `imggr1.median_filter(med/2, med/2)` après l'affectation des teintes `greenshades` | — | **Confirmé** |
| 10 | Zones A/B/C/D réutilisables comme échantillons → non, circulaires (auto-critique §8.2 du plan) | — | — | **Correct** : découpées par intersection avec la sortie du pipeline |
| 11 | `voxeldownsize` disqualifié (lave 32–50 % du signal) | Doc PDAL : un point retenu par voxel, les autres filtrés | — | **Cohérent** — et voir §4.4 : Cassini l'utilise volontairement, ce qui nuance la portée de la clôture |

---

## 2. Les quatre corrections qui changent le plan

### 2.1 « L'intensité n'a jamais été lue » : faux, et la nuance est décisive

Le plan écrit (§1, tableau) : `Intensity` — « Lu par Lidar'O ? **jamais** ». C'est inexact.
Le dépôt contient **trois** artefacts :

- `docs/test_intensite.md` : AUC 0,3638 (inversée 0,6362) entre FN_406 et blanc, conclusion
  « Piste close », plus le contrôle de dépendance angulaire r(intensité, `ScanAngleRank`) =
  **0,0339** ;
- `docs/archive/CONSIGNE_intensite_406_v2.md` : protocole complet, avec pronostic négatif
  écrit **avant** mesure (« Ce test est probablement une réfutation ») ;
- `docs/bilan_v0.md` ligne 679 : **réfutation n°15** sur quinze, dans le tableau des leviers
  fermés.

Ce que ce test a réellement mesuré, c'est **l'intensité comme discriminant de
franchissabilité dans la bande [0,3 ; 3,0] m**, contre le blanc FFCO — et il l'a close pour
un motif documenté : biais d'échantillonnage (peu de retours dans la bande ⇒ la moyenne
d'intensité décrit des retours de sol/litière, pas de la végétation).

Ce qui reste **réellement ouvert** est exactement ce que le plan propose en B2 : l'intensité
comme discriminant d'**essence**, sur des retours de canopée, avec une vérité terrain
indépendante. Cette question n'a jamais été posée. La distinction n'est pas rhétorique :
elle détermine la population d'échantillonnage (canopée, pas bande) et le critère (médianes
et IQR par formation, pas AUC de franchissabilité).

**Action** : réécrire la ligne du tableau §1 et l'encadré « le plus rentable reste
l'intensité ». Une piste déjà close une fois ne se rouvre pas par reformulation — elle se
rouvre sur une **question différente**, ce qui est le cas ici, à condition de le dire.

### 2.2 La Phase B2 est probablement infaisable sur Grimbosq

Le plan place la Phase B2 (« intensité vs BD Forêt V2 ») sur Grimbosq sans vérifier que les
deux formations y coexistent. Or `docs/bilan_v0.md` §14 documente le terrain principal
comme **feuillus**, et les autres terrains comme **résineux/lande** (Airelles) ou
**épicéas** (Kuti). Un contraste feuillus/résineux ne se mesure pas dans un massif feuillu,
et pas non plus en comparant deux massifs différents sans contrôler les autres facteurs.

**BD Forêt V2 est le bon référentiel** — vérifié : nomenclature nationale de 32 postes,
plage minimale 0,5 ha, distinction feuillus/résineux/mixtes, licence Etalab, disponible en
**WFS** (`LANDCOVER.FORESTINVENTORY.V2`) comme en SHP par département. Le dépôt sait déjà
interroger la Géoplateforme en WFS (`src/providers/france.py`, `scripts/fetch.py`) : le coût
d'intégration est quasi nul.

**Action** : choisir le terrain de mesure **après** un comptage BD Forêt V2 des surfaces
feuillus/résineux (30 minutes via WFS) ; viser une dalle où les deux formations sont
représentées à ≥ 10 ha, ou à défaut comparer Airelles (résineux) à Grimbosq (feuillus) en
contrôlant densité, saison et angle.

### 2.3 NDVD : ce n'est pas un levier, c'est une validation — et deux réglages OCAD qu'on avait ratés

Le plan concède que la NDVD est « déjà connue ». C'est plus tranchant que ça : avec
`NDVD = (V − G)/(V + G)` (Trier, éq. 1) et notre `ratio = bande/(bande + dessous)`, on a
**`NDVD = 2 × ratio − 1`**. Or le bilan §5 a mesuré que `ratio` et `NRD` (le dénominateur
« bande + dessous ») sont substituables à 0,0006 près. Autrement dit : **le projet calcule
déjà la NDVD, à une transformation affine près, depuis le premier jour.** Un éditeur
commercial qui implémente cette métrique valide donc notre choix, il ne l'enrichit pas.

Deux éléments du wiki OCAD sont en revanche **nouveaux pour nous** :

1. **La plage ±1 comme espace de calibration.** Nos seuils de production
   `[0,20 / 0,45 / 0,85]` se réécrivent en NDVD : `[−0,60 / −0,10 / +0,70]`. Trier publie,
   pour 10 pts/m² : `[0,00 / 0,35 / 0,70]`. Le seuil « fight » coïncide (0,70), mais nos deux
   seuils bas sont beaucoup plus permissifs que ceux de la référence — ce qui est cohérent
   avec la précision mesurée du pipeline (32 %) et les 59,6 % de faux verts (§3.3 du bilan).
   Attention : les seuils de Trier **dépendent de la densité d'impulsion** (à 2 pts/m² il
   publie −0,2 / 0,20 / 0,60), et nous sommes à ~150 pts/m². La comparaison n'est donc pas
   une vérité, c'est un **ordre de grandeur à tester** — et c'est précisément l'argument de
   la Phase A.
2. **« Overlap Points from »** — un champ de l'interface OCAD dédié aux points de
   recouvrement (classe LAS 12 / drapeau *overlap*) : « Overlap points is a classification
   type of LAS file format. These unclassified overlap points come from different scans
   (flight lines). Choose the lower threshold in which points should be considered as
   Undergrowth and Vegetation. If this value is too low, ground points are used as
   undergrowth and vegetation points. » **OCAD expose donc en réglage exactement l'artefact
   de bande que nous avons mesuré au §7 du bilan** — et l'IGN a livré en 2025 une
   classification « Version 5 » qui gère mieux les recouvrements et **marque les points
   retenus pour le MNT/MNS** par deux attributs, `DTM_MAKER` et `DSM_MAKER`. C'est un test
   bien moins coûteux que la voie multi-looks de `diag_multilook.py` → §4.3.

### 2.4 Les paramètres « validés » de KP vivent dans un fichier non versionné

Le plan (§10) range les onze `greenshades` et `medianboxsize: 9` parmi les paramètres de
production « à ne pas toucher ». Vérification dans le code :

- `src/run_engine.py::_build_ini` n'injecte **que** `lightgreentone` et `medianboxsize2` ;
  l'ini minimal généré ne contient **ni `greenshades`, ni `medianboxsize`, ni
  `firstandlastreturnfactor` / `lastreturnfactor` / `firstandlastreturnasground`** ;
- côté KP v2.12.1, `greenshades` **n'a pas de valeur de repli dans le code**
  (`gs.get("greenshades").unwrap_or("")` puis `parse::<f64>().unwrap()`) : sans la clé, le
  parsing panique ;
- `medianboxsize` a pour défaut `0` ⇒ `if med > 1` est faux ⇒ **le premier médian ne
  s'applique pas** ;
- les facteurs de retour ont pour défaut `0.0 / 0.0` dans le code, mais `1 / 1` dans le
  `pullauta.default.ini` livré par l'amont ;
- `pullauta.ini` est dans `.gitignore`, et le bilan §15.1.4 documente que **KP réécrit
  `pullauta.ini` à chaque exécution batch**.

Conclusion : les valeurs réellement en vigueur dépendent d'un fichier non versionné, présent
seulement sur la machine de production. Ce n'est pas un détail comptable : la Phase A du
plan consiste à **dériver les seuils d'échantillons**. On ne peut pas dériver des seuils
qu'on ne sait pas mesurer, ni comparer à un témoin dont on ne connaît pas le réglage.

**Action, 10 minutes, avant toute chose** :

```bash
# lire l'ini réellement utilisé par le dernier run (et non celui qu'on croit)
grep -E "greenshades|medianboxsize|firstandlastreturn|lastreturnfactor|lightgreentone" \
     work/pullauta.ini out_kp_*/pullauta.ini 2>/dev/null
# vérifier ce que la production injecte
python -c "from src.run_engine import _build_ini; print(_build_ini('a','b',None))"
```

Puis **épingler** ces valeurs dans `config.yaml` et les injecter explicitement (règle
« paramètres = données » de l'avenant n°02 §0bis), ou versionner un `pullauta.base.ini`.

---

## 3. Ce que le croisement fait apparaître et que ni le plan ni la campagne n'ont vu

### 3.1 Le banc vertical : nos bornes ne sont celles d'aucune implémentation de référence

C'est, de l'avis de cette revue, **le levier le plus rentable du moment** — publié, testable
en une passe PDAL, et jamais balayé.

| Implémentation | Bande verticale | Traitement |
|---|---|---|
| **Trier 2015** (NDVD) | **0,2 – 2,0 m** | comptage plat + noyau circulaire 2 m (poids plein jusqu'à 1 m, décroissance linéaire au-delà) |
| **Karttapullautin** | ≈ **1,0 – 2,65 m** poids 1 | puis 2,65–3,4 m poids **0,1**, 3,4–5,5 m poids 0,2 si toit < 8 m (`zone1/2/3`) |
| **Cassini** | 0 – 1 m / 1 – 4 m / 4 – 30 m | trois rasters de comptage, seuils propres par strate |
| **Lidar'O** | **0,3 – 3,0 m** | comptage **plat**, non pondéré |

Deux différences structurelles :

1. **La borne haute.** Tous les autres arrêtent le comptage de végétation basse autour de
   2,0–2,65 m ; nous montons à 3,0 m à poids égal. Or le bilan §6.2 a mesuré que la tranche
   **[1,5–3,0] m sépare aussi bien que la bande complète** — signature d'une contamination
   par des retours de canopée, exactement ce contre quoi Trier met en garde : *« if the tree
   canopies are very dense above 2 m above the ground, then very few lidar pulses may reach
   the 0–2 m vegetation height interval. So we need to compensate for the possibly weak
   signal. »* KP compense par `pointvolumefactor`, `topweight` et le **minimum** de
   `firsthit` sur 5×5 blocs — trois mécanismes que nous n'avons pas.
2. **La borne basse et les bandes de recouvrement.** Trier a mesuré **le même artefact de
   bandes** que notre bilan §7 : *« The NDVD of the 0.0–2.0 m above ground vegetation returns
   contains some artefacts in the form of clearly visible stripes, related to overlaps of
   data from different flight strips. These artefacts were reduced by using the returns from
   0.2–2.0 m above ground. »* Sa correction est un simple décalage de borne basse — pas un
   multi-looks. La nôtre (0,3 m) est déjà au-dessus ; **c'est la borne haute qu'il faut
   tester**.

**Protocole (1 passe PDAL, plusieurs sorties — cf. `docs/pistes_raster_multipasses.md` L0)** :

| Variante | Bande | Question |
|---|---|---|
| B0 | 0,3 – 3,0 m (production) | témoin |
| B1 | **0,2 – 2,0 m** | bande de Trier |
| B2 | 0,3 – 2,0 m | borne basse seule |
| B3 | 1,0 – 2,65 m | zone principale de KP |
| B4 | 3 strates pondérées (1,0–2,65 ×1 ; 2,65–3,4 ×0,1 ; 3,4–5,5 ×0,2 si toit <8 m) | transposition de `zone1/2/3` |

Lecture : AUC conditionnelle (aujourd'hui 0,4919 — le plancher à battre), AUC inter-classes
406/408 (0,6026) et 408/410 (0,4807), puis contraste bande/hors bande (§7). **Ce sont des
chiffres déjà établis dans le bilan : le protocole est directement comparable, aucune
nouvelle référence à construire.**

### 3.2 Trier donne aussi la réponse à la question « ordre des opérations » (§7 du plan)

Le plan hésite entre « seuiller puis généraliser » (KP) et « généraliser puis seuiller »
(Cassini). Trier tranche en pratique, et pas au milieu : il **seuille d'abord**, puis
applique une **cascade morphologique progressive** — `fermeture 7×7 → ouverture 3×3 →
fermeture 9×9 → ouverture 5×5 → fermeture 11×11 → ouverture 7×7` (pixels 1 m), avec cette
justification : *« If a too large kernel is used in morphological closing, then areas with
quite low vegetation density are also included. The solution is to use gradually increasing
kernels iteratively. »*

C'est un mécanisme que ni KP (un, deux médians plats) ni nous (ouverture 3, fermeture 3,
sieve) n'utilisons. Il est **testable sans PDAL**, sur le raster classifié déjà en cache :
les variantes **V5** (seuiller puis médianer, ordre KP) et **V6** (seuiller puis cascade de
Trier) sont implémentées dans `scripts/diag/sweep_ordre_lissage.py`.

### 3.3 Le test le moins cher de l'artefact de bande passe par l'IGN, pas par le multi-looks

Le plan n'en parle pas, OCAD si : `Overlap Points from`. Et l'IGN a publié en mars 2025 une
classification « Version 5 » où **les points retenus pour le MNT/MNS sont marqués**
(`DTM_MAKER`, `DSM_MAKER`), précisément pour mieux gérer les recouvrements de vol. Le test
devient :

1. `pdal info --schema` sur une dalle → la dalle porte-t-elle `DTM_MAKER` / un drapeau
   overlap / la classe 12 ? (10 minutes, décide si le test est possible)
2. si oui : rasteriser ce drapeau et le croiser avec l'occupation par ligne de vol
   (`PointSourceId`) et avec la bande mesurée au §7. **Si la bande coïncide avec les points
   de recouvrement, la correction est un filtre d'une ligne dans `build_pdal_*`
   (`Classification != 12` / `where DTM_MAKER == 0`), pas une refonte.**

### 3.4 Le résultat que Trier publie et que personne ne cite

Le plan espère de la Phase B un gain sur les **limites de peuplement**. Il faut poser à côté
le résultat du papier qui a introduit la NDVD, sur quatre forêts d'Oslo :

| Classe | Taux de classification correcte (Trier 2015, tab. 7) |
|---|---|
| ouvert | 81 – 88 % |
| forêt normale | 76 – 80 % |
| **slow run** | **22 – 52 %** |
| **walk** | **9 – 40 %** |
| **fight** | **0 – 4 %** |

Et l'auteur conclut : *« it is tempting to use only one class for reduced runability »*
(26–60 % sur une classe unique). C'est la validation externe de la conclusion de ce dépôt
(classification 406/408/410 abandonnée au livrable), et un garde-fou pour la suite : la
littérature **la plus citée** sur le sujet documente 0–4 % pour la classe « fight ».
Cela n'annule pas la Phase B2 — cartographier des limites d'essence est un autre objectif —
mais interdit de la présenter comme un rattrapage de la classification.

Bonus de mécanisme, également non repris dans le plan : Trier **compense le signal faible
avant de seuiller** (§2.1 : masque d'ouvert construit par morphologie, puis retiré de la
carte de densité de végétation). Nous n'avons pas d'équivalent : notre masque anthropique
(BD TOPO) n'est pas un masque d'ouvert morphologique.

---

## 4. Points de désaccord mineurs, et ce qu'ils impliquent

### 4.1 Le plan réordonne correctement (autocritique §8.1) mais pas assez loin

Le plan place la Phase A en premier. Bonne idée, mauvais prérequis : **la Phase A calibre des
seuils sur un canal dont la validité est en question** (§3.1 : borne haute contaminée par la
canopée, cf. bilan §6.2). Calibrer finement les seuils d'un signal mal borné fige l'erreur en
la rendant plus difficile à voir. D'où l'ordre du §5 : **canal, puis seuils**.

### 4.2 Phase A : deux verrous opérationnels que le plan sous-estime

Le plan annonce « le traçage des zones est manuel (une heure), le reste est du calcul sur des
données déjà en cache ». Pour la partie **KP**, c'est inexact :

- KP n'exporte **pas** la valeur continu de son indice ; il exporte des **teintes déjà
  quantifiées** (`greenshades`), et applique ses médians sur cette image de teintes. On ne
  peut donc pas dériver des seuils d'échantillons à partir d'un raster KP existant — la
  grandeur à seuiller n'y est plus. Il faut soit boucler (`pullauta makevege` est prévu pour
  ça : il recalcule la végétation seule, sans les courbes), soit réimplémenter l'indice.
- Corollaire : la comparaison au « raster validé à la main » doit porter sur un **fichier
  figé** (empreinte avant l'expérience), sinon le témoin bouge.

Là où la Phase A est immédiatement opérationnelle, c'est sur **notre propre indice**
continu (`ratio` HAG), que nous contrôlons de bout en bout et dont nous savons calculer la
valeur par zone d'échantillon. C'est aussi la version qui a un sens produit : si le fond
livré doit un jour venir de notre pipeline plutôt que du PNG KP, c'est *ce* réglage qui
sera utilisé.

### 4.3 « Feature Map » d'OCAD vs notre mesure : pas de contradiction, mais une échelle

Le plan a raison de refuser la réouverture de la piste close. Précision utile : OCAD
travaille à **0,5 m de cellule avec 13–29 pts/m²** pour détecter des **objets** (pierres,
murs, troncs, clôtures) ; notre mesure porte sur des **densités de strate** à 1 m. Deux
questions différentes, deux échelles différentes — et une indication : notre grille 1 m est
probablement trop grossière pour la classe d'objets visée par OCAD.

### 4.4 `voxeldownsize` : la clôture est juste, la portée était plus étroite que le plan ne le dit

Cassini — le même outil que le plan cite en §7 — **utilise `filters.voxeldownsize`**
(`cell: 0.5`, `mode: first`) en amont de ses rasters de densité, avant toute classification.
Notre clôture O2 (« lave 32–50 % du signal ») est donc un argument contre *l'usage correctif
ciblé du recouvrement*, pas contre le sous-échantillonnage uniforme comme **régularisation** :
uniforme partout + seuils recalibrés derrière = facteur d'échelle absorbable. C'est
exactement l'argument de la Phase A, et cela renforce le §3.1 : si la borne du banc vertical
change, la densité change, et les seuils doivent suivre.

### 4.5 Sur l'affirmation « l'intensité répond directement à la question de la quintessence »

Demi-accord. L'intensité est le **seul canal spectral** disponible, et OCAD documente son
usage pour l'essence. Mais elle ne répond pas à la question « quelle gêne à la course » :
c'est un fond de carte (limites de peuplement), pas une classification. À porter au plan
comme tel : une **couche de fond supplémentaire** soumise au jugement cartographique, pas un
nouveau classeur.

---

## 5. Ordre retenu par cette revue

| Ordre | Étape | Coût | Sortie attendue |
|---|---|---|---|
| **0** | **Audit de l'ini KP effectif** (§2.4) + épinglage des valeurs | 10 min | les paramètres de production cessent d'être une hypothèse |
| **1** | **Banc vertical** B0–B4 (§3.1), 1 passe PDAL multi-sorties | ½ j | AUC conditionnelle > 0,4919 ? sinon le canal reste le plafond |
| **2** | **Ordre de généralisation** V5/V6 (§3.2), 0 PDAL | 1 h | le livrable actuel (médian sur teintes) est-il défendable ? |
| **3** | **Overlap / `DTM_MAKER`** (§3.3) | ½ j | l'artefact de bande est-il d'acquisition ? correction d'une ligne ou non |
| **4** | **Phase A — seuils par échantillons**, sur notre indice continu d'abord (§4.2) | 1 j | portabilité du réglage validée contre le témoin figé |
| **5** | **Phase B2 — intensité vs BD Forêt V2**, sur terrain à deux formations (§2.2) | ½ j | séparation feuillus/résineux : couche de fond oui/non |
| **6** | **Phase C — profil vertical** (inchangée, conditionnelle) | — | — |

Ce qui **ne change pas** par rapport au plan : les trois clôtures du §1 restent closes ; les
paramètres de production ne sont modifiés qu'après jugement sur planche ; l'injection des
polygones 406/408/410 dans l'`.omap` reste hors périmètre.

---

## 6. Ce que cette revue n'a pas pu vérifier

- **Les mesures des zones A/B/C/D** citées par le plan (`A 0,062 ≤ C 0,071 ≤ D 0,076`, le
  « R8 sans appel », les 32–50 % du `voxeldownsize`) : elles ne sont pas dans le dépôt. Elles
  sont donc prises pour acquises ici, sans contrôle indépendant.
- **Le wiki OCAD courant** (`LiDAR_Point_Cloud_Manager`) : les citations proviennent de
  versions indexées/archivées de la page (le site refuse les requêtes automatisées). Le
  contenu « NDVD / ±1 / Statistics / Overlap Points / Steinhauserwald » est cohérent entre
  plusieurs index, mais n'a pas été relu à la source en direct.
- **La fiche produit IGN « Nuages de points LiDAR »** (PDF, HTTP 403) : les éléments
  `DTM_MAKER`/`DSM_MAKER` et la classification « Version 5 » proviennent de l'actualité
  cartes.gouv.fr/geoservices de mars 2025, pas du descriptif de contenu complet.
- **La formule et les seuils de la version « modifiée » de la NDVD** utilisée par Trier pour
  la franchissabilité : l'article donne l'équation de la NDVD (§2, éq. 1) et le tableau de
  seuils (§2.2, tab. 5), mais la modification elle-même est décrite ailleurs dans l'article
  et n'a pas été lue intégralement.

---

## 7. Références

- **Trier, Ø. D. (2015).** *Automatic mapping of forest density from airborne lidar data.*
  Geodesy and Cartography 41(2), 49–65. DOI 10.3846/20296991.2015.1051342 (CC-BY).
  Éq. 1 (NDVD) ; §2 (bandes, noyau, **artefact de bandes de vol réduit par 0,2–2,0 m**) ;
  §2.1–2.2 (masque d'ouvert, **cascades morphologiques progressives 7-3-9-5-11-7**) ;
  §2.2 tab. 5 (**seuils dépendants de la densité d'impulsion**) ; §3 (taux par classe).
- **OCAD**, wiki *LiDAR Point Cloud Manager* : NDVD, seuils −1…+1, **Statistics**,
  cellule 1 m / noyau 5×5, bandes 0–1 m et 0–3 m, **Overlap Points from**, no-data en rouge,
  défauts optimisés pour Steinhauserwald / canton de Zurich.
- **OCAD**, blog 2024-07 (*Feature Map*) et 2026-06 (*Positioning and Mapping in the Field* :
  intensité = feuillus/résineux, Vegetation Base Map orientée franchissabilité).
- **Karttapullautin v2.12.1**, `src/vegetation.rs` (trois boucles, `top`, `aveg`,
  `pointvolumefactor`, médians appliqués à l'image de teintes), `src/config.rs`
  (défauts), `pullauta.default.ini`.
- **Cassini** (`github.com/NicoRio42/cassini`) : `src/lidar.rs` (PDAL, `voxeldownsize 0.5`,
  classes 3/4/5 par strate, rasters `count` 1 m), `src/vegetation.rs` (noyaux gaussiens
  r=2/σ=1 et r=4/σ=2, seuils 1/2/3, filtre min pour la végétation haute).
- **IGN** : actualité « Les premiers modèles numériques issus du programme LiDAR HD sont
  disponibles » (03/2025) — classification Version 5, attributs `DTM_MAKER`/`DSM_MAKER` ;
  BD Forêt V2 (32 postes, 0,5 ha, WFS `LANDCOVER.FORESTINVENTORY.V2`, Etalab).
- **Dépôt Lidar'O** : `docs/bilan_v0.md` (§5, §6.2, §7, §14, §15.1-4, réfutation n°15),
  `docs/test_intensite.md`, `docs/archive/CONSIGNE_intensite_406_v2.md`,
  `docs/archive/PLAN_vegetation_406.md`, `src/run_engine.py`, `.gitignore`.
