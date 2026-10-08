# Pistes « multi-passes » pour le raster de végétation

> Note d'exploration — 2026-10-08. **Aucune mesure n'a été exécutée pour cette note** :
> l'environnement de rédaction n'a ni PDAL ni dalle LiDAR. Tous les chiffres cités sont
> déjà établis ailleurs dans le dépôt : `docs/bilan_v0.md` §4–§7, `docs/portabilite.md`
> (« Diagnostic banding »), `docs/etat_existant.md`, et la mesure ci-dessous du code
> source de Karttapullautin v2.12.1 (dépôt amont, `src/vegetation.rs`, `pullauta.default.ini`).

---

## 0. Réponse courte

1. **Le « nombre de passes » est un vrai levier, mais pas celui qu'on croit.** Une seconde
   passe n'améliore le résultat que si elle apporte une information que la première n'avait
   pas. En encodage vidéo, la passe 1 lit *tout le film* pour allouer le débit — c'est de
   l'information globale. Empiler deux fois le même filtre sur le même champ ne fait que
   lisser, et chez nous **le lissage est saturé** (bilan §6.3 : 0,5 m → 2 m → 5 m ne lève
   pas le plafond ; §5 : changer le dénominateur du ratio NRD donne Δ ≤ 0,0006).

2. **Karttapullautin est déjà un algorithme multi-passes** — trois boucles successives sur
   le nuage, dont la dernière n'utilise que des statistiques globales (commentaire du code :
   `// compute global average firsthit`). Il possède deux ingrédients que notre pipeline
   n'a pas : la **hauteur de toit par bloc** (`top`) et la **densité moyenne globale**
   (`aveg`, qui alimente `pointvolumefactor`). Les utilisateurs de KP en parlent, mais sous
   un autre nom : *green stripes* et « équilibrage du vert ».

3. **Le seul artefact déjà mesuré chez nous qui appelle réellement une seconde passe est le
   banding d'acquisition** (bilan §7) : la bande de recouvrement de 3 lignes de vol a un
   ratio HAG gonflé (contraste résiduel 0,024 ; 84,6 pts/m² dans la bande contre 41,2 hors
   bande). Le test censé trancher n'a jamais été exécuté — `docs/portabilite.md` conclut
   « Pas de correction dans ce run » et le volet intra-cellule du bilan §7 est déclaré
   **NON TESTÉ**.

4. **OCAD ne travaille pas sur un rendu multi-passes.** Son raster végétation est un NDVD
   sur cellule 1 m / noyau 5×5, en deux bandes (0–1 m sous-bois, 0–3 m végétation), à seuils
   **calibrés par échantillonnage** (fonction *Statistics*) et filtrable (« the filter option
   generalizes the raster map »). Sa R&D récente porte sur les objets proches du sol
   (*Feature Map*), l'intensité (feuillus/résineux), l'extraction automatique d'objets
   vectoriels et la lisibilité ISOM. Ce sont ces idées-là qu'il y a à reprendre, pas un
   schéma de passes.

---

## 1. « Passes » recouvre quatre mécanismes différents

| # | Mécanisme | Équivalent exact | État chez Lidar'O |
|---|-----------|------------------|-------------------|
| **P1** | Empiler N fois le même opérateur sur le même champ | 2e médian, 3e gaussienne | 1 gaussienne + 1 médian. L'**espace ordre/cascade n'a jamais été balayé** → levier L1 |
| **P2** | Passe 1 = statistiques globales → passe 2 décide | normalisation p95, seuils globaux | **Partiel** : `p95_local` est déjà une 2e passe de normalisation. La densité moyenne globale de KP (`aveg`) manque |
| **P3** | Passe 1 = carte structurelle → passe 2 conditionnée par elle | hauteur de toit (CHM), fiabilité par cellule | **Absent.** KP le fait (`top` entre dans la condition de zone et le terme `topweight`) → levier L3 |
| **P4** | Plusieurs vues du même sol fusionnées | looks de lignes de vol (`PointSourceId`), angles de scan | **Absent.** Le `filters.merge` actuel fusionne tous les looks en une moyenne pondérée par le nombre de points — involontaire et non contrôlée → levier L2 |

Les leviers utiles sont P2 (déjà à moitié fait), P3 et P4. P1 n'est utile que par son
*ordre*, qui n'a pas été testé.

---

