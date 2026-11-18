# Bilan V0 — Ovector : pipeline CO depuis LiDAR IGN HD

> Document de référence autonome. Terrain principal : forêt de Grimbosq (Calvados, France),
> feuillus, 6 tuiles IGN LiDAR HD, hull FFCO 324 ha. Campagne menée de 2026-07 à 2026-09.
> Les chiffres de classification proviennent de la config figée au 2026-08-15 : σ=1,0,
> mode=ratio, p95_local, seuils T=[0,20, 0,45, 0,85], min_area 406=100/408=100/410=75 m².

---

## État du projet

| Axe | État |
|---|---|
| DIAGNOSTIC HAG simple | ÉTABLI — TERMINÉ |
| CLASSIFICATION 406/408/410 | SUSPENDUE (branche HAG) — REPRISE via vectorisation KP (PLAN 3) |
| WORKFLOW KP + FOND OCAD | RETENU |
| TEMPLATE OMAP | FONCTIONNEL |
| VECTORISATION VÉGÉTATION | SUSPENDUE — _vege mbs2=16 mesuré, critère non atteint |
| DOMAINE | FORÊTS NORMANDES CIBLÉES |

---

## 1. Objectif initial

L'objectif initial du projet était d'exploiter les données LiDAR IGN HD pour aider à produire
automatiquement les zones de végétation CO en classes 406 (sous-bois léger), 408 (marche) et
410 (progression difficile).

L'objectif pratique était de produire une **information utile au cartographe**, pas seulement
une classification statistiquement correcte. Un résultat est utile s'il permet au cartographe
de gagner du temps sur le tracé ou la vérification des limites de végétation à l'échelle
d'usage (1:10 000).

---

## 2. Méthode initiale

Le modèle testé était volontairement simple :

```
LiDAR IGN HD
  ↓
ratio HAG = count[0,3–3,0 m] / total_count  (par cellule 1 m × 1 m)
  ↓
lissage gaussien σ
  ↓
seuillage [T406, T408, T410]
  ↓
zones 406 / 408 / 410
```

Hypothèse sous-jacente : la densité de retours dans la tranche verticale [0,3–3,0 m] —
correspondant à la strate arbustive et aux premiers mètres de sous-étage — est un indicateur
suffisant pour distinguer les niveaux de franchissabilité CO.

---

## 3. Résultats qui ont fermé la piste du modèle simple

### 3.1 Insensibilité au seuil T406

Sur Grimbosq, doubler le seuil T406 de 0,20 à 0,40 ne récupère que 1,6 point de non-végétation
correctement classée :

| T406 | Non-végétation correctement classée |
|---|---|
| 0,20 | 40,6 % |
| 0,40 | 42,2 % |

**ÉTABLI.** La distribution HAG des faux positifs est indiscernable de celle des vrais
non-végétation — monter le seuil ne peut pas les séparer. Ce n'est pas un problème de
calibration du seuil.

### 3.2 Matrice de confusion complète

Mesurée pixel à pixel sur le raster lissé (density_hag.tif, σ=1,0, sans masque BD TOPO,
5 997 395 pixels valides, Grimbosq). Chaque cellule = % des pixels de la classe référence
(ligne) classés dans la classe pipeline (colonne).

|  | **pipe nonveg** | **pipe 406** | **pipe 408** | **pipe 410** |
|---|---|---|---|---|
| **ref 406** (84,7 ha) | 0,91 % | **5,29 %** | 77,24 % | 16,56 % |
| **ref 408** (28,4 ha) | 0,92 % | 3,84 % | **54,39 %** | 40,85 % |
| **ref 410** (19,1 ha) | 1,26 % | 9,36 % | 49,86 % | **39,52 %** |
| **ref nonveg** (471,8 ha) | **40,37 %** | 4,21 % | 41,20 % | 14,22 % |

Lecture principale :
- 77 % de la végétation 406 est classée en 408 — la confusion principale est entre 406 et 408.
- Seulement 5,3 % de ref 406 est classé en 406 (la diagonale 406 est la plus faible).
- 39,5 % de ref 410 est classé en 410 — le mieux discriminé, mais encore insuffisant.
- 59,6 % des pixels non-végétation sont classés à tort en végétation.

### 3.3 Indicateurs globaux

