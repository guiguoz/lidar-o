# Vectoriser le raster Karttapullautin — protocole retenu

> **Statut :** protocole adopté, implémenté, démontré (2026-09-30).
> **S'applique à :** `src/kp_raster.py` (nouveau), `src/vegetation.py` (étape 10),
> `src/run_engine.py`, `main.py` (étapes vegetation/assemble), `config.yaml`.
> **Complète :** avenant n°02 §A (la question « KP expose-t-il une densité ? » y est
> répondue : non, mais il expose mieux — un raster de *classes* exact).
> **Ne remplace rien :** la chaîne PDAL/HAG reste disponible (`vegetation.source: pdal`).
> **Démo exécutable sans données :** `python scripts/diag/demo_vectorisation_kp.py`
> → figure `docs/images/demo_vectorisation_kp.png` + `work/demo/kp_vege_demo.omap`.

---

## 0. La décision, en une page

**Question posée :** « il y a de très nombreuses façons de vectoriser — laquelle pour
aboutir à un `.omap` à végétation modifiable ? »

**Réponse :** aucune des méthodes de vectorisation existantes n'est le bon outil, parce
que le problème n'est pas un problème de vectorisation. Trois faits, vérifiés dans le
source de Karttapullautin v2.12.1 (pas dans sa documentation) :

1. **KP ne produit aucun vecteur de végétation.** Ni DXF, ni shapefile, ni GeoJSON. Le
   fork `tjmsy/karttapullautin-veg-vector` (« WIP fork for vegetation vector export »)
   ne contient qu'un commit de README : personne n'a fait ce vecteur, pas même son auteur.
2. **Le « raster rendu » de KP n'est pas une image, c'est un raster de classes.**
   `vegetation.png` est un PNG **indexé** dont les indices de palette sont codés en dur
   dans `src/palette.rs` (`to_color()` : 1 = blanc, 3 = jaune, 16+i = vert i). Aucun
   dégradé, aucune anti-aliasing : le filtre médian de KP travaille sur les indices.
   En mode batch la palette est étendue en RGB, mais les couleurs restent **exactement**
   celles de la palette — il n'y a donc aucune couleur ambiguë à classifier.
3. **KP écrit déjà la généralisation dans ce raster.** `medianboxsize` (9 px) puis
   `medianboxsize2` (16 px) sur les indices de palette : c'est le geste « masses nettes,
   pas de confetti » que fait un cartographe, et il est déjà fait, à 1 px = 1 m.

D'où le protocole : **traduire les classes, pas interpréter des couleurs**, puis laisser
le reste du travail aux briques calibrées du dépôt.

| | avant | après |
|---|---|---|
| Végétation dans le `.omap` | image de fond (`vegetation.png` en template), rien à éditer | objets surfaciques ISOM 406/408/410, sélectionnables et déplaçables dans OOM |
| Classification | décalque humain à l'œil sur le template | exacte, par indice de palette (0 pixel ambigu) |
| Nouveau code de production | — | un pont raster→raster (`src/kp_raster.py`, ~350 lignes) et une étape de partition plane (`src/vegetation.py`, étape 10) |
| Généralisation, masque, `.omap`, QA | moteur existant | **inchangés**, réutilisés tels quels |
| Chaîne PDAL/HAG | source unique | source alternative (`vegetation.source: pdal`) |

Conformité à la règle directrice de l'avenant n°02 §0 : cette évolution **supprime une
étape** (le décalque manuel du vert), **n'ajoute aucune infrastructure** (pas de nouveau
vectoriseur, pas de nouvelle dépendance : rasterio est déjà dans l'image Docker) et
**réutilise quatre briques calibrées** (généralisation, masque, writer `.omap`, QA).

La seule nouveauté conceptuelle est imposée par le mot « modifiable » : une carte dont le
vert est un raster n'a aucune contrainte topologique ; une carte dont le vert est un
ensemble d'objets **en a une** — la partition plane (§4 É5). C'est l'unique changement
touchant les deux sources de végétation.

---

## 1. À quoi ressemble une carte de CO faite par un humain

### 1.1 Ce n'est pas une image du terrain, c'est un modèle de franchissabilité

L'ISOM 2017-2 définit le vert par la **vitesse de course**, jamais par la végétation :