## 2. Pourquoi une seconde passe « du même type » ne peut pas aider

C'est le point à ne pas rater, parce qu'il évite un faux chantier.

En vidéo, la passe 1 analyse l'intégralité du film pour répartir un budget global ; la passe 2
encode avec cette connaissance. Le gain vient de l'**information ajoutée**, pas du nombre de
passes. Appliqué au raster : une deuxième passe qui ne voit que le raster déjà produit (et
qui ne lisse que davantage) est informationnellement vide.

Or c'est exactement la famille de leviers déjà fermée chez nous :

- ratio HAG/total vs NRD → **Δ ≤ 0,0006** (bilan §5) ;
- changement de σ gaussien → saturé (§6.3) ;
- fenêtres verticales alternatives → la tranche basse [0,3–1,5 m] est *moins* informative
  que la tranche haute [1,5–3,0 m] (§6.2) ;
- agrégation 0,5 → 2 → 5 m → +0,004 AUC, plafond conditionnel inchangé (§6.3) ;
- seuils T9, hystérésis, ouverture, fermeture, fd, min_area → 9 leviers testés sur la forme.

**Conclusion opérationnelle** : une seconde passe ne vaut la peine d'être écrite que si elle
introduit une variable absente aujourd'hui. Il y en a exactement trois dans la donnée :

1. la **géométrie d'acquisition** (ligne de vol, angle, numéro de retour) — présente dans le
   LAS, jetée par `filters.merge` ;
2. la **hauteur de toit** (contexte vertical du peuplement) — calculable, jamais calculée ;
3. le **calibrage par échantillon géoréférencé** (seuils internes aux strates) — la voie OCAD.

---

## 3. Le seul artefact mesuré qui appelle une seconde passe : le banding

### 3.1 Ce qui est établi

| Mesure | Valeur | Source |
|---|---|---|
| Densité dans la bande de recouvrement | 84,6 pts/m² | bilan §7 |
| Densité hors bande | 41,2 pts/m² | bilan §7 |
| Cellules à 3+ sources dans la bande | 83,2 % (vs 2,8 % hors bande) | bilan §7 |
| Contraste résiduel du ratio HAG après normalisation | **0,024** | bilan §7 |
| Corrélation angle × ratio (tous pixels) | \|ρ\| ≤ 0,12 | bilan §7 |

Le contraste résiduel de 0,024 est le point clé : **le ratio ne retire pas tout l'effet de
densité.** Or l'indice OCAD (NDVD) et la plupart des indices de littérature sont aussi des
ratios — ils héritent du même biais.

### 3.2 Les deux hypothèses, et le test qui les sépare

- **H-A (géométrie)** : les passes supplémentaires éclairent le sous-bois sous d'autres
  angles → plus de retours dans la bande [0,3–3,0 m] → le *ratio lui-même* est gonflé
  localement.
- **H-B (covariation spatiale)** : la bande tombe sur autre chose (drainage, lisière, sol nu)
  — bilan §7 : « hypothèse plausible, non démontrée ».

Le test décisif est déjà identifié dans `docs/portabilite.md` (« Contrôle `PointSourceId` —
méthode décisive ») et n'a **jamais été exécuté**. Il tient en deux temps :

1. rasteriser l'occupation par ligne de vol (nombre de looks par cellule) et comparer
   *bande vs hors bande* ;
2. calculer le ratio **par look** dans les mêmes cellules, puis le comparer au ratio poolé.

Lecture :

| Observation | Interprétation | Action |
|---|---|---|
| Ratio par look stable, écart produit par la pondération | H-A | fusion robuste (médiane de looks) — l'artefact doit tomber |
| Ratio par look divergent (le look de bord voit plus vert) | H-B + effet angulaire réel | correction angle-dépendante (type Beer-Lambert), pas une fusion |
| Aucun des deux (ratio par look ≈ poolé partout) | La bande n'est pas un artefact de ratio | fermer le dossier banding |

### 3.3 Pourquoi le test précédent n'a rien conclu

Bilan §7, verbatim : *« le filtre utilisé sélectionnait les cellules sur total_count plutôt que
band_count — les cellules retenues avaient band_count médian = 0. Le test n'a pas testé
l'hypothèse angulaire sur les cellules végétées. **NON TESTÉ** sur cette population. »*
Le nouveau test doit stratifier sur la densité **de la bande**, pas sur le total.