| Indicateur | Valeur |
|---|---|
| **Sensibilité** (recall détection végétation) | **99,04 %** |
| **Spécificité** (recall non-végétation) | **40,37 %** |
| **Faux verts** (parmi la référence non-végétation) | **59,63 %** |
| **Précision** (quand le pipe dit végétation, c'est vrai) | **32,11 %** |

**Domaine de validité :** Grimbosq, config σ=1,0 / p95_local / T=[0,20, 0,45, 0,85], sans
masque BD TOPO. Le masque BD TOPO ajoute ~8,6 pp de non-végétation correctement classée
(routes, bâtiments) — la précision effective est légèrement supérieure en pratique.

### 3.4 Recall par classe (config figée 2026-08-15)

Deux métriques distinctes, deux questions distinctes :

| Classe ISOM | Recall détection (any-class) | Recall classe exacte | Surface FFCO |
|---|---|---|---|
| **406** sous-bois léger | **35 %** | **28 %** | 86,6 ha |
| **408** marche | **61 %** | **26 %** | 27,1 ha |
| **410** progression difficile | **82 %** | **48 %** | 19,2 ha |

- **Recall détection** : fraction de la surface FFCO couverte par *n'importe quelle* classe pipeline.
- **Recall classe exacte** : fraction couverte par la *bonne* classe.

---

## 4. AUC et disparition du signal continu

**ÉTABLI** (exp1_7, exp1_7bis — Grimbosq, ratio HAG/total) :

| Condition | AUC (veg vs nonveg) | n_veg | n_nonveg |
|---|---|---|---|
| Tous pixels | **0,6837** | 1 279 788 | 4 717 607 |
| Signal > 0 | **0,4919** | 1 254 239 | 2 844 690 |
| Signal > 0,05 | **0,4849** | 1 233 129 | 2 761 238 |

Le pouvoir discriminant apparent de l'AUC globale vient principalement de la distinction
zéro / non-zéro. Lorsque les cellules nulles sont retirées, le ratio continu devient proche
du hasard (AUC ≈ 0,49). La valeur absolue du signal HAG n'est pas informative une fois
qu'on sait que la végétation est présente.

**AUC inter-classes** (tous pixels, HAG brut) :

| Comparaison | AUC |
|---|---|
| 406 vs 410 | **0,5665** |
| 406 vs 408 | **0,6026** |
| 408 vs 410 | **0,4807** |

La frontière 408/410 est quasi-aléatoire (AUC 0,48). La séparabilité 406/408 est légèrement
meilleure mais insuffisante pour une classification fiable.

---

## 5. NRD — levier fermé

**ÉTABLI** (exp1_8) :

| Filtre | AUC HAG | AUC NRD | Δ |
|---|---|---|---|
| Tous pixels | 0,6837 | 0,6834 | −0,0003 |
| > 0 | 0,4919 | 0,4913 | −0,0005 |
| > 0,01 | 0,4914 | 0,4909 | −0,0005 |
| > 0,05 | 0,4849 | 0,4843 | −0,0006 |

L'écart maximal est **0,0006**. HAG/total et NRD (= band/(band+below)) sont pratiquement
identiques. Changer le dénominateur dans cette famille de ratios ne constitue pas un levier.

---

## 6. Verticalité, fenêtres et agrégation

### 6.1 Sigma des hauteurs HAG

**ÉTABLI** (exp1_9) :
- Seulement **4,99 % des pixels** ont un sigma calculable avec n≥3 retours dans [0,3–3,0 m].
  Le sigma est structurellement indisponible sur la majorité du terrain.
- Sur les pixels calculables (n≥3), AUC sigma veg vs nonveg = **0,546** — signal faible.
- AUC sigma inter-classes : 406 vs 410 = 0,534 ; 406 vs 408 = 0,515 ; 408 vs 410 = 0,519.
  Ces valeurs sont proches de 0,5 — quasi-aléatoire.

**INTERPRÉTÉ** : la corrélation sigma vs densité de retours est ρ=0,128 (Spearman). Le sigma
est essentiellement lié à la quantité de retours, pas à la structure de la végétation.

**Conclusion ÉTABLIE** : le sigma vertical apporte seulement un signal faible et ne couvre
qu'une fraction minoritaire du terrain.

### 6.2 Fenêtres verticales alternatives

**ÉTABLI** (exp1_10) :

| Fenêtre | Rôle | AUC veg vs nonveg (n≥3) | Couverture n≥3 |
|---|---|---|---|
| [0,3 – 3,0 m] | baseline | 0,546 | 4,99 % |
| [0,3 – 1,5 m] | W1 — strate basse | 0,511 | 1,42 % |
| [1,5 – 3,0 m] | WC — contrôle strate haute | **0,546** | 2,95 % |

**Résultat WC :** la strate haute [1,5–3,0 m] sépare aussi bien que la plage complète
[0,3–3,0 m] (AUC identiques à 0,546) et **mieux** que la strate basse W1 [0,3–1,5 m]
(AUC 0,511). Si le signal capturé était la franchissabilité au sol, la strate basse
devrait être la plus informative — ce n'est pas le cas.

**ÉTABLI :** l'hypothèse que la tranche 0,3–1,5 m capte spécifiquement les obstacles à
la marche est infirmée par ce contrôle. Le résidu de signal dans la fenêtre sigma provient
pour l'essentiel de la strate haute [1,5–3,0 m], qui n'est pas directement liée à la
franchissabilité.

Aucune fenêtre ne fournit une discrimination suffisante — le problème fondamental est dans
la valeur absolue du signal, pas dans le choix de la tranche verticale.

### 6.3 Agrégation spatiale

**ÉTABLI** (exp2_0, résolution native 0,5 m, Grimbosq) :

| Résolution | AUC globale | AUC conditionnelle (>0) | Observation visuelle |
|---|---|---|---|
| 0,5 m (natif) | 0,684 | 0,492 | couronnes, mouchetage |
| 2 m | 0,688 | 0,509 | encore granuleux |
| 5 m | ~0,69 | ~0,52 | structures cohérentes |
| 10 m | — | — | trop grossier |
| 20 m | — | — | trop blocqué |

L'agrégation spatiale améliore la cohérence visuelle mais dégrade progressivement la précision
des contours. Le gain en AUC globale est marginal (+0,004 à 2 m). L'AUC conditionnelle passe
de 0,492 à 0,509 — la valeur absolue du plafond n'est pas levée.

Ces résultats ne prouvent pas qu'une résolution précise est optimale — ils documentent
le compromis bruit/échelle sur ce terrain.

---

## 7. Acquisition et angle d'incidence

**ÉTABLI** (exp2_1) :

Une **bande de forte densité** est visible dans la fenêtre étudiée (Grimbosq) : densité
dans la bande 84,6 pts/m² contre 41,2 pts/m² hors bande. Cette bande correspond au triple
recouvrement de 3 passages d'acquisition (83,2 % des cellules à 3+ sources dans la bande
vs 2,8 % hors bande). L'artefact persiste après division par total_count (contraste résiduel
dans le ratio : 0,024).

**Corrélations globales angle / ratio** (exp2_2, volet 1, n = 32 000 à 508 000) :

| Groupe | ρ Spearman (angle vs ratio) |
|---|---|
| n_sources = 1 | 0,048 |
| n_sources = 2 | −0,012 |
| n_sources ≥ 3 | −0,121 |

Les corrélations globales avec l'angle sont faibles (|ρ| ≤ 0,12).

**Volet intra-cellule** (exp2_2, volet 3) : le filtre utilisé sélectionnait les cellules sur
total_count plutôt que band_count — les cellules retenues avaient band_count médian = 0.
Le test n'a pas testé l'hypothèse angulaire sur les cellules végétées. **NON TESTÉ** sur cette
population.