| Code | Nom ISOM 2017-2 | Vitesse | Couleur | Aire mini | Largeur mini |
|---|---|---|---|---|---|
| 405 | Forest (forêt courable de référence) | ~100 % | blanc | 1×1 mm (15×15 m) pour une ouverture | 0,3 mm |
| 406 | Vegetation: slow running | 60–80 % | green 30 % | 1×1 mm (15×15 m) | 0,4 mm (6 m) |
| 408 | Vegetation: walk | 20–60 % | green 60 % | 0,7×0,7 mm (10,5 m) | 0,3 mm (4,5 m) |
| 410 | Vegetation: fight | < 20 % | green 100 % | 0,55×0,55 mm (8 m) | 0,25 mm (3,8 m) |

(footprints ISOM à 1:15 000 ; à 1:10 000, 1 mm² = 100 m² — c'est l'échelle du dépôt.)

Conséquences que tout protocole automatique doit encaisser :

- **Deux terrains de même densité peuvent porter des verts différents**, et inversement.
  Un seuil physique n'est jamais « vrai », il est **calibré** sur le terrain — c'est
  exactement ce que disent J. Ryyppö (guide *greenmapping* : itérer `pointvolumefactor`
  jusqu'à disparition des bandes de vol, puis placer les tons sur une zone témoin) et
  T. Mathisen (fichier `vegetasjon_facit.txt` de points témoins G/Y/W/DG/WS).
- **« If no part of the forest is easily runnable then no white should appear on the
  map »** (ISOM 405) : le blanc n'est pas « l'absence de vert », c'est une affirmation
  sur la course. Un raster qui ne verdit pas n'autorise pas à conclure « blanc ».
- Le vert KP mesure une **densité de retours LiDAR sous 2 m**, pas une vitesse. C'est un
  excellent *proxy* (le dépôt l'a mesuré sur Grimbosq), pas une vérité : feuillus d'été
  vs d'hiver, résineux, coupes récentes déplacent les tons. D'où la calibration par
  terrain (§4 É2) et le garde-fou de couverture (§4 É7).

### 1.2 Le vocabulaire est petit, et la règle humaine est discrète

Outre les quatre ci-dessus, l'ISOM offre 401/402 (découvert), 403/404 (ouvert rugueux),
407/409 (slow/walk **à bonne visibilité** — combinables ni avec 406 ni avec 408),
411 (infranchissable), 415/416 (limites franches, **lignes**), 417/418/419 (ponctuels).

La règle de généralisation humaine tient en une phrase de l'ISOM, répétée sous chaque
symbole : *« Smaller areas must either be left out, exaggerated or shown using symbol
X. »* C'est une **décision à trois issues**, pas un filtrage continu :

- **laisser tomber** (le sous-bois épars disparaît),
- **exagérer** (la tache trop petite devient lisible),
- **changer de symbole** (le fourré minuscule mais marquant devient 419, la limite de
  plantation devient 416).

Un algorithme ne fait naturellement que la première issue ; les deux autres relèvent du
jugement. Le protocole assume cette limite et la documente (§4 « reste à l'humain »).

Deux familles de symboles sont **structurellement hors de portée** du LiDAR :

- **407/409** (bonne visibilité) : le LiDAR mesure l'obstacle vertical, pas la vue
  horizontale sous couvert (ronces basses vs jeunes pousses hautes). Indiscernable.
- **416** (limite nette de végétation) : c'est une *ligne* que le cartographe pose quand
  la transition est franche et visible au sol (lisière de coupe, limite de plantation).
  Le raster la connaît en pixels, pas en intention.

### 1.3 La signature mesurable d'une carte humaine

Le dépôt sait déjà **mesurer** si une forme ressemble à celles d'un cartographe :
`scripts/measure_corpus.py` et `src/qa.py` produisent, par classe, couverture, nombre
d'objets, médiane des aires en mm², proportion sous 1 mm², compacité (4πA/P²), proportion
de polygones à trous, P/√A. Les cibles gelées dans `config.yaml → qa_targets` viennent de
la carte FFCO de Grimbosq (hull 323,8 ha) :

| | 406 | 408 | 410 |
|---|---|---|---|
| couverture | 19,3 % | 6,9 % | 8,0 % |
| n objets | 463 | 432 | 363 |
| médiane | 5,17 mm² | 2,31 mm² | 1,39 mm² |
| % < 1 mm² | 3,7 % | 13,4 % | 32,0 % |
| compacité méd. (406) | 0,663 | | |
| % avec trous (406) | 1,1 % | | |

Lire ces chiffres comme une **famille de formes**, pas comme des cibles à atteindre au
décimètre : un humain produit peu d'objets, compacts, presque sans trous — il fusionne
systématiquement ce que le capteur disperse. C'est le critère d'acceptation du protocole
(§4 É7) : une sortie qui sort de cette famille est ratée, même si elle « colle » au raster.

### 1.4 Ce qu'un humain ne laisse jamais dans un fichier éditable

- **deux verts qui se chevauchent** — à l'écran l'un masque l'autre selon l'ordre de
  dessin ; déplacer ou supprimer un polygone révèle un dessin incohérent dessous ;
- **un trou sous l'aire minimale** — une lucarne de 40 m² dans du 408 n'existe pas, elle
  est absorbée (le pipeline le fait déjà, `min_hole_area_m2`) ;
- **des slivers et des escaliers de pixels** — d'où DP + Chaikin, calibrés sur corpus ;
- **des objets orphelins minuscules** — `remove_isolated`, calibré.

Le premier point est nouveau : tant que le vert était un fond raster, les pixels se
recouvraient d'eux-mêmes sans que personne ne le voie. Il devient bloquant dès que la
végétation est éditable → étape 10 du moteur (§4 É5).

---

## 2. Ce que Karttapullautin produit réellement

Lecture du source Rust v2.12.1 (`src/palette.rs`, `src/vegetation.rs`, `src/process.rs`,
`src/merge.rs`), complétée par les sorties observées en Phase 0 (`docs/etat_existant.md`).

### 2.1 Sorties « végétation »

| Fichier | Quand | Contenu | Utilisable pour vectoriser ? |
|---|---|---|---|
| `temp/vegetation.png` | toujours | PNG **indexé** : indices de palette = classes | oui (indices) |
| `temp/greens.png`, `temp/yellow.png` | toujours | verts et jaunes séparés, indexés | oui |
| `{dalle}_vege.png` | mode batch | **RGB** : palette étendue par `to_rgb8()` puis overlay opaque sur blanc | oui (appariement exact) |
| `temp/greens_bit.png`, `yellow_bit.png`, `vegetation_bit.png` | `vege_bitmode=1` | niveaux de gris : **0 = blanc, 1 = jaune, 2+i = vert i** | **oui, idéal** |
| `{dalle}_vege_bit.png` + `.pgw` | batch + `vege_bitmode=1` | idem, pleine tuile, centré pixel | **oui, idéal** |
| `undergrowth*.png` | `vege_bitmode=1` | sous-bois — fonction morte en Rust v2.12.1 (mesuré Phase 0) | non |
| `out2.dxf`, `c2g.dxf`, `c3g.dxf`, `dotknolls.dxf`, `formlines.dxf` | toujours | relief **uniquement** | non (pas de vert) |

### 2.2 La palette est codée en dur — la classification est exacte

`PaletteColorEnum::to_color()` fixe les indices : `0` transparent, `1` blanc, `2` noir
(bâti), `3` jaune `(255,219,166)`, `4` bleu, `5` undergrowth `(64,121,0)`, **`16+i` =
vert i**. Les RGB des verts suivent, avec `N = len(greenshades)` **y compris les entrées
`99` désactivées** (le diviseur porte sur la longueur du paramètre, pas sur les teintes
atteignables) :

```
R = B = lightgreentone − lightgreentone/(N−1)·i        G = 254 − 74/(N−1)·i
```

Le ini par défaut du dépôt (`greenshades=0.2|0.35|0.5|0.7|1.3|2.6|4|99|99|99|99`,
`lightgreentone=160`) donne donc N=11 et des teintes atteignables i=0..6 — valeurs du
raster bit 2..8. `src/kp_raster.kp_green_rgb()` reproduit la formule ; les tests la
figent (`test_palette_reproduit_la_formule_rust`).

**Pourquoi c'est décisif :** vectoriser un bitmap ordinaire (CoVe, potrace, trace
d'Inkscape) commence par une *classification chromatique tolérante* — on choisit une
distance, on arbitre les pixels de bord. Ici il n'y a **aucun pixel de bord** : le filtre
médian de KP opère sur les indices, le rendu n'interpole jamais. Un pixel est une classe
ou n'appartient à aucune palette connue — et dans ce second cas `kp_raster` **refuse**
(garde-fou `pixels hors palette`), au lieu d'inventer.

### 2.3 Le raster est déjà généralisé, à 1 px = 1 m

`imggr1.median_filter(med/2, med/2)` puis `(med2/2, med2/2)` sur l'image **indexée** :
fenêtres 9×9 puis 17×17 px = 9 m puis 17 m. C'est ce qui transforme le confetti de
cellules de 3 m (`greendetectsize`) en masses suivables — le réglage `medianboxsize2=16`
a été validé par le dépôt (TEST A 2026-09). Géoréférencement : `.pgw` en **centres de
pixels** (`minx+0.5`, `maxy−0.5`), résolu 1,0 m — `kp_raster.tile_origin()` corrige le
demi-pixel.

### 2.4 Ce que KP ne produit pas

- aucun **float** continu de densité (mesuré Phase 0 : « KP ne produit que du PNG ») ;
- aucun **vecteur** de végétation (README officiel : les DXF sont le relief ; le fork
  veg-vector est une coquille vide) ;
- aucune distinction de **visibilité** (407/409) ni de **limite intentionnelle** (416).

---

## 3. Inventaire des méthodes, évaluées une par une

| Méthode | Ce qu'elle produit | Verdict | Raison |
|---|---|---|---|
| **CoVe** (intégré à OOM ≥ 0.9.2, né de l'issue #833) | polylignes vectorisées depuis un template raster (amincissement + Bézier) | **écarté** | conçu pour les *lignes* (courbes) ; une surface verte n'a pas de « ligne » à amincir ; aucun code ISOM, aucune topologie |
| **potrace / trace bitmap (Inkscape, GIMP)** | chemins binaires lissés | **écarté** | une seule classe à la fois, pas de géoréférencement, pas de trous attribués, pas de symboles ; le lissage n'est pas une généralisation CO |
| **`gdal_polygonize` seul** | un polygone par plage connexe de pixels | **nécessaire mais insuffisant** | démo : 557 objets, 35 295 sommets, 26 % sous 1 mm² sur 1 km² — exactement le confetti qu'un humain n'écrit jamais |
| **Graphe de frontières façon T. Mathisen** (segments de 2 m le long des changements de classe → polylignes jointes aux nœuds de degré 2 → low-pass à extrémités fixes → aires avec trous encodés DXF/OCAD) | vrais objets surfaciques à frontières **partagées** | **principe repris, code non repris** | l'algorithme est juste — c'est d'ailleurs pourquoi ses objets n'ont ni trous ni chevauchements — mais il réinvente la généralisation que le dépôt a calibrée sur cartes FFCO ; on garde son *invariant* (partition plane) plutôt que son implémentation |
| **OmapMaker** (Hjermstad, Chalmers 2025, Rust) | `.omap` complet depuis le LiDAR, seuils végétation 403/406/408/410 | **hors sujet ici** | concurrent de *toute* la chaîne, pas du raster KP ; déjà en Phase 0 bis (avenant 02 §A) ; l'évaluer reste pertinent, indépendamment |
| **Chaîne PDAL/HAG du dépôt** | raster classifié 85/170/255 | **conservée comme source alternative** | même contrat de sortie que le pont KP ; reste préférable là où KP est absent ou mal réglé |
| **Pont raster KP → raster classifié → moteur existant** (retenu) | raster classifié identique à celui de `process_hag.py`, puis objets `.omap` | **retenu** | classification exacte (§2.2), généralisation déjà présente dans le raster (§2.3), zéro nouvelle infrastructure, quatre briques calibrées réutilisées |

Le choix se résume ainsi : **le raster KP n'est pas une image à interpréter, c'est la
sortie d'un classifieur déjà généralisé**. Le « vectoriser » consiste à lui donner le
format du moteur de généralisation du dépôt, puis à respecter la contrainte qu'impose
l'édition humaine (partition plane). Tout le reste — CoVe, potrace, graphes de frontières
— résout un problème que KP a déjà résolu en amont.

---

## 4. Le protocole

```
out_kp_{terrain}/
  {dalle}_vege_bit.png (+ .pgw)      ← É0  KP avec vege_bitmode=1
  pullauta.ini                        ← relu pour connaître le run réel
        │  É1  lecture en classes, mosaïque sur les indices (jamais sur les couleurs)
        │  É2  teinte → code ISOM (table en config, calibrée par couverture)
        ▼
output/kp_vege_classified.tif         ← É3  uint8 DN 85/170/255, CRS terrain, bbox
        │  É4  CO Generalization Engine (src/vegetation.py, étapes 1–9 inchangées)
        │  É5  étape 10 : partition plane (NOUVEAU)
        ▼
output/vegetation.gpkg → vegetation_masked.gpkg   ← masque anthropique inchangé
        │  É6  src/omap_writer : couches veg_406/408/410 injectées en objets
        ▼
output/{terrain}.omap                   ← végétation MODIFIABLE + template de contrôle
        │  É7  QA : métriques « signature humaine » + contrôle visuel OOM
```

### É0 — faire écrire à KP son raster de classes

`vege_bitmode=1` dans le `pullauta.ini` généré (`src/run_engine._build_ini`, piloté par
`karttapullautin.vectorization.bitmode`). KP écrit alors `{dalle}_vege_bit.png`, niveaux
de gris `0/1/2+i` : plus aucune dépendance à `lightgreentone` ni à `greenshades`, donc
plus aucune palette à recalculer ni à voir dériver. Coût : un PNG par dalle.

*Repli :* si le répertoire ne contient que des `{dalle}_vege.png` RGB (runs antérieurs),
`kp_raster` recalcule la palette depuis le `pullauta.ini` **du run** (pas depuis la
config) et apparie exactement. Tout pixel non apparié → erreur explicite, jamais une
classe inventée.

### É1 — lire en classes, mosaïquer en classes

`src/kp_raster.load_tiles()` détecte la présentation **depuis le fichier** (bande unique
+ palette = indexé ; bande unique sans palette = raster bit ; 3-4 bandes = RGB) puis
ramène tout à la même sémantique `0/1/2+i`. `mosaic()` assemble les tuiles **sur les
valeurs de classe**.

Cela supprime un piège pré-existant : `main._merge_vege_tiles()` mosaïquait en RGB et
appliquait un remapping de ton `200 → lightgreentone` — remapping appliqué **une seconde
fois** aux tuiles que KP avait déjà rendues à 160 (le ini du run porte 160). Le template
ressortait plus sombre que la carte KP d'origine. Corrigé : le remapping ne s'applique que
si le ton voulu diffère du ton **réellement rendu**, lu dans le `pullauta.ini` du run.

Garde-fou hérité du bug de Port-en-Bessin : mosaïque disjointe de la bbox du terrain →
erreur (pas un raster vide silencieux).

### É2 — teinte → code ISOM, calibrée par couverture

`karttapullautin.vectorization.shade_to_isom` (table *valeur du raster bit → code ISOM*,
`0` = teinte volontairement abandonnée). Valeurs livrées : 2→blanc, 3-4→406, 5-6→408,
7-8→410.

**La calibration ne se fait pas à l'œil sur une couleur.** Elle se fait par couverture :

```
python -m src.kp_raster report out_kp_<terrain>
```

affiche, pour chaque teinte, sa surface en ha et sa part du vert total ; on place les
coupures là où les cumuls rejoignent les cibles `qa_targets` mesurées sur la carte
humaine du terrain (Grimbosq : 19,3 / 6,9 / 8,0 %). C'est exactement la démarche du guide
*greenmapping* de Ryyppö, rendue reproductible et mesurable. La démo synthétique applique
ce réglage et obtient 19,9 / 3,0 / 2,4 ha pour 100 ha avant généralisation.

Le **jaune KP est ignoré** (`yellow_to: 0`, toute autre valeur est refusée) : KP marque
en jaune tout ce qui est bas — coupe rase, culture, lande, herbe — sans distinguer 401 de
403, et le découvert est déjà fourni par BD TOPO `zone_de_vegetation` / OSM `landuse` via
`mask_vegetation.build_fill_layers()`. Le tri 401/403 est un jugement de terrain.

### É3 — le contrat du moteur, pas un format de plus

Sortie : GeoTIFF uint8, DN `85/170/255` → 406/408/410, `0` = pas de végétation, CRS du
terrain, recadré sur la bbox — **le contrat exact de `scripts/process_hag.py`**. C'est ce
qui rend tout l'aval gratuit : `run_pipeline`, masque, assemblage, QA ne savent pas d'où
vient le raster. Aucune chaîne parallèle n'est créée (l'anti-pattern que l'avenant 02 §0
aurait refusé).

### É4 — le moteur de généralisation, inchangé

Étapes 1 à 9 de `src/vegetation.py` (dissolve, trous, petits polygones, fusion par
proximité, trous post-fusion, isolés, DP 2 m, Chaikin ×2, isthmes) : calibrées sur
corpus, mesurées, non retouchées. Seule modification technique : l'import `osgeo` est
descendu dans `stage_polygonize`, pour que le reste du moteur — Shapely/GeoPandas pur —
soit importable et testable sans GDAL (les tests sautaient jusque-là :
`pytest.skip("GDAL non disponible")`).

### É5 — partition plane : la contrainte née de l'éditabilité (nouvelle étape 10)

`stage_coverage_partition`, en **dernier** : les classes sont ordonnées par densité
(410 > 408 > 406) et chaque classe est amputée de tout ce qui appartient à plus dense
qu'elle. Résultat : chaque point du terrain appartient à **au plus une** surface verte.

Pourquoi en dernier : DP et Chaikin travaillent polygone par polygone et réintroduisent
des micro-chevauchements ; poser la partition avant ne servirait à rien. Pourquoi pas
`shapely.coverage_simplify` (GEOS ≥ 3.12, que le Dockerfile exige déjà) : c'est la piste
suivante — simplifier la couverture **entière** en préservant les frontières partagées —
mais elle n'est pas calibrée ; l'étape 10 garantit l'invariant sans changer le rendu.

Chiffres de la démo (1 km²) : chevauchements **0,372 ha → 0,000 ha** (amputé :
406 −0,228 ha, 408 −0,143 ha) ; témoin `planar_partition: false` : 0,372 ha conservés.

Désactivable (`generalization.profiles.<p>.planar_partition: false`) pour reproduire le
comportement antérieur — mais alors le `.omap` n'est plus proprement éditable.

### É6 — assemblage : le vert devient des objets

`step_assemble` injecte désormais `build_veg_layers(vegetation_masked.gpkg)` — fonction
qui existait déjà et n'était plus appelée — en **premières** couches (les écrans verts
passent sous le relief et l'anthropique, ordre ISOM). Le template `vegetation.png` reste
disponible comme calque de contrôle pendant la reprise humaine, piloté par
`karttapullautin.vectorization.keep_template` (le passer à `false` pour la carte finale :
sinon le PNG se superpose aux objets et alourdit le `.omap`).

### É7 — contrôle : la famille de formes, pas la fidélité au raster

- métriques `src/qa.py` / `measure_corpus.py` contre `qa_targets` (couverture, n,
  médiane mm², % < 1 mm², compacité, % à trous) ;
- le log de `coverage_partition` (chevauchements avant/après) doit finir à 0 ;
- contrôle visuel dans OOM : template à 50 % sous les objets — les masses vectorielles
  doivent *recouvrir* le rendu KP, pas le contredire ;
- sur terrain réel : les 2-3 vérités-terrain du spike Phase 1 restent l'arbitre final
  (avenant 02 §B : contrôle de plausibilité, pas corpus-vérité).

### Ce que le protocole ne fait pas — reste à l'humain, dans OOM

| Reste | Pourquoi |
|---|---|
| 407 / 409 (bonne visibilité) | la visibilité sous couvert n'est pas dans le LiDAR |
| 416 (limite nette de végétation) | une ligne posée par intention, pas par pixel |
| 419 (élément végétation proéminent) | ponctuel, défini « significatif » = jugement |
| 401 / 403 (découvert vs ouvert rugueux) | le jaune KP ne les distingue pas |
| exagérer une tache trop petite mais marquante | issue « exaggerated » de la règle ISOM |
| valider la franchissabilité sur le terrain | le vert KP est une densité, pas une vitesse |

---

## 5. Risques, pièges constatés, garde-fous

| Risque / piège | Garde-fou |
|---|---|
| Le vert KP dérive avec la saison, l'essence, la densité de vol | calibration par terrain via `report` ; presets (`dense_summer`, `sparse_winter`) déjà en config ; contrôle de couverture à l'étape 7 |
| Coutures entre tuiles : KP filtre le médian **par tuile** | visible sur sorties réelles ; KP fournit `pngmergevege` (fusion après filtrage) — à mesurer avant de filtrer après mosaïque (le faire changerait la calibration) |
| Palette qui dérive si `lightgreentone`/`greenshades` changent | mode bit (É0) supprime le risque ; en mode rgb, la palette est relue dans le `pullauta.ini` du run et tout pixel hors palette **fait échouer** le pont |
| **Bug corrigé** : double remapping du ton dans `_merge_vege_tiles` (ini à 160 + remap 200→160) | le remapping ne s'applique que si ton voulu ≠ ton rendu |
| **Bug corrigé** : `src/run_engine._build_ini` ne compilait pas (concaténation implicite de f-strings cassée par les `+ (…) if … else ""`) → sans `pullauta.ini` de base, aucun run KP possible | bloc réécrit en liste de lignes ; testé sur les deux chemins (avec/sans base) |
| Chev. résiduels entre classes après fusion par proximité | étape 10, log avant/après, test `test_partition_plane_supprime_les_chevauchements` |
| Trois tests en échec **pré-existants** sur `main` (`test_init_terrain` check, `test_omap_writer` georef : attendu 450 000 vs 449 000 dans l'asset) | non touchés — à statuer séparément : c'est l'attendu du test ou l'asset qui a bougé, pas le code de ce chantier |

---

## 6. Utilisation

```bash
# 1. Relief + raster de classes (écrit vege_bitmode=1 dans le ini généré)
python main.py relief <terrain> --tiles-dir LIDAR/

# 2. Calibrer le mapping teinte → ISOM sur CE terrain
python -m src.kp_raster report out_kp_<terrain>

# 3. Végétation → masque → .omap (la source kp saute pdal + process_hag)
python main.py run <terrain> --from-step vegetation

# 4. Reprendre dans OpenOrienteering Mapper : les verts sont des objets
#    (template KP à 50 % dessous tant que keep_template: true)

# Sans dalles ni binaire KP : démonstration complète du protocole
python scripts/diag/demo_vectorisation_kp.py
```

Revenir à la chaîne physique : `vegetation.source: pdal` dans `config.yaml` — les étapes
`pdal` et `process_hag` se réactivent d'elles-mêmes, le reste est identique.

---

## Annexe A — sémantique exacte des valeurs

Raster bit KP (`{dalle}_vege_bit.png`, `vegetation_bit.png`) :

| Valeur | Signification | Devenu |
|---|---|---|
| 0 | fond / blanc | rien (405 implicite) |
| 1 | jaune | ignoré (401 vient de BD TOPO/OSM) |
| 2 | vert 1, le plus clair | blanc par défaut (`shade_to_isom[2] = 0`) |
| 3–4 | verts 2–3 | 406 (DN 85) |
| 5–6 | verts 4–5 | 408 (DN 170) |
| 7–8 | verts 6–7, les plus foncés | 410 (DN 255) |

Indices du PNG indexé (`temp/vegetation.png`) : `1` blanc, `3` jaune, `16+i` vert i,
`2` noir bâti, `4` bleu eau, `5` undergrowth (ces trois derniers → blancs : ce n'est pas
de la végétation KP).

## Annexe B — la démo, chiffres

1 km² synthétique dans l'emprise de Grimbosq, 4 tuiles façon batch KP, échelle 1:10 000
(`scripts/diag/demo_vectorisation_kp.py`, figure `docs/images/demo_vectorisation_kp.png`) :

| | objets | sommets | 406 | 408 | 410 | méd. mm² | % < 1 mm² | chevauchements |
|---|---|---|---|---|---|---|---|---|
| raster KP (bit) | — | — | 19,9 ha | 3,0 ha | 2,4 ha | — | — | — |
| polygonisé brut | 557 | 35 295 | 19,9 ha | 3,0 ha | 2,4 ha | 7,3 | 26,3 % | 0 |
| après étapes 1–9 | 290 | 14 334 | 19,5 ha | 2,8 ha | 2,4 ha | 13,7 | 13,3 % | **0,372 ha** |
| protocole complet | 290 | 14 502 | 19,3 ha | 2,7 ha | 2,4 ha | 13,7 | 13,3 % | **0,000 ha** |

Sortie : `work/demo/kp_vege_demo.omap`, 290 objets surface sur 3 calques, symboles ISOM
résolus dans le gabarit, géoréférencé Lambert-93 (contrôle aller-retour des coordonnées
dans la démo). La médiane des aires et le taux de petits polygones restent au-dessus des
cibles FFCO : le terrain synthétique est plus grumeleux qu'une forêt réelle — c'est le
rôle du corpus de calibration de le dire sur données réelles, pas celui de la démo.
