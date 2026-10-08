# Pistes — symboles ISOM supplémentaires (pierres, limites de végétation, végétation basse)

> Question posée (2026-10-08) : « pourrait-on envisager d'avoir plus de symboles ISOM ?
> pierre ? limite de végétation ? végétation basse ? autres ? Qu'apporteraient ces
> améliorations du raster concrètement ? »
>
> Réponse en quatre temps : ce que la chaîne produit **déjà** ; famille par famille ce que le
> LiDAR HD peut et ne peut pas donner ; ce que cela changerait **concrètement** dans le
> workflow ; et le protocole qui trancherait, avec un critère écrit d'avance.
>
> Statut des affirmations : ÉTABLI (mesuré dans le dépôt), SOURCE (doc externe vérifiée),
> INTERPRÉTÉ (raisonnement), NON TESTÉ.

---

## 0. Réponse courte

1. **Le trou de couverture est petit et précis.** Le dépôt déclare « manuel » exactement
   quatre familles : **rochers/blocs (204–210)**, **115**, **419**, **531**
   (`docs/etat_existant.md`). Tout le reste du squelette est déjà produit : courbes 101/102,
   courbes de forme 103, buttes/fosses 109/111, falaises 201/202, eau 301–304, ouvert/forêt
   401/403/405 (BD TOPO), routier/bâti 502–523 (BD TOPO), fond végétation KP.