**Formulation finale ÉTABLIE** : Aucun effet angulaire global suffisamment net n'a été
détecté ; le volet intra-cellule n'a pas permis de conclure.

L'explication de la bande par covariation spatiale reste une hypothèse plausible, non
démontrée. L'existence d'un effet d'acquisition ne peut pas être écartée.

---

## 8. Correction majeure — sorties Karttapullautin mesurées

> Cette section corrige une erreur de mesure dans l'expérience 2.3.

L'expérience 2.3 avait utilisé `_undergrowth.png` comme représentant du rendu KP pour
mesurer la qualité des frontières. **C'était une erreur** : `_undergrowth.png` est quasi-vide
dans KP v2.12.1 Rust (0,0 % de pixels colorés, confirmé par exp2_3bis). Ce fait était
documenté dans `docs/etat_existant.md` §7 (Phase 1 spike) mais non relu au moment
de l'expérience.

**Résultats exp2_3 par produit** (Grimbosq, référence = contour FFCO 131 056 m) :

| Produit | Distance médiane | Couverture ≤ 10 m | Composantes |
|---|---|---|---|
| KP `_undergrowth` | 15,1 m | 0,4 % | 21 |
| KP `_vege` | 9,4 m | 86,0 % | 3 662 |
| KP `base` | 9,5 m | 88,9 % | 3 144 |

**`_vege`** : ratio_utile = 0,517 — la moitié des frontières KP sont proches de la
référence FFCO selon cette métrique.

**`base`** : ratio_utile artificiellement > 1, dû à une composante gigantesque couvrant
l'ensemble du terrain. La dalle principale n'est pas un bon objet pour la comparaison
directe des frontières.

**Conclusion ÉTABLIE** : L'ancienne conclusion sur `_undergrowth` ne caractérisait pas
KP dans son ensemble. `_vege` présente une forte proximité spatiale avec les limites de
référence selon notre métrique de couverture à ≤ 10 m. Cette mesure porte sur des
frontières pixel issues d'aplats raster, pas sur des contours cartographiques tracés —
elle ne signifie pas que KP détecte les limites de façon générale.

---

## 9. Recentrage du produit

### 9.1 Avant / après

```
AVANT                               APRÈS
─────────────────────────────────   ──────────────────────────────────
classification automatique          fond végétation KP
  406 / 408 / 410                     +
       ↓                            objets vectoriels Lidar'O
polygones dans l'OMAP                        ↓
                                           OMAP
                                             ↓
                                       OCAD / OOM
                                             ↓
                                  tracé manuel de la végétation
```

Ce changement correspond au workflow réellement utilisé par les cartographes : le fond LiDAR
sert de décalque, le cartographe délimite lui-même les zones de franchissabilité.

### 9.2 Pourquoi la classification automatique est abandonnée dans le livrable actuel

Trois contraintes cumulatives :

1. **Plafond du signal HAG** : AUC conditionnelle ≈ 0,49 sur les pixels à signal non nul.
   La classification fine requiert une séparabilité inter-classes que le signal HAG ne
   fournit pas (AUC 408 vs 410 = 0,48).

2. **Qualité des formes** : compacité 0,441 vs cible FFCO 0,663. Neuf leviers testés,
   tous insuffisants. La cause est structurelle : le pipeline seuille un champ continu,
   le cartographe délimite des zones de praticabilité homogène.

3. **Domaine étroit** : n=1 terrain dans le domaine. Les trois modes de défaillance documentés
   (indiscernabilité, désaccord sémantique, signal uniforme) ne sont pas captables par un
   critère automatique unique.

---

## 10. Rendu KP retenu actuellement

| Paramètre | Valeur retenue |
|---|---|
| `lightgreentone` | 160 |
| Opacité template | 50 % |
| `medianboxsize` | 9 |
| `medianboxsize2` | 16 |

**Note sur medianboxsize2 :**

`medianboxsize2=1` est le défaut KP Rust v2.12.1 et désactive effectivement le second
filtrage médian de la végétation.

Les tests 1 → 5 → 10 → 16 montrent un lissage monotone et cohérent des aplats : zones
progressivement plus nettes et suivables à 1:10 000.

`medianboxsize2=16` est retenu pour le rendu actuel et la validation d'usage sur Grimbosq.
Ce n'est pas un optimum universel démontré — il n'a pas été testé sur d'autres terrains
ni avec d'autres types de végétation.

`greenshades` n'est pas étalonné sur la franchissabilité CO.

### Effet mesuré de medianboxsize2=16 sur la fidélité spatiale

**ÉTABLI** (Grimbosq, protocole exp2_3, référence = contour FFCO 131 056 m) :

| Métrique | `_vege` mbs2=1 | `_vege` mbs2=16 |
|---|---|---|
| Distance médiane → réf | 9,4 m | 11,1 m |
| Couverture ≤ 5 m | 66,4 % | 36,6 % |
| Couverture ≤ 10 m | **86,0 %** | **57,9 %** |
| Couverture ≤ 20 m | 95,0 % | 78,3 % |
| ratio_utile | 0,517 | 0,476 |
| Composantes | 3 662 | 1 137 |
| Longueur médiane composante | 16 m | 19 m |
| Longueur maximale composante | 24 370 m | 15 216 m |
| is_blob | non | non |

`medianboxsize2=16` a été retenu pour améliorer la lisibilité visuelle du fond KP, mais les
mesures montrent qu'il supprime une part importante de la proximité avec les limites de
référence : la couverture ≤ 10 m chute de 86,0 % à 57,9 % (−28 pp), et le kilométrage
frontière total passe de 450 km à 230 km (−49 %). Le réglage actuel **privilégie le confort
de lecture au détriment d'une partie de la fidélité spatiale.**

**Question ouverte :** Ce compromis est-il souhaitable pour un fond destiné au tracé manuel ?
Une lisière ou une clairière supprimée par le filtrage peut constituer une information que le
cartographe doit pouvoir voir. Cette question ne peut pas être tranchée sans nouvelle
validation d'usage.