---

## 4. Protocoles, dans l'ordre de coût

### L0 — Prérequis de coût : une lecture, N sorties *(aucun effet qualité)*

Aujourd'hui chaque produit raster est une passe PDAL complète : `density_hag`, `total_count`,
`count_below`, `band_low`, `band_mid` → **4 à 5 relectures** des dalles, chacune repassant
par `filters.merge` + `filters.hag_nn` (count=8). C'est le poste de temps dominant du run.

PDAL sait faire mieux depuis 2.7 : `filters.assign` crée des dimensions
(`BandFlag = 0` puis `BandFlag = 1 WHERE HeightAboveGround >= 0.3 && HeightAboveGround <= 3.0`
— attention, `filters.range` traite `[0.3:3.0]` comme **fermé des deux côtés**, un `<=` est
donc requis pour l'équivalence stricte),
et **plusieurs writers peuvent être chaînés** dans un même pipeline
(`Reader -> Writer -> Writer`, autorisé par PDAL ; en revanche un pipeline **ne peut pas
brancher** vers plusieurs sorties parallèles). Chaque writer voit les mêmes points et écrit
sa propre statistique sur sa propre dimension :

```
readers → merge → hag_nn → assign(W_band, W_below, W_low, W_mid)
        → writers.gdal[dim=W_band,  output_type=["mean","count"], filename=band.tif]
        → writers.gdal[dim=W_below, output_type=["mean"],           filename=below.tif]
        → writers.gdal[dim=W_low,   output_type=["mean"],           filename=band_low.tif]
        → writers.gdal[dim=W_mid,   output_type=["mean"],           filename=band_mid.tif]
```

`mean(flag) × count` (les deux bandes de `band.tif`) redonne **exactement** le compte dans la
bande — sans changer ni la résolution, ni le rayon/`window_size` du writer, ni le nodata. Il
faut juste une étape numpy de 3 lignes en tête de `process_hag.py`. Ne pas passer à
`binmode: true` « pour faire propre » : le rayon par défaut actuel (≈ 0,71 m pour une cellule
de 1 m) est inscrit dans les chiffres de référence, le changer invaliderait la comparaison.

- Gain attendu : le coût PDAL passe de ~4–5 décodages à 1 (×3–4 sur cette étape).
- Contrainte : validation obligatoire par comparaison raster à raster avec les sorties
  actuelles (tolérance : aucun point d'écart) **avant** toute expérience qualité.
- Raison de le faire : sans lui, chaque levier L2/L3 ajoute 20–40 min de PDAL par variante.

### L1 — Ordre et cascade du post-traitement *(0 passe PDAL en plus, 1 h)*

Ordre de production actuel (`scripts/process_hag.py`) :

```
ratio → gaussienne(σ=1 m) → médiane(9 m) → normalisation p95_local → seuils [0,20 / 0,45 / 0,85]
```

Tout ce qui suit la gaussienne est **non linéaire** (médiane, percentile local, seuillage) :
l'ordre n'est donc pas neutre, et il n'a jamais été testé. Variantes :

| Réf. | Variante | Question posée |
|---|---|---|
| V0 | gauss → médian (production) | témoin |
| V1 | médian → gauss | la médiane en premier retire le mouchetage avant lissage : contours plus stables ? |
| V2 | médian(5) → médian(5) | cascade de deux petites passes au lieu d'une grande — c'est **exactement ce que fait KP** (« two rounds », `medianboxsize` puis `medianboxsize2`) |
| V3 | gauss → médian → médian | ajouter une passe : gain ou simple érosion des petites structures ? |
| V4 | normaliser **avant** de lisser | le p95_local actuel s'applique sur un champ déjà lissé (ordre rarement questionné) |

Script : `scripts/diag/sweep_ordre_lissage.py` (pur numpy/scipy, aucun PDAL).

- **Go** : compacité médiane ↑, %trous ↓, %<1 mm² stable ou ↓, surface 406 non effondrée,
  et gain visible sur au moins deux des trois classes.
- **No-go** : gain uniquement sur la compacité *ou* perte de couverture > 6 pp.

### L2 — Fusion multi-looks par ligne de vol *(1 lecture PDAL en plus, ~2 h)* — **le candidat principal**

Pipeline (PDAL ≥ 2.7, une seule lecture) :

```json
[
  "dalle_*.copc.laz", "…",
  {"type": "filters.merge"},
  {"type": "filters.hag_nn", "count": 8},
  {"type": "filters.assign", "value": ["BandFlag = 0"]},
  {"type": "filters.assign", "value": ["BandFlag = 1 WHERE HeightAboveGround >= 0.3 && HeightAboveGround <= 3.0"]},
  {"type": "filters.sort", "dimension": "PointSourceId"},
  {"type": "filters.groupby", "dimension": "PointSourceId"},
  {"type": "writers.gdal", "filename": "look_#.tif", "resolution": 1.0,
   "dimension": "BandFlag", "output_type": ["mean", "count"],
   "data_type": "float32", "nodata": -1}
]
```

`filters.groupby` crée une vue par ligne de vol ; le `#` dans le nom de fichier fait écrire un
GeoTIFF par vue. On obtient, par look : la fraction de retours dans la bande (`mean` du flag)
et le nombre de points contribuant à la cellule (`count`), avec **les mêmes réglages de writer
que la production** (rayon par défaut) pour que le « poolé » reconstruit soit comparable au
`density_hag.tif` existant.

Fusion (numpy) :

- **poolée** (comportement actuel) = Σ(bande) / Σ(total) = moyenne des fractions pondérée par les counts ;
- **fusionnée** = médiane des fractions de look, restreinte aux looks avec `count ≥ n_min`
  (proposé : 4).

Puis rejouer la chaîne L1/L0 (`diag_multilook.py` réutilise σ/médian/p95/seuils de
`config.yaml`) et comparer les deux sorties.

- **Go** : contraste bande/hors bande ramené sous ~0,005, classes 406/408/410 stables
  (±10 % de surface), aucun nouveau trou.
- **No-go** : contraste inchangé (→ la bande est réelle, la fermer comme question) ou les
  surfaces de classe bougent de plus de 20 % sans gain mesurable.
- Garde-fous habituels : recall FFCO par classe, `max%406` (percolation).

### L3 — Conditionnement par la hauteur de toit *(1–2 lectures PDAL, 1 j)*

C'est la transposition directe de KP (voir §5.1) et le seul levier qui touche à la nature du
signal plutôt qu'à sa mise en forme. Deux faits convergent :

- bilan §6.2 : la tranche haute [1,5–3,0 m] sépare mieux que la tranche basse — donc le
  signal n'est pas la franchissabilité au sol ;
- KP ne regarde jamais une bande absolue : ses poids de zone dépendent de `top` (toit du bloc)
  et son intensité de vert mélange un terme de canopée (`topweight × highit`).

Protocole : une lecture produisant (a) un **CHM** = `max(HAG)` par cellule (`writers.gdal`
`output_type: max`, dimension `HeightAboveGround`) et (b) 3–4 comptes de bandes HAG
(0,3–1,3 / 1,3–3,0 / 3,0–5,0 m). Puis, en numpy : seuils **internes aux strates de toit**
(petit/demi/grand bois), au lieu d'un seuil unique global. C'est aussi là que se branchent
les idées OCAD : deux bandes 0–1 m / 0–3 m, noyau 5×5 explicite, et surtout **seuils
calibrés par échantillonnage** plutôt que par sweep global.

- **Go** : la confusion 406→408 (§3.2 du bilan : 77 % du 406 part en 408) baisse, et
  `%<1 mm²` ne se dégrade pas.
- **No-go** : les seuils par strate dégénèrent (trop peu de cellules par strate à Grimbosq).

---

## 5. État de l'art — ce que font réellement les autres

### 5.1 Karttapullautin : trois boucles, deux statistiques globales

Lecture du code amont (`src/vegetation.rs`, `makevege`) :

| Boucle | Entrée | Produit | Remarque |
|---|---|---|---|
| 1 | points | `top` (hauteur max par bloc), `yhit`/`noyhit` sur grille 3 m | pass 1 = pure accumulation |
| 2 | points | `firsthit`, `ghit`, `greenhit`, `highit` | dépend de `top` → commentaire dans le code : *« we cannot combine the two processing loops into one »* |
| 3 | blocs (pas de points) | rendu jaune + vert | calcule `aveg`, la **densité moyenne globale** |

Valeur de vert de KP :

```
valeur = greenhit/(ghit+greenhit+1)
       × (1 − topweight + topweight × highit/(ghit+greenhit+highit+1))
       × (1 − pointvolumefactor × firsthit_local_5x5_min / aveg) ^ pointvolumeexponent
```

Trois éléments à retenir :

1. **`top` (toit)** conditionne à la fois les zones de hauteur (`zone low|high|roof|factor`) et
   la sensibilité (`thresold roof_low|roof_high|ratio`) — c'est un vrai P3.
2. **`aveg`** est une statistique globale : `pointvolumefactor` est *le* correctif officiel du
   recouvrement de lignes de vol. Le fichier `pullauta.default.ini` dit littéralement :
   *« areas where scanning lines overlap we have two or three times bigger point density.
   That may make those areas more or less green. Use these parameters to balance it. »*
   Valeur par défaut 0,1 ; le guide de Jarkko recommande de monter vers 0,35 (plage 0–0,5) en
   itérant « jusqu'à ce que le vert soit équilibré ».
3. **`min` de `firsthit` sur 5×5 blocs** : KP prend la valeur *la plus faible* du voisinage —
   un choix de robustesse, pas un lissage. Nous n'avons aucun équivalent.

Côté utilisateurs : la question n'est jamais posée comme « combien de passes » mais comme
« pourquoi j'ai des bandes vertes » (**green stripes**, documenté avec illustration dans le
guide de vegetation mapping de Jarkko Ryyppö). Le workflow d'itération existe en natif :
`pullauta makevege` puis `pullauta` recalcule **seulement** la végétation sans refaire les
courbes — c'est la seule « passe » que KP expose à l'utilisateur.

### 5.2 Terje Mathisen (outil alternatif, le plus avancé de la communauté)

Deux étages assumés : (1) classification par blocs 2×2 m contre un **référentiel de placettes**
(10–30 patchs de référence relevés sur le terrain, un par classe de vert/blanc/jaune),
(2) **passe de vote majoritaire** centre-pondéré sur le résultat. Sortie vectorisée
(`veg2dxf.crt`). Il mentionne aussi des relances multiples de `lasground_new` avec paramètres
ajustés. Comparaison honnête : c'est un P3/P4 avec calibrage supervisé — plus puissant, mais
il déplace le problème (il faut des placettes).

### 5.3 OCAD

- Algorithme publié (wiki *LiDAR Point Cloud Manager*, section *Raster Map*) : **cellule 1 m,
  noyau 5×5 m, indice NDVD**, seuils entre −1,0 et +1,0, **bande sous-bois 0–1 m** et
  **bande végétation 0–3 m**, seuils calculés « avec des échantillons » via la fonction
  *Statistics*, « the filter option generalizes the raster map », zones sans données
  affichées en rouge. (Doc historique OCAD 12 ; les valeurs exactes de la version courante
  n'ont pas pu être relues — le wiki bloque les requêtes automatisées.)
- Produits (blog 2026-06) : courbes lissées/non lissées, hillshading, **Feature Map** (objets
  proches du sol : pierres, murs, troncs), intensité (feuillus/résineux), végétation en
  hauteur, et **Vegetation Base Map « focus more on the runability »**.
- Recherche en cours, dans leurs propres mots : *« classifying vegetation is a big task […]
  we believe that the Vegetation Base Map will become more and more important in the
  future »*, et côté développement : extraction automatique d'objets de végétation et de
  terrain, contrôle de lisibilité ISOM 2017.
- **Aucune publication OCAD sur un rendu multi-passes.** Leur réponse au plafond du signal
  n'est pas « plus de passes » mais « **seuils calibrés par échantillonnage** + deux bandes
  séparées + généralisation optionnelle ».

### 5.4 Littérature LiDAR (pourquoi le banding est structurel)

- Le **banding** (variations périodiques de densité le long des lignes de vol) a trois causes
  documentées : vitesse avion variable non compensée par le scanner, recouvrement des
  fauchées, désalignement vertical des lignes (effet moiré/corduroy). Conséquence : **tout
  indice de densité brute hérite de la géométrie d'acquisition**.
- Le recouvrement latéral des fauchées (30 % recommandé, 50 % courant) est *volontaire* :
  il augmente la densité et **« capture from different angles … a greater opportunity to
  capture more points beneath heavy vegetation »** — c'est exactement notre bande §7.
- La normalisation par la densité (comme `pointvolumefactor`) ou par look est la réponse
  standard ; l'alternative est l'inversion physique (gap fraction / Beer-Lambert) qui
  modélise l'angle — c'est la voie L2, branche H-B.

---

## 6. Décision proposée

| Ordre | Levier | Coût | Script | Décision attendue |
|---|---|---|---|---|
| 1 | **L1** ordre/cascade | 1 h, 0 PDAL | `scripts/diag/sweep_ordre_lissage.py` | fermer ou promouvoir un nouvel ordre |
| 2 | **L2** multi-looks | 2 h, 1 PDAL | `scripts/diag/diag_multilook.py` | trancher H-A / H-B sur le banding |
| 3 | **L0** 1 lecture → N sorties | ½ j | `scripts/run_terrain.py` | réduire le coût des variantes |
| 4 | **L3** toit + strates | 1 j, 1–2 PDAL | à écrire après L2 | n'engager que si L1/L2 ont montré un gain |

**Ce qu'il ne faut pas faire** :

- ajouter un 3e médian « pour voir » — c'est P1, déjà saturé, et KP a déjà la cascade ;
- ré-ouvrir les 9 leviers fermés (seuils, σ, hystérésis, NRD) ;
- engager un classifieur supervisé (voie Terje) avant que L2 ait tranché la question
  d'acquisition : si le banding est un artefact d'acquisition, aucun classifieur ne le
  corrigera.

**Question tranchée par cette note** : parmi les trois mécanismes « passe 2 » disponibles,
un seul (L2) est adossé à un artefact déjà mesuré dans ce dépôt. C'est celui-là qu'il faut
écrire d'abord ; L1 est gratuit et doit être fait en parallèle.

---

## Annexe A — Pourquoi la 2-pass vidéo n'est pas transposable telle quelle

| | Vidéo 2-pass | Notre raster |
|---|---|---|
| Objet de la passe 1 | tout le film | tout le terrain (déjà : c'est ce que fait le run complet) |
| Ce qui est appris | distribution du débit | distribution de densité/ratio (p95_local, seuils) |
| Ce que la passe 2 ajoute | l'allocation | rien de plus — sauf si on lui donne une variable nouvelle (look, toit) |
| Coût | ×2 | ×2 par relecture PDAL (~20–40 min) |

La transposition correcte n'est donc pas « faire deux fois la même chose », c'est
« **faire lire une fois pour décider, puis décider une deuxième fois avec la vue d'ensemble** ».
`p95_local` est déjà cette idée, mal exploitée : il est *local*, donc il ne corrige pas un
biais *global* d'acquisition — le rôle qu'`aveg` joue chez KP.

## Annexe B — Références

- KP amont : `github.com/karttapullautin/karttapullautin` — `src/vegetation.rs`
  (`makevege`, boucles 1–3), `pullauta.default.ini` (`pointvolumefactor`, `zone1..3`,
  `thresold1..5`, `medianboxsize*`).
- Guide de vegetation mapping de Jarkko Ryyppö : `routegadget.net/karttapullautin/greenmapping.pdf`
  (green stripes, `pointvolumefactor` 0,15 → 0,35, itération des `greenshades`).
- Thèse (theseus.fi, Harald Joachim, 2019) : §3.6.1 « Balansering av punktdensiteten »
  (même correction, plage 0–0,5, puis rognage `las2las`).
- Attackpoint : fils « Lidar and vegetation mapping » (densité proche-sol 0–2 m, noyau 10 m,
  classement ground/low/medium/high, référentiel de placettes puis **second filtre
  majoritaire**), « Lidar mapping batch process » (Terje Mathisen), « Veg or png to dxf for
  OCAD ? » (vecteur `veg2dxf`, relances `lasground_new`).
- OCAD : wiki *LiDAR Point Cloud Manager* (NDVD, cellule 1 m, noyau 5×5, seuils −1…+1,
  bandes 0–1 m et 0–3 m, *Statistics*), wiki *Using Airborne Laserscanning Data for
  Orienteering Base Map Generation*, blog 2026-06 *How OCAD Helps you With Positioning and
  Mapping in the Field*, blog 2024-07 *Feature Map*.
- Banding / densité : « Point Density Variations in Airborne Lidar Point Clouds » (2023),
  tableau des causes et symptômes ; GeoCue, *Flight Planning – LIDAR* (recouvrement latéral
  30–50 %, intérêt des angles multiples sous canopée).