2. **Ce qu'OCAD appelle « Feature Map » n'est pas une couche de symboles.** C'est une *image
   d'indices* à 0,5 m calculée sur les points **non-sol** — pour repérer et **positionner**,
   pas pour dessiner (OCAD écrit lui-même que le résultat « doit être traité avec prudence »
   et sert d'« indice des endroits à vérifier en terrain »). C'est reproductible chez nous en
   **une passe PDAL** (patron L0 de `docs/pistes_raster_multipasses.md` : 1 lecture →
   N writers chaînés).
3. **Limite de végétation (416) : la voie raster est déjà mesurée, et elle échoue.** La
   vectorisation du rendu KP est suspendue sur deux conditions non atteintes, dont une
   longueur médiane de composante de **19 m** — inférieure au minimum du symbole 416 lui-même
   (**2,0 mm = 20 m à 1:10 000**). Les voies qui restent (intensité, BD Forêt V2) donnent des
   **limites de peuplement**, pas des 416.
4. **Végétation basse (401–404) : déjà couverte là où elle compte** (ortho + BD TOPO en zone
   ouverte). Le LiDAR n'ajoute que sous couvert, avec le risque documenté par OCAD de
   confondre branches basses, buissons et objets. Le pendant KP (couche jaune) est
   **quasi-vide sur Grimbosq** — mesuré, bilan §15.1.5.
5. **Le vrai apport concret d'une telle couche est le temps de terrain et le positionnement**,
   pas un livrable automatique. ISOM exige qu'un bloc dessiné soit « immédiatement
   identifiable sur le terrain » (204 : hauteur > 1 m) : aucune détection LiDAR ne peut le
   certifier. Donc : **couche-indice séparée, éteinte par défaut, jamais injectée comme
   symbole** — le contraire exact du précédent 406/408/410 (injectés puis retirés deux fois).

---

## 1. Ce qui est produit aujourd'hui, et par quoi

| Famille ISOM | Symboles | Source actuelle | État |
|---|---|---|---|
| Relief | 101 contour, 102 maîtresse, 103 courbe de forme, 109 butte, 111 fosse | Karttapullautin → DXF → CRT | ÉTABLI (`etat_existant.md` §4) |
| Falaises | 201 impassable, 202 falaise | Karttapullautin (`c3g.dxf`, `c2g.dxf`) | ÉTABLI |
| Eau | 301–304, 313 | BD TOPO (tronçon/surface hydro) | ÉTABLI |
| Ouvert / forêt | 401, 403, 405 | BD TOPO `zone_de_vegetation` + ortho | ÉTABLI |
| Végétation franchissabilité | 406, 408, 410 | pipeline HAG | **HORS LIVRABLE** (qualité insuffisante, bilan §3.4) |
| Végétation bonne visibilité | 407, 409 | pipeline HAG | NON GÉNÉRÉ |
| Routier / bâti | 502–505, 515, 516, 521, 523 | BD TOPO | ÉTABLI |
| Fond de traçage | — | rendu KP `vegetation.png` (opacité 50 %) | ÉTABLI (livrable recommandé) |
| **Rochers / blocs** | **204–210** | **—** | **MANUEL (déclaré)** |
| Relief remarquable | 115 | — | MANUEL |
| Végétation remarquable | 419 | — | MANUEL |
| Anthropique remarquable | 531 | BD TOPO / manuel | partiel |

**Lecture** : la question « plus de symboles » ne porte donc pas sur 25 symboles, elle porte
sur **une famille** (les rochers) et **une frontière** (416), plus quelques cas isolés.

---

## 2. Famille par famille

### 2.1 Pierres, blocs, sols rocheux — 204, 205, 206, 207, 208, 209, 210–212

**Contraintes ISOM 2017-2** (SOURCE, spec) : 204 = bloc distinct, **hauteur > 1 m**,
« immédiatement identifiable sur le terrain », empreinte 6 m ; 205 = gros bloc, **> 2 m**,
empreinte 9 m ; 206 = bloc gigantesque ou pilier, en surface, minimum 1 mm × 1 mm
(15 m × 15 m à 1:15 000) ; 207/208/209 = groupes et champs de blocs ; 210–212 = sols
rocailleux réduisant la course (210 : 60–80 % de la vitesse normale).

**Ce que le LiDAR HD peut faire** (ÉTABLI, données du dépôt) : les retours non-sol à faible
hauteur sont déjà dans les dalles ; nos densités mesurées sur Grimbosq sont de **41 à
85 pts/m²** (bilan, note multi-passes §3), soit **1,4 à 6,5 fois** les exemples publiés par
OCAD (13–29 pts/m²). À 0,5 m de cellule, cela suffit pour *voir* un objet — pas pour
*l'identifier*.

**Le mode d'échec documenté** (SOURCE, OCAD, exemple Lillehammer) : à 10 pts/m² et 0,75 m de
cellule, « de nombreux petits arbres et buissons ont des branches jusqu'au sol ; il est
difficile de distinguer de gros cailloux des arbres ou des buttes ». Nos forêts sont des
feuillus à sous-bois : c'est le terrain le plus défavorable au discriminateur
caillou / branche / souche.

**Apport concret** (INTERPRÉTÉ) :
- *Positionnement* — un mur, un tronc, un bloc donnent un point de repère exact sous couvert,
  là où l'ortho ne montre rien. C'est **la** difficulté du terrain en feuillus.
- *Complétude* — évite d'oublier un champ de blocs ou un muret en forêt profonde.
- *Pas* la certitude : la hauteur (> 1 m) et l'identifiabilité ne se déduisent pas d'un
  nuage à 0,5 m. La couche reste un indice à vérifier.

**Verdict** : **à tester** — c'est le meilleur candidat, et le moins cher (une passe).
Instructif : OCAD lui-même ne le vend pas comme un générateur de symboles.

### 2.2 Limite de végétation — 416

**Contraintes ISOM** (SOURCE) : ligne, minimum 5 points = **2,0 mm** (30 m à 1:15 000,
**20 m à 1:10 000**) ; deux implémentations possibles (points noirs ou tirets vert foncé),
**une seule à la fois** par carte — c'est un choix de cartographe. Le symbole ne doit pas
être confondu avec les points du 210–212.

**Trois voies, trois statuts** :

| Voie | Ce qu'on obtient | Statut mesuré |
|---|---|---|
| Vectoriser le rendu KP | des polylignes de bord de vert | **SUSPENDUE** : longueur médiane 19 m < seuil 32 m, couverture ≤ 10 m = 57,9 % < 64,5 % ; et 19 m < minimum 416 (20 m à 1:10 000) |
| Intensité / BD Forêt V2 | limites de **peuplement** (feuillus/résineux), ≥ 0,5 ha | piste ouverte (Phase B2 de `docs/revue_plan_signaux_lidar.md`) — **ne produit pas des 416** |
| Améliorer le raster lui-même | un fond que le cartographe suit plus fidèlement | pistes ouvertes (banc vertical, overlap) — c'est le levier réel pour les 406/408/410 **et** leurs limites |

**Apport concret** : les 416 vecteurs « prêts à l'emploi » ne sont pas au bout de ces voies.
Le gain réel est (a) un **fond plus juste** (moins de corrections à la main) et (b) une
**information d'essence** pour décider où vérifier. Les deux se mesurent ; le 416 automatique,
non.

### 2.3 Végétation basse, terrain ouvert — 401, 402, 403, 404

**Déjà couvert, et plutôt mieux** : en zone ouverte, l'ortho et la BD TOPO donnent la
situation ; le LiDAR HD n'a pas d'avantage compétitif là où l'on voit le sol depuis le ciel.
Son seul apport est **sous couvert** : trouées, layons, zones herbacées à l'ombre de la
canopée, que le pipeline actuel ne voit pas (bande HAG démarrant à 0,3 m, normalisation
p95 locale).

**Côté KP** : le rendu « végétation basse/jaune » existe en interne (`imgye2`, piloté par
`yellowheight` / `yellowthresold`), mais `_undergrowth.png` est **quasi-vide sur Grimbosq**
(ÉTABLI, bilan §15.1.5 — mesuré dans un autre but, mais la mesure est là). Avant de coder
quoi que ce soit : **regarder les PNG jaunes du dernier run** (coût nul).

**Apport concret** : marginal. Risque : un jaune automatique mal placé se voit à l'impression
et se confond avec les 401/403 tracés à la main.

### 2.4 Autres candidats

| Symbole | Signal possible | Apport | Verdict |
|---|---|---|---|
| 105 levée de terre, 106 levée ruinée (murets) | **le plus fiable** : linéaire + vertical, visible en non-sol 0–1,5 m (exemple Jura d'OCAD : « les murs deviennent clairement visibles ») | repérage + tracé de linéaires en forêt (murets normands fréquents) ; min. ISOM 105 : hauteur 1 m, longueur 20 m à 1:10 000 | **à tester avec les pierres** (même passe) |
| 113 sol irrégulier | densité des buttes/fosses KP déjà produites | graine possible depuis `dotknolls.dxf` | NON TESTÉ, faible priorité |
| 210–212 sol rocheux | idem pierres, en surfacique | utile en terrain rocheux ; Grimbosq n'est pas ce terrain | dépend du terrain |
| 308/310 marais | plat + végétation basse + proximité hydro | BD TOPO + terrain font mieux ; faible priorité en feuillus normands | faible priorité |
| 109/111 buttes/fosses | **déjà produits** par KP | rien à ajouter | ÉTABLI |

---

## 3. Ce que ça apporterait concrètement

### 3.1 Deux usages à ne pas confondre

| | Couche-indice (façon Feature Map) | Symbole livré |
|---|---|---|
| But | repérer, positionner, **cibler le terrain** | figurer sur la carte de course |
| Exigence | aucune (une erreur = une vérification inutile) | ISOM : identifiable au sol, hauteur minimale, dimensions minimales |
| Qui valide | le cartographe, en terrain | le cartographe, en terrain |
| Coût d'une erreur | temps perdu | **erreur de carte** (équité sportive) |
| Où ça va | fichier séparé, éteint par défaut | le `.omap` du livrable |

Toute la question « plus de symboles » se joue dans cette distinction. Ce qui est réaliste en
LiDAR HD aujourd'hui, c'est **des indices** ; ce qui reste humain, c'est **les symboles**.

### 3.2 Les chiffres qui bornent le gain

- **Résolution** : les indices se lisent à **0,5 m** (réglage OCAD constant dans ses 5
  exemples). Notre chaîne travaille à **1 m** et le fond KP par blocs de **3 m**. Une couche
  d'objets est donc un **produit nouveau**, pas un réglage du raster existant.
- **Densité** : nos dalles (41–85 pts/m²) sont **au-dessus** des exemples OCAD (13–29) et
  **loin** du cas d'échec (10 pts/m²). Interprété : le mode d'échec « branches » reste le
  risque principal, pas la densité.
- **Volume** : la couche végétation actuelle pèse **2 225 objets** ; le garde-fou du projet
  pour l'`.omap` est **~30 000 objets** (`CONSIGNE_relief_dxf_v2.md`). Une couche d'indices
  doit vivre **hors** du `.omap` (ou dans une couche éteinte), sinon elle reproduit le
  précédent 406/408/410 : injecté, retiré, deux fois.
- **Coût marginal faible** : les patrons sont déjà là — 1 lecture PDAL → N writers chaînés
  (`docs/pistes_raster_multipasses.md` §L0) ; un writer 0,5 m de plus ne coûte pas une
  seconde lecture des dalles.

### 3.3 Ce qui se mesure, ce qui ne se mesure pas

**Se mesure** : nombre de candidats par hectare ; taux de vrais objets sur un échantillon
vérifié (ortho, puis terrain) ; temps de terrain économisé (chronométré sur une séance) ;
comblement de trous de l'ortho (zones sous canopée où l'ortho ne montre rien).

**Ne se mesure pas** : « le cartographe aurait-il trouvé ce bloc sans l'indice ? » — question
contrefactuelle. Elle se remplace par un test A/B sur une séance de terrain, journal à
l'appui.

---

## 4. Protocole de décision (½ à 1 journée, si on veut trancher)

**Étape 1 — production (½ journée, aucune donnée nouvelle).** Sur les dalles Grimbosq déjà en
cache, une passe PDAL par dalle, sorties chaînées :
- `feature_0_2.tif` : non-sol, [0,0 ; 2,0] m, cellule 0,5 m (recette OCAD « pierres ») ;
- `feature_0_1_5.tif` : non-sol, [0,0 ; 1,5] m (recette « murs », exemple Jura) ;
- `feature_0_0_5.tif` : non-sol, [0,0 ; 0,5] m (recette « troncs », positionnement).
Rendu à 1:10 000, juxtaposé à l'ortho et au fond KP.

**Étape 2 — lecture (½ journée).** Compter les candidats/ha et leur taille ; sur un
échantillon de ~30 candidats : combien sont des objets réels identifiables (vérification
ortho, puis terrain si possible) ; combien d'objets connus (murets, blocs) l'ortho ne montre
pas.

**Critère, à figer AVANT de mesurer** (suggestion) : la couche est retenue comme
*couche-indice* si, sur l'échantillon, **au moins la moitié** des candidats correspondent à un
objet réel identifiable, **et** au moins une famille d'objets utiles (muret, tronc, bloc) est
détectée dans des zones où ni l'ortho ni la BD TOPO ne l'indiquent. Sinon : piste classée,
documentée, non retenue.

**Ce qu'on ne fait pas** : l'injecter dans le `.omap` ; en déduire des symboles 204/206 ;
l'appliquer avant d'avoir validé le critère.

---

## 5. Ce qu'on ne promet pas

- Un générateur de symboles 204/205/206 : la hauteur (> 1 m, > 2 m) et
  l'« identifiabilité au sol » ne se lisent pas dans un nuage à 0,5 m.
- Un 416 automatique : la voie raster est mesurée en échec (19 m médian), et le choix entre
  les deux implémentations du symbole reste humain.
- Une mesure d'équité : aucune couche automatique ne remplace la vérification terrain qui
  fonde la validité sportive d'une carte.

---

## 6. Références

- **ISOM 2017-2** (spec, révision 6 janv. 2024) : 204/205/206 (hauteurs et empreintes),
  210–212, 105/106 (levées de terre), 113, 308/310, 416 (minimum 2,0 mm, deux
  implémentations), 401–404.
- **OCAD**, blog 2024-07 *Feature Map – Get more out of your LiDAR Data* et wiki
  *DEM Import Wizard* / *Using Airborne Laserscanning Data for Orienteering Base Map
  Generation* : recette (points non-sol reclacifiés, seuils 0,0–0,5/1,5/2,0 m, cellule 0,5 m,
  13–29 pts/m²), avertissement d'usage (« hint »), cas Lillehammer sans résultat
  satisfaisant ; crédit Jeff Teutsch.
- **Dépôt** : `docs/etat_existant.md` (§4, sources attendues par code CRT),
  `docs/bilan_v0.md` (§3.4 recall, §12 vectorisation suspendue, §15.1.5 couche KP quasi-vide),
  `docs/pistes_raster_multipasses.md` (patron L0), `docs/revue_plan_signaux_lidar.md`
  (Phases A/B), `docs/archive/CONSIGNE_relief_dxf_v2.md` (garde-fou 30 000 objets).