### Comparaison visuelle avec contour FFCO à 1:10 000

**ÉTABLI** (Grimbosq, comparaison `_vege` mbs2=1 vs mbs2=16 avec contour FFCO superposé,
lightgreentone=160, opacité 50 %, fenêtres 500 × 500 m) :

- **fen1_406** : La non-détection de la grande zone centrale est identique dans les deux
  réglages — antérieure au choix de mbs2, non aggravée par le filtrage. Les petits fragments
  verts présents en mbs2=1 sont légèrement fusionnés en mbs2=16 ; la couverture de cette zone
  reste comparable car elle est structurellement sous-couverte.

- **fen2_408** : Gain net de lisibilité en mbs2=16. Le mouchetage dense de mbs2=1 rend les
  transitions et les grandes masses difficiles à lire. En mbs2=16, les grandes masses sont
  plus franches. Contrepartie visible : plusieurs trouées blanches apparaissent à l'intérieur
  de polygones FFCO qui étaient couverts en mbs2=1.

- **fen3_410** : mbs2=16 produit des masses vertes plus cohérentes et moins mouchetées. En
  mbs2=1, le contour FFCO est davantage noyé dans les petites structures. Les structures
  supprimées par mbs2=16 sont en partie des fragments internes ou périphériques qui ne
  contribuent pas aux grandes limites lisibles à 1:10 000.

**Décision de production — ÉTABLIE :** `medianboxsize2=16` est conservé dans la configuration
de production. Le réglage est retenu comme compromis de lisibilité du fond de décalque à
1:10 000, et non comme optimum géométrique démontré.

La perte de couverture (86,0 % → 57,9 % à ≤ 10 m) ne doit pas être interprétée seule comme
une dégradation : la métrique de couverture favorise mécaniquement les rendus très remplis.
mbs2=1 conserve davantage de petites structures au prix d'un mouchetage qui gêne la lecture
des grandes masses. Le choix de mbs2=16 **privilégie la lisibilité du support** plutôt que
le maintien maximal de toutes les petites structures détectées par KP.

Aucun nouveau test de valeur intermédiaire n'est lancé.

---

## 11. Architecture actuelle et livrable

```
LiDAR IGN HD (COPC)
  ↓
Karttapullautin (KP v2.12.1) — mode batch
  ↓
vegetation.png  (mosaïque géoréférencée, ~1 m/pixel)
  +
vectoriel Lidar'O  (courbes, falaises, points relief)
  ↓
.omap — structure :
   ├── relief / courbes de niveau
   ├── chemins et routes
   ├── bâtiments
   ├── hydrographie
   ├── terrain découvert / zone interdite
   └── template vegetation.png
          tone 160
          opacity 50 %
          medianboxsize2 = 16
  ↓
OCAD / OOM — tracé et modification des limites de végétation
```

**Mise à jour 2026-10 (PLAN 3)** : la végétation 406/408/410 **est de nouveau produite automatiquement
dans l'OMAP**, via la chaîne KP vectorisée (`step_vegetation_kp` → `vegetation_kp.gpkg`).
La chaîne HAG (`src/vegetation.py`, seuils density_hag) reste dans le code mais n'alimente plus
le livrable principal — elle sert de fallback QA si `vegetation_kp.gpkg` est absent.

---

## 12. Vectorisation : suspendue, pas abandonnée

La vectorisation automatique de la végétation reste un objectif, mais l'approche actuelle
`density_hag → seuil → polygonisation` n'a pas produit de contours suffisamment utiles
(fragmentation extrême : 12 310 composantes de 4 m en moyenne à 2 m de résolution).

### 12.1 Vectorisation du rendu KP — implémentée (PLAN 3)

```
vegetation KP  (vegetation.png ou _vege.png par dalle)
  ↓
segmentation
  ↓
polygonisation
  ↓
nettoyage  (trous, artefacts)
  ↓
simplification
  ↓
lissage éventuel
```

**ÉTABLI (mesure) / SUSPENDUE (vectorisation).**

La proximité de `_vege.png` avec les contours FFCO a été mesurée selon le protocole exp2_3
pour deux variantes de paramétrage (voir §10) :

- **mbs2=1** : couverture ≤ 10 m = 86,0 %, longueur médiane composante = 16 m
- **mbs2=16** : couverture ≤ 10 m = 57,9 %, longueur médiane composante = 19 m

Le critère de vectorisation posé (longueur médiane ≥ 32 m **et** couverture ≤ 10 m ≥ 64,5 %)
n'est atteint dans aucune des deux variantes. La mesure porte sur des frontières pixel — la
qualité cartographique des polygones résultants n'a pas été évaluée.

**Critère de vectorisation — ÉCHEC sur les deux conditions :**

| Condition | Valeur mesurée | Seuil fixé | Verdict |
|---|---|---|---|
| Longueur médiane composante | 19 m | ≥ 32 m | ÉCHEC |
| Couverture ≤ 10 m | 57,9 % | ≥ 64,5 % | ÉCHEC |

La variante `_vege` + `medianboxsize2=16` ne fournit pas une matière première suffisamment
favorable pour lancer une expérience de vectorisation.

**Mise à jour 2026-10 (PLAN 3)** : la piste a été relancée et implémentée via `coverage_simplify`
(tolérance 2 m, validée V3 bras C). La chaîne complète est dans `step_vegetation_kp` (`main.py`)
et documentée dans `docs/pipeline_vegetation_kp.md`. Le critère de frontières pixel §12.1 ne
s'applique pas à cette approche : `coverage_simplify` opère sur la topologie des polygones, pas
sur une segmentation pixel-à-pixel.

### 12.2 Piste lissage géométrique des contours

**NON TESTÉ.** À évaluer après polygonisation des aplats KP : un lissage de type gaussien
appliqué aux **contours vectoriels**, uniquement pour améliorer la forme géométrique.

Ce lissage est distinct de deux choses déjà en place ou déjà réfutées :

- **Pas le σ gaussien du pipeline HAG** : le lissage σ s'applique au raster `density_hag`
  avant seuillage — il opère sur un champ continu, en amont de toute classification.
- **Pas l'un des 15 leviers réfutés** : ces leviers portaient tous sur le signal density_hag.
  Ici le point de départ est `vegetation.png`, image pré-classifiée par KP — les aplats
  existent déjà, la question porte uniquement sur la régularité géométrique des contours
  après polygonisation.

Ce lissage ne doit pas servir à masquer une mauvaise segmentation.

### 12.3 Piste non instruite — plusieurs niveaux de lissage

**NON TESTÉ.** Plutôt qu'un réglage unique de `medianboxsize2`, permettre de choisir entre
plusieurs niveaux de lissage du fond selon la tâche :

```
vue générale (grandes masses)   → fond lissé  (mbs2=16)
travail de détail (lisières)    → fond moins lissé  (mbs2 faible)
```

Cette piste concilierait lisibilité générale et conservation des structures fines. Elle n'est
pas développée dans la présente étape.

---

## 13. Cas de non-détection connu — fen1_406

La fenêtre fen1_406 (~25 ha, Grimbosq) contient **45,9 % de végétation CO selon la FFCO**
(29 % de classe 406, 10 % de classe 408). `vegetation.png` ne produit pratiquement aucun
signal exploitable dans cette fenêtre.

**Cas de non-détection observé ; la cause n'est pas établie.**

Les hypothèses plausibles (**INTERPRÉTÉ**, non démontré) : végétation basse et peu dense
dont le signal HAG [0,3–3,0 m] est noyé dans le bruit de fond ; caractéristique du terrain
dans ce secteur ; artefact de dalle. Une investigation sur les nuages de points bruts serait
nécessaire avant de conclure.

---

## 14. Domaine d'utilisation

### 14.1 Domaine du modèle HAG — évalué sur 4 terrains

Le tableau ci-dessous documente le domaine du **modèle HAG** (density_hag → seuillage →
classification 406/408/410). **Ce modèle n'est plus le livrable actuel.**

| Terrain | Statut | Mode de défaillance |
|---|---|---|
| **Grimbosq** (feuillus, Normandie) | Dans le domaine | Classe 406 hors portée |
| **Airelles** (résineux/lande, France) | Hors domaine | Indiscernabilité inter-classes : lande praticable ≡ sous-bois en HAG[0,3:3,0 m] |
| **Kilemaed** (Estonie, lande/forêt) | Hors domaine | Désaccord sémantique : végétation basse terrain ouvert (ISOM 403/404) ≡ sous-bois |
| **Kuti** (Estonie, épicéas) | Hors domaine | Signal uniforme dense (p95/p50=3,3) : p95_local compresse tout en [0,3–0,8] |

Grimbosq est le seul terrain dans le domaine. Ceci rend impossible la calibration d'un
critère de fiabilité automatique (n=1 in-domain ne suffit pas).

**Note sur le critère p95/p50 :** Grimbosq=7,6, Airelles=7,7 — le critère ne sépare pas
les deux alors que leurs modes de défaillance diffèrent. Aucune frontière binaire sur p95/p50
n'est valide pour tous les modes.

### 14.2 Domaine du fond KP — non évalué

Le livrable actuel est le fond `vegetation.png` produit par Karttapullautin, pas la
classification HAG. Le domaine d'application du fond KP **n'a pas été évalué** sur corpus
multi-terrain. Les tests comparatifs des 4 terrains portaient exclusivement sur le modèle HAG.

**NON TESTÉ** : comportement de KP sur Airelles, Kilemaed, Kuti, ou sur d'autres forêts
normandes que Grimbosq. Le cas de non-détection fen1_406 montre que KP peut ne produire
aucun signal dans une zone de végétation CO — y compris sur Grimbosq.

L'objectif actuel reste les **forêts normandes ciblées, principalement feuillues**
(Calvados, France), avec LiDAR IGN HD (densité > 10 pts/m²), sur la base de la validation
visuelle sur Grimbosq uniquement. Ce périmètre ne découle pas d'une évaluation systématique
du fond KP — il reflète l'état de la validation disponible.

---

## 15. Leçons de méthode

### 15.1 Principes établis au fil de la campagne

1. **Ne pas confondre proximité géométrique et utilité pour le cartographe.**
   Une frontière à 9,4 m de distance médiane n'est pas nécessairement décalquable si elle
   est fragmentée en 3 662 composantes de 4 m en moyenne. Les deux types de mesures sont
   nécessaires et ne se substituent pas l'un à l'autre.

2. **Contrôler les rendus à l'échelle d'usage (1:10 000).**
   Des fenêtres affichées à ×6 l'échelle d'impression montraient un fond KP saturé et
   moucheté — artefact de zoom inexistant à l'échelle réelle. Nommer l'échelle de contrôle
   fait partie du protocole.

3. **Ne pas transformer une corrélation en causalité.**
   La corrélation r=−0,689 entre fraction 406 par cellule et delta-coverage signifie que
   les zones sous-détectées correspondent aux zones à végétation légère — conséquence directe
   de l'AUC 0,487 pour 406, pas une causalité nouvelle.

4. **Vérifier la version exacte et l'ini réel d'un outil de référence.**
   KP v2.12.1 Rust réécrit `pullauta.ini` à chaque exécution batch, écrasant les paramètres
   personnalisés. Les paramètres effectifs doivent être lus dans le fichier réel au moment de
   l'expérience, pas dans celui qui était prévu.

5. **Vérifier qu'on mesure le bon fichier de sortie.**
   L'expérience 2.3 a mesuré `_undergrowth.png` (quasi-vide) au lieu de `_vege.png` (le
   rendu effectivement utilisé), produisant une couverture de 0,4 % représentative du fichier
   mais non de KP. La documentation existante (`etat_existant.md`) le précisait et n'a pas
   été relue.

6. **Conserver les configurations utilisées pour les expériences.**
   Seuils T, σ, et référence Grimbosq ont évolué au cours de la campagne. Le snapshot
   post-correction (2026-08-13) est la seule référence fiable. La série temporelle avant
   cette date n'est pas directement comparable.

7. **Vérifier le livrable final et pas seulement les artefacts intermédiaires.**
   La qualité du raster `density_hag.tif` ne dit pas si le rendu `vegetation.png` dans
   l'OMAP est lisible à l'échelle d'usage. Les contrôles finaux se font sur le fichier `.omap`
   dans OOM, pas sur les sorties pipeline intermédiaires.

8. **Ne jamais lire la couverture référence → produit seule.**
   La métrique favorise mécaniquement les rendus très remplis : un fond couvrant une grande
   surface est plus souvent situé à ≤ 10 m des limites de référence, même lorsque ce vert est
   peu pertinent pour la lecture cartographique. La couverture doit être combinée avec le
   `ratio_utile`, la structure spatiale (nombre et taille des composantes), et la visualisation
   superposée à la référence avant toute décision sur l'utilité du fond.

9. **Avant de traiter une dette héritée, vérifier qu'elle décrit encore l'état actuel du code.**
   La valeur 1511/767/497 décrivait un état du pipeline antérieur au pivot KP. Elle a continué
   d'être citée — qualifiée de « dette la plus urgente » — alors qu'elle ne correspondait plus
   à rien dans le dépôt. C'est la deuxième occurrence du même mécanisme dans ce projet, après
   le « 370 polygones » : une valeur portée d'une session à l'autre sans revalidation. La première
   a coûté une référence non reconstructible ; celle-ci a failli coûter un chantier de correction
   sur un problème inexistant.

### 15.2 Clôture de la fausse dette QA

**ÉTABLI** (2026-09, vérification dans le code) :

La dette « la QA mesure un artefact intermédiaire (942/611/465), pas le livrable (1511/767/497) »
a été héritée d'une session antérieure. Elle décrivait un état du pipeline **antérieur au pivot
vers KP**, où les couches 406/408/410 étaient encore injectées dans le `.omap`. Depuis le pivot
(`main.py:510-511`) :

- au moment de rédaction (pré-PLAN 3), le `.omap` ne contenait plus de couches vectorielles 406/408/410 ;
- depuis PLAN 3 (2026-10), elles sont de nouveau présentes via `vegetation_kp.gpkg` ;
- les valeurs 1511/767/497 restent introuvables dans l'intégralité du dépôt ;
- 942/611/465 sont les comptes corrects **après clip au hull FFCO** (323,8 ha), produits par
  `report_hull_metrics()` — c'est la bonne métrique de comparaison avec le référentiel FFCO.

**La QA mesure ce qu'elle doit mesurer. La dette n'existait pas dans l'état actuel du code.**

### 15.3 Conclusions trop larges corrigées

| Formulation ancienne | Formulation corrigée |
|---|---|
| `_undergrowth` représente le rendu KP | `_undergrowth` est quasi-vide dans KP v2.12.1 Rust ; le rendu utilisé est `vegetation.png` |
| Exp2.3 : KP couvre 0,4 % du contour | Exp2.3 mesurait un fichier quasi-vide ; `_vege` couvre 86 % à ≤ 10 m selon la métrique frontière pixel |
| Le pipeline couvre 100 % du terrain | Tautologie : mesure sur le hull propre du pipeline ; le recall FFCO est 35–82 % selon la classe |
| Gain de X pp sur la classe 406 | Sans pondération par surface FFCO, une comparaison en pp entre classes est trompeuse |
| QA mesure 942/611/465 sur artefact, livrable = 1511/767/497 | 942/611/465 est le compte hull-clippé correct ; 1511/767/497 décrivait un état antérieur au pivot KP |

---

## PLAN 3 — verdict final (2026-10-07)

Objectif : intégrer la vectorisation du rendu KP dans la chaîne de production et supprimer l'ancien chemin HAG→OMAP.

### Acquis expérimentaux

| Point | Statut | Référence |
|---|---|---|
| Raster KP retenu comme source de classification | ÉTABLI | V1 f9ea539 |
| `shade_to_isom` gelé (table PLAN 3) | ÉTABLI | V3 3d579ba |
| Polygonisation RAW lossless (aucune perte avant `coverage_simplify`) | ÉTABLI | V1 f9ea539 |
| `coverage_simplify` tolerance=2 m retenu | ÉTABLI | V3 3d579ba |
| Topologie inter-classes : T-junctions structurelles, garde-fou per-classe, simplification globale | ÉTABLI | P16 866916f |
| OOM validé avec template (opacity=0,5) | ATTESTÉ porteur | V4 5fffba7 |
| OOM validé sans template | ATTESTÉ porteur | V4 5fffba7 |

**T-junctions** : quand rasterio polygonise chaque classe séparément, les frontières inter-classes produisent des T-junctions. `coverage_is_valid` per-classe = True, global = False. La garde-fou per-classe détecte les erreurs intra-classe ; `coverage_simplify` est appliqué sur l'ensemble des classes pour traiter les frontières partagées sans créer de recouvrements.

### Production — état intégré

- Chaîne : `step_vegetation_kp` → `vegetation_kp.gpkg` → `step_assemble` → `.omap`
- Source unique de la végétation dans le `.omap` : `vegetation_kp.gpkg`
- QA KP par défaut ; fallback QA HAG si `vegetation_kp.gpkg` absent (nommé dans les logs et `run_metadata.json`)
- Paramètres KP suivis dans `config_snapshot.json`
- Ancien chemin `scripts/mask_vegetation.py:main()` + `build_veg_layers` + `regenerate_omap` supprimés (P20, ffaaea9)

### Grimbosq — chiffres de référence

1340/409/18 (406/408/410). Validation visuelle OOM 2026-10-04 (attestation porteur).

Artefacts V4 (commit 5fffba7 — `work/expe/vectorisation/`) :

| Fichier | XML | Objets | 406 | 408 | 410 | Symboles inconnus |
|---|---|---|---|---|---|---|
| `v4_with_template.omap` | valide | 1767 | 1340 | 409 | 18 | aucun |
| `v4_no_template.omap` | valide | 1767 | 1340 | 409 | 18 | aucun |

> `ctrl_omap.py` sans gabarit ISOM produit des IDs bruts : id_86 → 406 (1340), id_89 → 408 (409), id_93 → 410 (18).

Attributs XML templates (vérifiés) :
- `v4_with_template` : `<templates count="1" first_front_template="1">`, `<template type="TemplateImage" open="true" name="KP vegetation (fond)" relpath="vegetation.png" opacity="0.5" georef="true">` (non auto-fermant)
- `v4_no_template` : `<templates count="0" first_front_template="0">`, zéro TemplateImage

Bbox `vegetation_kp.gpkg` (global 406+408+410) : [448000, 6886000, 449997, 6888997] ⊂ emprise config [448000, 6886000, 450001, 6889001].

### Non démontré

- Portabilité de `shade_to_isom` sur un terrain différent de Grimbosq
- Comportement des classes 406/408/410 sur une autre forêt ou composition différente
- Qualité géométrique hors Grimbosq

→ étape suivante : test de portabilité sur au moins un autre terrain.

### Docker

Commit df15ceb met à jour le Dockerfile (ligne 58 : `kp_raster`, `kp_install`, `setup_terrain`, `trier_ref`). Image **non reconstruite** dans cette session — la conformité Dockerfile/image n'est pas vérifiée.

### Suite de tests

| Arbre | Collectés | Passés | Skippés | Échoués | Note |
|---|---|---|---|---|---|
| Dépôt `origin/master@4e750b4` | 148 | 146 | 1 | 1 | Échec environnemental : `test_init_terrain::TestCmdCheck` (module `pdal` absent). |

`tests/test_vegetation_kp.py` est identique à `origin/master` (13 tests au registre depuis 4ec6848). Aucun test supplémentaire commité : `src/topology.py` + `tests/test_topology.py` sont déplacés sous `work/expe/topology/` (gitignore, local uniquement).

### Registre des commits PLAN 3

| Étape | Hash | Statut | Description |
|---|---|---|---|
| Intégration P2–P15 | 7f4805d | origin/master | feat: intégrer la chaîne KP vectorisée |
| Tests P2–P11 | 5cba21a | origin/master | test: couverture P2–P11 |
| V4 validation OOM | 5fffba7 | origin/master | docs: V4 PASS — validation OOM 2026-10-04 |
| Fix topologie inter-classes | 866916f | origin/master | fix: coverage_simplify global + garde-fou intra-classe |
| Tests mutation topologie | 4ec6848 | origin/master | test: verrouiller coverage_simplify global par mutation |
| Fix erreurs bloquantes KP absente | 652f200 | origin/master | fix: erreurs bloquantes source KP absente + doc pipeline |
| Tests erreurs bloquantes KP absente | 7dda3ed | origin/master | test: couvrir les erreurs bloquantes source KP absente |
| Docs README + Dockerfile | df15ceb | origin/master | docs: README + Dockerfile reflètent l'intégration KP |
| P20 nettoyage HAG→OMAP | ffaaea9 | origin/master | refactor: supprimer l'ancien chemin HAG→OMAP |
| P21 verdict final | 3d0854c | origin/master | docs: verdict final — chaîne vegetation_kp intégrée |

### Artefacts hors registre

- `work/expe/vectorisation/v4_with_template_test.omap`, `v4_no_template_test.omap` : fichiers post-édition OOM (test porteur) — non commités, untracked
- OMAPs de validation P18 (`output/grimbosq_with_template.omap`, `output/grimbosq_without_template.omap`) : produits dans `output/` (gitignore), non au registre

---

## PLAN 4 — verdict final (2026-10-09)

Objectif : faire de KP le chemin de production officiel et rendre PDAL optionnel pour le mode KP.

### Validé

Les points ci-dessous sont vérifiés par les tests ou par observation directe du code.

**Indépendance KP/PDAL (P0)**

- Audit statique (`src/run_engine.py`) : aucun appel à `pdal` dans le chemin KP.
- Sonde d'exécution (P0.3, worktree a7db172, PATH sans `miniconda3/Library/bin`, leurre `pdal.bat` qui
  enregistre ses invocations) : 42 DXF produits, log du leurre vide, comptes 406/408/410 = 1340/409/18
  (identiques à PLAN 3). KP n'invoque pas PDAL à l'exécution.

**Contrat `vegetation_source` (P1a + P1b, arena)**

- `resolve_veg_source(terrain, cfg)` retourne `"kp"` ou `"hag"` selon la clé
  `terrains.<t>.vegetation_source` ; une valeur inconnue lève `ValueError`.
- Absent = KP par défaut (INFO). Aucune clé globale. Aucun mode `legacy`.
- 15 tests couvrent le contrat dans `tests/test_pipeline_mode.py`.

**Vérification conditionnelle PDAL (P2+P3)**

- `check_deps(require_pdal=False)` : exclut `pdal` de la liste des modules requis.
- `cmd_check(..., veg_mode="kp")` : n'exige pas PDAL ; `veg_mode="hag"` l'exige avec
  message `conda install` explicite.
- Emprise non vérifiable (dalles non-IGN sans PDAL) → `⚠` dans le rapport, jamais `✓`.
- CRS non vérifiable (métadonnées PDAL indisponibles) → `⚠` dans le rapport.
- `veg_mode` propagé dans les trois appelants : `main._cmd_check`, `main._cmd_run`,
  `src/setup_terrain.py`.
- 4 tests couvrent les cas dans `tests/test_init_terrain.py::TestCmdCheck`.

**Suite de tests**

| Commit | Collectés | Passés | Skippés | Échoués |
|--------|-----------|--------|---------|---------|
| `8d8e972` (origin/master) | 193 | 193 | 0 | 0 |

Les 193 tests valident les contrats d'interface et les comportements unitaires listés ci-dessus.
Ils ne valident pas les résultats cartographiques ni le pipeline end-to-end.

---

### Décidé (choix porteur)

Ces points résultent de décisions d'architecture validées par le porteur du projet, pas de mesures.

| Décision | Effet |
|----------|-------|
| `absent = KP par défaut` | Toute configuration sans `vegetation_source` est traitée en mode KP sans avertissement bloquant |
| `vegetation_source: "kp"` pour grimbosq | Terrain de référence explicitement KP |
| `sainte_honorine` → kp | Terrain basculé en KP (décision porteur 2026-10) |
| 7 terrains retirés | `monthureux`, `luxeuil`, `bouhard`, `bas_des_conches`, `kilemaed`, `kuti`, `port_en_bessin` supprimés de `config.yaml` — sans usage actif |
| Terrain KP non-IGN sans PDAL → continuer avec `⚠` | Pas une erreur bloquante ; le pipeline peut continuer sans contrôle d'emprise |

---

### Non vérifié

Les points suivants ne sont pas couverts par les tests ni par la sonde d'exécution.

- **Pipeline end-to-end en mode HAG** : aucun terrain `vegetation_source: "hag"` n'est configuré dans
  `config.yaml`. Le chemin HAG n'a pas été exercé depuis le pivot KP.
- **PDAL absent en production** : les tests patchent `importlib.util.find_spec`. Le comportement réel
  avec PDAL réellement absent de l'environnement conda n'a pas été vérifié en dehors de la sonde P0.3.
- **Georef et contrôles sur terrains non-IGN** : la logique `⚠ emprise non vérifiable` est couverte par
  test avec noms arbitraires mais n'a pas été exercée sur un terrain réel non-IGN.
- **Docker** : le Dockerfile (commit df15ceb, PLAN 3) n'a pas été reconstruit depuis le pivot KP.
  La conformité Dockerfile/image n'est pas vérifiée pour PLAN 4.

---

### Restant à faire

- **P4 Documentation** : `README`, `docs/quick_start.md`, `docs/pipeline_vegetation_kp.md`,
  `docs/installabilite_audit.md` — à mettre en cohérence avec KP par défaut, PDAL optionnel en KP,
  PDAL requis en HAG.
- **Test de portabilité HAG** : valider le chemin HAG sur au moins un terrain réel pour confirmer que
  le routage `veg_mode="hag"` aboutit bien à un run complet avec PDAL.
- **Docker** : reconstruire l'image et vérifier que les dépendances sont cohérentes avec les modes
  KP et HAG.

---

## Annexe — Inventaire des réfutations

| # | Levier | Test | Résultat |
|---|---|---|---|
| 1 | T_406 seuil de détection | AUC Mann-Whitney FN_406 vs blanc | AUC=0,487 — indiscernables |
| 2 | min_area filtre taille | Comptage FN_406 filtrés par taille | 4,4 ha sur 70 ha FN — marginal |
| 3 | σ gaussien 3 m | QA Grimbosq σ=3 vs σ=1 | σ=1 retenu pour recall ; compacité reste 0,441 |
| 4 | grid_resolution 2 m | QA complet 1 m vs 2 m | 38,1 % vs 37,6 % — quasi-inchangé |
| 5 | Normalisation fixed vs p95_local | fixed_percentile=31,018 sur Kuti | QA inchangé — dynamique compressée est le problème |
| 6 | Masque canopée (count_high) | Séparabilité count_high FFCO Airelles | Médiane identique terrain ouvert vs veg_406 |
| 7 | remove_holes pré-merge | Sweep seuils — mauvaise métrique | Médiane tache invariante au remplissage de trous |
| 8 | remove_holes post-merge | Sweep compacité corrigée | Plateau 0,453 au-delà de 200 m² (cible 0,663) |
| 9 | Chirurgie isthmes r=1 m | %<0,3 avant/après | 33,4 %→36,5 % — dégradé |
| 10 | T_408/T_410 inter-classes | Sweep joint pondéré ha | Plateau ha [0,71, 0,92] ; T actuel 0,85 déjà optimal |
| 11 | NRD vs HAG brut | AUC comparée tous filtres | Écart max 0,0006 — substituables |
| 12 | Sigma/IQR [0,3–3,0 m] | AUC veg vs nonveg, inter-classes | Couverture 5 % ; AUC inter ≈ 0,52 — non exploitable |
| 13 | Fenêtres verticales alternatives | [0,3–1,5 m] vs [0,3–3,0 m] | AUC détériore, couverture divise par 3 |
| 14 | Agrégation spatiale 2 m/5 m/10 m | AUC global et conditionnel | Gain marginal (+0,004 global) ; plafond non levé |
| 15 | Intensité de retour HAG[0,3:3,0 m] | AUC FN_406 vs blanc | AUC=0,364 (inversé=0,636) — gradient physiquement incohérent ; biais de sélection |
| 16 | Strate basse LiDAR comme canal undergrowth | Planche Phase 1 — 4 candidats (C1–C4), σ=2 m, seuil 0,5–1,0 pt/m² | Couverture 38–76 % sur fen3_410 — signal trop diffus, non discriminant (Porte 1 NON, 2026-10-01) |
| 17 | Canal de sous-bois (signal HAG basse strate comme couche indicative) | Phase 0 — zones A/B/C/D, dalle 0448\_6888, trois bandes B1 [0,2–1,0], B2 [0,3–1,5], B3 [0,2–2,0] m | B1 occ : A=0,062 < C=0,071 < D=0,076 ; médianes nulles A et C ; B=0,275 valide le protocole ; contrastes B2/B3 (×1,17–1,27) insuffisants pour établir une spécificité — pas de signature HAG basse propre aux zones 406 blanches — trois antécédents convergents (Gate 1, exp1\_10, diag\_hag\_classes) l'avaient laissé attendre (Phase 0 NON, 2026-10-02) |
