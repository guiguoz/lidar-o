# Plan v2 — Du décalque au calque

> **Objet** : amener le rendu Karttapullautin — aujourd'hui un décalque de traçage — jusqu'à
> des **calques vectoriels** de végétation livrables dans le `.omap`, c'est-à-dire franchir le
> critère de vectorisation suspendu, puis améliorer la matière première si nécessaire.
>
> **Remplace** : `docs/archive/PLAN_signaux_lidar_inexploites_2026-10-08.md` (« Plan — Signaux
> LiDAR inexploités ») et `docs/avenant_plan_signaux_lidar.md` (avenant n°01). Les deux
> restent au dépôt comme trace ; en cas de conflit, **ce document prime**.
>
> **Décision fondatrice (2026-10-08)** : la vectorisation est obligatoire en aval, quelle que
> soit la situation. Le critère de vectorisation n'est donc pas une porte à rouvrir : c'est
> **l'objectif**.
>
> **Révision 2 (2026-10-08, soir)** : intégration d'une revue externe (ChatGPT) — voir §1.8.
> Corrections apportées : chaîne minimale bout-en-bout avant toute généralisation, **mapping
> explicite tons → classes**, **surfaces minimales ISOM corrigées**, masques cumulatifs,
> audit de matière première élargi, résolution sémantique de 3 m.
>
> **Révision 3 (2026-10-08, soir)** : seconde passe de la même revue. Corrections :
> dimensionnement des noyaux (§0c, §3), protocole de calibration 1b renforcé (ROIs
> indépendantes, validation tenue à part, monotonicité), décomposition suppression/fusion
> (§2.3), et **décision écrite d'avance en cas d'échec de 1b** (§3).
>
> **Révision 4 (2026-10-08, nuit)** : troisième passe de la même revue + **vérification à la
> source de la citation Trier**. Corrections : marge de sécurité des ROIs (§3), statut de
> **référence bruitée** de la FFCO (§3), reformulation du noyau 7×7 et rappel de ne pas
> « corriger » la séquence de Trier pour l'aligner sur la maille de 3 m (§0c), **plafond
> `max_pct` pré-engagé** (§2.3), nuance sur « seuils de suppression » (§2.2), structure de
> falsification A/B/C (§6).

---

## 0. Pourquoi ce nom (le plan a changé de nom, et ce n'est pas cosmétique)

| | v1 | v2 |
|---|---|---|
| Titre | « Plan — Signaux LiDAR inexploités » | « **Du décalque au calque** » |
| Objet réel | quels canaux n'ont pas été lus | transformer une **image** en **vecteurs livrables** |
| Critère de succès | une AUC qui bouge | le **fichier** qui franchit son critère |

Le nom de v1 décrivait une **curiosité d'exploration** : il a produit un plan dont quatre
étapes sur sept ne touchaient pas le livrable (§1.1 ci-dessous). Le nom de v2 décrit la
**transformation attendue** : le PNG de végétation est un *décalque* (on trace par-dessus) ;
l'objectif est qu'il devienne un *calque* (une couche du `.omap`, avec des polygones).

Noms écartés : « De l'image au vecteur » (juste, mais générique) ; « Vectoriser le rendu KP »
(décrit une méthode, pas un plan) ; « La forme avant le signal » (décrit un ordre, pas un
objet).

---

## 1. Autocritique

### 1.1 L'erreur de fond : le plan a suivi ses canaux, pas son livrable

Le livrable `output/<terrain>.omap` contient : le fond végétation KP (opacité 50 %), les
couches BD TOPO, les courbes/falaises de KP. **Les 406/408/410 n'y sont pas.** Pourtant v1
ouvrait par la Phase A « seuils par échantillons » et plaçait le banc vertical avant tout le
reste — deux travaux sur *notre* raster de classification, qui n'atteint jamais le fichier.

**Correction v2** : le critère de sortie des premières étapes est le critère de vectorisation
lui-même ; le signal (banc vertical, Phase A) passe en étape 6 et ne s'engage que si la forme
échoue encore.

### 1.2 L'erreur d'ordre : calibrer avant de connaître le témoin

v1 dérive des seuils par échantillons… contre un témoin dont **on ne connaît pas le
réglage** : `_build_ini` n'injecte que `lightgreentone` et `medianboxsize2` ; `greenshades`
(obligatoire pour KP), `medianboxsize` et les facteurs de retour vivent dans un `pullauta.ini`
non versionné, réécrit à chaque exécution batch (bilan §15.1.4).

**Correction v2** : audit de 10 minutes, premier item.

### 1.3 Deux prémisses fausses (corrigées, elles ne reviennent pas)

- « L'intensité n'a jamais été lue » : elle l'a été — réfutation n°15, `docs/test_intensite.md`
  (AUC 0,3638 vs blanc ; r angulaire 0,0339). Ce qui reste ouvert est l'**essence**
  (feuillus/résineux), une autre question sur une autre population.
- « La NDVD est à implémenter » : avec `NDVD = (V−G)/(V+G)` et notre `ratio =
  bande/(bande+dessous)`, **NDVD = 2·ratio − 1** ; et `ratio` ≡ `NRD` à 0,0006 près (bilan
  §5). C'est la validation externe de notre métrique, pas un levier.

### 1.4 L'erreur d'auteur : mon avenant n°01 a réduit le périmètre au lieu de réordonner

L'avenant quantifiait la suringénierie (« périmètre engagé : ½ j ») mais **conservait la
vectorisation comme une option suspendue** — il a fallu une décision explicite pour remettre
le livrable en tête. Leçon : *un avenant qui réduit le périmètre sans demander « qu'est-ce qui
produit le fichier ? » ne fait que reporter le problème.*

### 1.5 Le critère lui-même est critiquable

`longueur médiane ≥ 32 m` **et** `couverture ≤ 10 m ≥ 64,5 %` est un critère **géométrique**,
satisfiable en **aplatissant** (fusionner en grosses masses allonge les composantes et peut
même améliorer la couverture, en détruisant l'information cartographique). Et il a été mesuré
sur des **frontières pixel** (bilan §12.1), pas sur des objets vectoriels — il devra donc être
**re-mesuré** après vectorisation ; la valeur 16–19 m n'est qu'une ligne de base.

**Garde-fous** (§2) : surfaces et répartition par ton ; **part de la plus grande composante**
(le `max_pct` de `src/qa.py` existe déjà et sert de garde-fou anti-percolation) ; nombre de
composantes ; lisibilité à 1:10 000 sur planche.

### 1.6 Ce qui reste incertain, et qui est le vrai risque du plan

| Hypothèse | Statut | Comment on la tue vite |
|---|---|---|
| La généralisation cartographique (surfaces minimales + fusion + simplification) suffit à passer de 16–19 m à 32 m | **NON TESTÉ — hypothèse centrale** | étape 2 |
| Peut-on associer les tons KP aux classes 406/408/410 de façon stable ? | **NON TESTÉ — risque n°1** | étape 1b, ROIs FFCO avec validation tenue à part (§3) ; issue d'échec écrite d'avance |
| Le PNG KP porte l'artefact de bande (mesuré sur **notre** raster : 84,6 vs 41,2 pts/m², jamais sur le PNG) | **NON TESTÉ** | étape 0c, à l'œil, 10 min |
| La cascade de Trier défragmente sans aplatir | **NON TESTÉ sur le PNG** (codée, testée en synthétique) | étape 3 |
| Le signal (banc vertical) est nécessaire derrière | **NON TESTÉ — parqué** | seulement si 1–4 échouent |

### 1.7 Autocritique de rythme

Quatre documents produits en une journée. Le plan s'interdit d'en produire un cinquième avant
que le critère soit franchi ou la famille épuisée. Le prochain livrable utile est **du code,
des mesures et un `.omap` expérimental**.

### 1.8 Revue externe (ChatGPT, 2026-10-08) — ce qui est intégré, ce qui est déjà fait, ce qui est corrigé

**Intégré (5 points, tous justes)** :

1. **Le mapping tons → 406/408/410 manquait.** « Segmentation en tons » ne dit pas *quels*
   tons deviennent *quelles* classes. Étape 1b nouvelle, et ce mapping **ne s'invente pas** :
   c'est la Phase A de v1 (zones d'échantillons homogènes sur le FFCO → distribution →
   seuils), appliquée à l'échelle des tons KP au lieu du HAG. La Phase A n'est donc pas
   abandonnée : elle est **réaffectée** au service de la vectorisation.
2. **Chaîne minimale bout-en-bout d'abord.** PNG → `kp_vegetation.gpkg` → `Layer()` →
   `.omap` avant toute généralisation ; sinon on compare des chaînes différentes et on ne sait
   pas ce qui a produit le gain. Le writer n'est pas le chantier : `src/omap_writer.py` possède
   `Layer` (code ISOM) et `_polygon_to_xml` sérialise déjà des polygones en objets de surface —
   **vérifié dans le code**.
3. **Trier sur masques cumulatifs**, pas ton par ton : les tons sont **ordonnés**, des
   fermetures indépendantes créent des recouvrements impossibles. Précision : l'implémentation
   V6 de `scripts/diag/sweep_ordre_lissage.py` assigne déjà du plus sévère au plus léger avec
   un masque `assigned` — c'est cumulatif. Le plan le dit désormais explicitement.
4. **Critère géométrique = un indicateur parmi d'autres**, et la QA **existe déjà** :
   `src/qa.py` fournit `cov%`, `n`, `med_mm2` (en mm² carte — l'unité d'ISOM), `%<1mm2`,
   `max_pct` (part de la plus grande composante, avec garde-fou anti-percolation). On les
   réutilise au lieu d'en écrire de nouveaux.
5. **« Généraliser selon l'ISOM » est un abus de langage.** ISOM fixe des contraintes
   graphiques et sémantiques, pas un algorithme. Renommé **« généralisation cartographique
   compatible ISOM »**.

**Correction factuelle acceptée (et vérifiée à la source)** : les surfaces minimales citées par
v2 (50/30/20 m²) **ne sont pas celles d'ISOM 2017-2**. Valeurs réelles (O-Map Wiki, reprises de
la spec, rev. 6) converties à 1:10 000 — voir §2.2. La conséquence est favorable : les minima
réels sont **deux fois plus agressifs** que ceux qu'on s'appliquait, ce qui va dans le sens de
la longueur médiane recherchée.

**Seconde passe de la même revue (révision 3)** — corrections acceptées : dimensionnement des
noyaux (§0c : ma formulation « multiples de 3 m » était fausse ; le code, lui, paramétrait déjà
en mètres), protocole 1b (ROIs, cellule = observation, validation à part, monotonicité),
décomposition suppression/fusion (§2.3.3). Ajout demandé par la question utilisateur : la
**décision d'échec de 1b** (§3), que ni la revue ni la révision 2 ne prévoyaient.

**Troisième passe de la même revue (révision 4)** — corrections acceptées : marge de sécurité
des ROIs (§3), statut de référence bruitée de la FFCO (§3), reformulation du noyau 7×7 (§0c),
plafond `max_pct` pré-engagé (§2.3), nuance sur « plus agressive » (§2.2). **Sa citation de
Trier a été vérifiée à la source** (article intégral, GAC/Vilnius Tech) : la séquence
closing 7×7 → opening 3×3 → closing 9×9 → opening 5×5 → closing 11×11 → opening 7×7 est bien
la procédure publiée en §2.2 (fig. 7c–7h), sur une image NDVD 0.2–2,0 m **agrégée à 1,0 m**.
Deux trouvailles supplémentaires, qui renforcent le plan : (a) Trier conclut lui-même qu'une
**seule classe** de runabilité réduite est « more meaningful » pour une méthode automatique —
notre branche d'échec de 1b cesse d'être un jugement pour devenir le résultat de référence ;
(b) ses seuils de NDVD dépendent de la densité d'impulsions (2 vs 10 pts/m²), donc rien ne se
copie sur nos bandes à 41–85 pts/m².

**Réserves, documentées** :

- « onze `greenshades` configurés dans ton projet » : **non vérifié en l'état**. Le dépôt ne
  contient la clé nulle part (elle vit dans l'ini non versionné) ; « onze » vient du §10 du
  plan v1. L'étape 0a le dira — et c'est précisément pourquoi elle est en premier.
- « L'overage removal est trop haut dans la chaîne » : il était **déjà conditionnel** (0c).
  Renforcé : conditionné à *artefact visuel* **et** *provenance démontrée* (§3, 0b).
- « Risque très élevé » sur le mapping des tons : le risque est réel mais il est **mesurable
  et borné** — on dispose d'une méthode de calibration (zones FFCO) et d'un référentiel
  surfacique. Il est classé risque n°1, avec un coût de réfutation de quelques heures.
- « Créer `kp_vectorize.py` » : oui — le nom et l'emplacement du module sont actés au §3.

---

## 2. Le critère (écrit avant mesure, avec ses garde-fous)

### 2.1 Critère hérité

| Condition | Seuil | État actuel (sur frontières pixel) |
|---|---|---|
| Longueur médiane d'une composante | ≥ **32 m** | 16 m (mbs2=1) · 19 m (mbs2=16) — **ÉCHEC** |
| Couverture ≤ 10 m | ≥ **64,5 %** | 86,0 % (mbs2=1) · 57,9 % (mbs2=16) |

**Lecture** : une seule condition échoue sur la variante non lissée — la **fragmentation**. Le
seul levier mesuré de ce type (le filtre médian) est mauvais : +3 m pour **−28 points** de
couverture. Un réglage global ne peut pas satisfaire les deux : il faut une généralisation
**consciente de la forme**. Le critère sera **re-mesuré sur composantes vectorielles** ; c'est
la mesure pixel qui sert de ligne de base.

### 2.2 Surfaces et largeurs minimales — valeurs ISOM 2017-2 corrigées

Contraintes graphiques de la spec, converties à l'échelle cible 1:10 000 (1 mm = 10 m) :

| Symbole | Minimum graphique | **À 1:10 000** | Largeur minimale | **À 1:10 000** |
|---|---|---|---|---|
| **406** (course lente) | 1 × 1 mm (empreinte 15 × 15 m à 1:15 000) | **100 m²** (10 × 10 m) | 0,4 mm | **4 m** |
| **408** (marche) | 0,7 × 0,7 mm (10,5 × 10,5 m) | **49 m²** (7 × 7 m) | 0,3 mm | **3 m** |
| **410** (lutte) | 0,55 × 0,55 mm (8 × 8 m) | **30 m²** (5,5 × 5,5 m) | 0,25 mm | **2,5 m** |

> Les valeurs 50/30/20 m² de `docs/iof_generalization_rules.md` (colonne « mm² » : 0,5 / 0,3 /
> 0,2) **ne sont pas les minima ISOM 2017-2** et le document les donnait lui-même comme « à
> confirmer ». Elles sous-estiment les minima d'un facteur ~2 et doivent être remplacées : à
> 1:10 000, c'est 1,0 / 0,49 / 0,30 mm². Conséquence : **les seuils de suppression peuvent être
> plus agressifs que ceux employés jusqu'ici** — c'est un droit, pas une obligation. Le minimum
> ISOM est une contrainte de **représentation** : aucun objet n'est « illégal » ; c'est la
> situation locale (fusionner, transformer, déplacer, supprimer) qui décide. Corroboration de
> la pratique : Trier, travaillant à 1:15 000, retire les objets 406/408 sous **225 m²**
> (= 1 mm² à cette échelle) et les 410 sous **112,5 m²** — il place son seuil au minimum
> graphique de l'échelle cible, exactement ce que la table ci-dessus convertit pour 1:10 000.

### 2.3 Garde-fous (à appliquer à chaque variante)

1. **Surfaces** : totale et par ton, dans ±20 % de l'état actuel.
2. **Plus grande composante** (`max_pct` de `qa.py` = surface de la plus grande composante ÷
   surface totale de la classe, en %) : plafond **numérique, pré-engagé avant toute variante** —
   `max_pct_variante ≤ min(1,5 × max_pct_1d ; seuil qa.py)`, où `max_pct_1d` est mesuré **une
   fois** sur la chaîne minimale non généralisée (étape 1d), gelé, et où le `seuil qa.py` est
   celui **déjà présent dans le code** : alerte percolation au-delà de **15 %** de `max%406`
   (plancher mesuré 7,4 %). Dépassement = **rejet automatique**, quelle que soit la médiane
   obtenue ; `k = 1,5` et le seuil ne s'ajustent **pas** après avoir vu un résultat (« ce run
   fait 62 %, ça semble encore raisonnable » est précisément l'arbitrage a posteriori que le
   plan cherche à éliminer). Pour 408/410 (pas de seuil existant), même borne relative ; au-delà,
   jugement sur planche obligatoire.
3. **Nombre de composantes par classe, décomposé** : `n_avant → supprimées par les minima →
   fusionnées par proximité → n_après`. La suppression par surface minimale est une opération
   **légitime** — l'interdire serait absurde — mais il faut savoir d'où vient le gain de
   longueur médiane : « 75 % suppression / 25 % fusion » et « 25 % / 75 % » ne racontent pas
   la même histoire cartographique.
4. **Lisibilité à 1:10 000** : jugée sur planche, avant/après, capture à l'appui.
5. **Critère hérité re-vérifié** contre la référence FFCO avant d'être traité comme définitif.

---

## 3. Les étapes

### 0 — Audit de la matière première (30 min au total)

**0a — ini KP effectif (10 min).** Lire le `pullauta.ini` du dernier run et le comparer à ce
que `_build_ini` injecte. **Sortie** : paramètres réels (dont le **nombre et les valeurs des
`greenshades`**) connus et épinglés dans `config.yaml`.

**0b — dalles et provenance (10 min).** `pdal info --schema/--stats` : classes présentes,
présence de 65/66, `DTM_MAKER`/`DSM_MAKER`, bornes d'`Intensity`, et **présence de
`PointSourceId` / `ScanAngleRank`** (condition de faisabilité de l'overage).

**0c — le PNG, matière première (10 min).** Pas seulement « les bandes sont-elles visibles ? »
mais : résolution et origine du PGW, nature de l'image (indexée / palette), **histogramme des
tons** (combien de verts distincts, surface par ton, nombre de régions par ton, taille médiane
et plus grande région), présence de blanc / jaune / undergrowth.
**Contrainte de résolution sémantique** : KP calcule la végétation sur une maille de **3 m**
(`greendetectsize=3`), puis restitue l'information dans un PNG à **1 m/pixel** (vérifié :
`_vege.pgw`). La maille de 3 m est donc la **résolution sémantique** effective, sans être la
résolution physique du fichier. Conséquences : (i) les frontières sont en escalier par blocs
de 3 m ; (ii) **une observation statistique = une cellule de 3 m**, pas ses 9 pixels
(cf. protocole 1b).

**Dimensionnement morphologique** : les noyaux se paramètrent en **mètres de terrain**, puis
se convertissent selon la résolution réelle du PNG (`taille_px = 2·(rayon_m / résolution) + 1`)
— c'est ce que fait déjà `_apply_cascade()` dans `scripts/diag/sweep_ordre_lissage.py`. À
1 m/pixel : rayon 1 / 2 / 3 / 4 / 5 m → noyau 3 / 5 / 7 / 9 / 11 px. Un noyau 3×3 px a un
rayon de **1 m** : ce n'est pas un opérateur « sans effet », c'est un opérateur
**sub-cellulaire** (il agit sur le bord d'une cellule de 3 m, pas sur une cellule entière).
**Un noyau 7×7 à 1 m/px (rayon 3 m) est le premier ordre de grandeur permettant de combler une
séparation de l'ordre d'une cellule sémantique entre deux structures.** (La formulation
antérieure — « fusionner deux cellules voisines » — était incorrecte : des cellules voisines se
touchent déjà.) Le mécanisme, tel que Trier le décrit : le *closing* remplit l'espace entre
zones de végétation séparées par **moins que le diamètre du noyau** ; l'*opening* qui suit
retire ce qui est plus mince que ce diamètre. C'est le **diamètre** qui compte : un 7×7 comble
les trous < 7 m à 1 m/px.

> **Ne pas « corriger » la séquence de Trier** pour l'aligner sur la maille de 3 m (7×7 → 9×9) :
> elle n'est pas dérivée de la maille KP. C'est une séquence de généralisation morphologique
> publiée, appliquée par son auteur sur une image **agrégée à 1,0 m** — la même résolution que
> notre PNG. (Note : les légendes de figures de l'article indiquent 1,5 m alors que le texte de
> la méthode dit 1,0 m ; on suit le texte.)

### 1 — Chaîne minimale, bout-en-bout (½ j) — **la première chose à faire**

```
vegetation.png KP
   ↓  (1a) lecture de la palette / des tons
   ↓  (1b) AGRÉGATION DES TONS → CLASSES  (calibrée, pas inventée)
   ↓  (1c) polygonisation
   ↓  (1d) nettoyage minimal (trous, îlots)
kp_vegetation.gpkg  (vege_406 / vege_408 / vege_410)
   ↓  build_kp_vegetation_layers()  →  Layer(nom, code ISOM, géométries)
write_omap()
```

- **1a — lecture** : si le PNG est indexé, exploiter directement la palette plutôt que refaire
  une classification RGB approximative.
- **1b — mapping des tons → classes** : c'est **l'étape centrale**. Sa méthode vient de la
  Phase A de v1, mais **le problème statistique a changé** : on ne cherche plus un seuil sur un
  champ continu (HAG), on cherche une **relation entre des niveaux de teinte ordonnés et une
  classe cartographique** — d'où un protocole durci :
  - **6 à 10 ROIs indépendantes par classe** (406 / 408 / 410) sur le FFCO, homogènes, avec une
    **marge de sécurité paramétrable** : le contour de référence est **érodé** avant
    échantillonnage, `marge = max(6 m ; largeur minimale du symbole)` — soit 6 m — portée à
    **8–10 m** pour les classes les plus sensibles (408/410, petites surfaces). La marge est
    **fixée avant la mesure** ; toute cellule à moins de `marge` du contour FFCO est exclue ;
  - **une observation = une cellule de 3 m** (jamais 9 pixels comme 9 observations
    indépendantes) ;
  - **la FFCO est une référence bruitée, pas une vérité terrain** : ses contours sont déjà
    généralisés par le cartographe et le style varie d'un traceur à l'autre (Trier : « different
    mapping styles by different mapmakers »). On ne cherche donc pas une exactitude au pixel,
    mais une **relation ordonnée et stable** — d'où les distributions complètes, la variance
    inter-ROIs et la validation spatiale, plutôt qu'un simple seuil médian ;
  - **séparation calibration / validation spatiale** : ~70 % des ROIs pour dériver la règle,
    ~30 % **spatialement distinctes** pour la valider (sinon l'autocorrélation spatiale offre
    une performance artificielle) ;
  - **règle d'agrégation figée avant la validation**, puis mesures : matrice de confusion,
    rappel et précision par classe, macro-F1, et surtout **monotonicité** attendue
    (vert clair → 406, moyen → 408, foncé → 410).
  - **Décision écrite d'avance en cas d'échec** : si les distributions se chevauchent trop
    (règle non monotone ou séparation instable entre ROIs de validation), ce **n'est pas un
    problème de réglage** — c'est la démonstration que **le ton KP ne porte pas la sémantique
    406/408/410**. Issue alors, dans cet ordre : (a) réduire à **une seule classe de
    végétation** (la limite extérieure du vert, que le cartographe trace déjà depuis le
    décalque), (b) revenir au signal (étape 6) pour tenter les classes, (c) rester au PNG.
    On ne « rattrape » pas un mapping instable en ajoutant des réglages.
    **Corroboré par la source** : sur ses quatre terrains, Trier mesure, par classe, slow run
    22–52 %, walk 9–40 %, **fight 0–4 %** — et conclut qu'il est « more meaningful to use one
    common class for reduced runability » dans une méthode automatique. L'échec du mapping fin
    n'est donc pas une hypothèse exotique : c'est le résultat de référence. Autre écart à garder
    en tête : ses seuils NDVD dépendent de la densité (2 vs 10 pts/m², table 5) et nos bandes
    sont à **41–85 pts/m²** — un régime qu'il n'explore pas ; nos seuils ne peuvent pas être
    copiés, seulement la méthode.
- **1c/1d — polygonisation et nettoyage** : sans généralisation cartographique à ce stade (elle
  arrive en 2), pour que la chaîne soit vérifiable de bout en bout.
- **Sortie** : un `.omap` expérimental contenant des objets, **en parallèle** du fond PNG qui
  reste le livrable tant que la QA n'est pas passée.
- **Nom du module** : `scripts/kp_vectorize.py` (ou `src/kp_vectorize.py` si appelé par
  `main.py`).

### 2 — Généralisation cartographique compatible ISOM (½ j)

Sur la chaîne 1, **sans changer l'étape 1b** : suppression des objets sous les minima §2.2 →
fusion locale des composantes proches → suppression des trous sous seuil → largeur minimale →
Douglas-Peucker → Chaikin **déjà présents** (`_chaikin_ring`, `cut_isthmes`).
**Contrainte** : opérations **locales et déterministes** (autorisations de l'avenant n°02) ;
pas de moteur de décision.
**Sortie** : re-mesure du critère §2.1 **sur composantes vectorielles** + garde-fous §2.3.

### 3 — Cascade de Trier, sur masques cumulatifs (1 h)

Mêmes étapes que 2, mais l'agrégation se fait sur des **masques cumulatifs** (`M_i = ton ≥
seuil_i`, classes recomposées par différence — `M1 − M2`, `M2 − M3`, `M3`), puis
closing 7 → opening 3 → closing 9 → opening 5 → closing 11 → opening 7.
**Dimensionnement (corrigé, cf. 0c)** : à 1 m/pixel, ces noyaux de Trier valent
**7 / 3 / 9 / 5 / 11 / 7 mètres** de terrain — soit des rayons de 3 / 1 / 4 / 2 / 5 / 3 m.
Ce ne sont donc **pas** des multiples du bloc sémantique de 3 m : la séquence est déjà à la
bonne échelle pour fermer une séparation d'une cellule (~3 m, noyau 7×7) puis nettoyer les
structures d'une demi-cellule (noyau 3×3, sub-cellulaire).
**Protocole comparatif** : à partir de **la même étape 1b** que l'étape 2, sinon on compare
deux chaînes et le gain n'est pas attribuable.
**Écarté d'avance** : la variante « un médian de plus » — déjà mesurée, déjà perdante.

### 4 — Lissage des contours vectoriels (½ j) — **finition, pas levier de fragmentation**

Pistes §12.2/§12.3 du bilan, écrites et jamais testées. **Attendu réaliste** : Chaikin/DP
régularisent les dents et réduisent les sommets ; ils **ne réunissent pas** 20 composantes.
C'est un problème de **topologie** (étape 2/3), pas de **géométrie**. Le lissage vient après la
décision de connectivité, jamais avant.

### 5 — Overage removal (½ j, **conditionnel**)

Seulement si : artefact visible sur le PNG (0c) **et** provenance démontrable (PointSourceId ou
équivalent présent, 0b). Alors : garder par cellule les points de la ligne la plus proche du
nadir (`lasoverage`, essai gratuit sur fenêtre, ou Python), relancer KP, comparer — sur le
**critère** et sur la planche.

### 6 — Signal (dégradé : seulement si 1–4 échouent)

Banc vertical B0–B4 (bandes [0,3–3,0] production, [0,2–2,0] Trier, [1,0–2,65] KP, strates
pondérées). La Phase A « seuils HAG » **n'a plus lieu d'être** sous sa forme v1 : sa méthode
est réutilisée en 1b.

### 7 — Intensité (½ j, en attente d'une décision de contenu)
B1 (`lasoverlap -intensity`) puis B2 (essence vs BD Forêt V2, terrain à deux formations).
Débouché : une **couche** de plus, à juger sur planche. Sans effet sur la vectorisation.

### 8 — Profil vertical (conditionnel, probablement non)

---

## 4. Volet 2 — documenté, non engagé

Symboles ISOM supplémentaires / Feature Map · gap fraction impulsions/retours · validation
externe du sol par MNT/MNH IGN · ratio sur les classes IGN 3/4/5 · filtrage des points virtuels
65/66 · hygiène multi-dalles. **Raison du parcage** : aucun n'a de chemin vers le `.omap`
aujourd'hui.

## 5. Invariants

Paramètres de production (`lightgreentone` 160, `medianboxsize` 9, `medianboxsize2` 16, les
`greenshades`, opacité 50 %, KP 2.12.1) : les étapes mesurent **contre** eux ; le mapping 1b
s'applique **en aval du PNG** et ne les modifie pas — si l'expérience exigeait de rejouer KP
avec d'autres `greenshades`, ce serait une décision séparée. Injection des 406/408/410
**issus du pipeline HAG** : hors périmètre (ce plan injecte ceux issus du **rendu KP**, et c'est
précisément la nouveauté). Trois pistes refermées de v1 : réouverture par mesure nouvelle
seulement. Paramètres = données (avenant n°02 §0 bis).

## 6. Règles d'arrêt

1. Aucune étape ne commence avant que la précédente ait produit son critère.
2. La chaîne minimale (étape 1) passe avant toute optimisation.
3. Généralisation déterministe, locale, configurable.
4. Aucun nouveau document d'exploration tant que le critère n'est pas franchi ou la famille
   épuisée.
5. Si une variante satisfait le chiffre mais dégrade la planche : rejetée.

**Trois échecs instructifs** (structure de falsification, à lire dans cet ordre) :
- **A — mapping OK, géométrie NON** : travailler la généralisation (étapes 2–4).
- **B — mapping NON** : appliquer la branche d'échec de 1b (une classe, sinon signal, sinon PNG).
- **C — chiffres OK, planche mauvaise** : rejet (règle 5), quels que soient les chiffres.

## 7. Risques (révisés après revue externe)

| Risque | Niveau | Étape de réfutation |
|---|---|---|
| Écrire dans le `.omap` (`Layer`, `_polygon_to_xml`) | 🟢 Très faible — **vérifié dans le code** | — |
| Chaîne PNG → polygones | 🟢 Faible | 1 |
| Généraliser sans percolation | 🟠 Moyen — garde-fou `max_pct` existant | 2/3 |
| Atteindre 32 m sans détruire l'information | 🟠/🔴 Élevé | 2/3/4 |
| Le gain de longueur vient de la **suppression** et non de la fusion (chiffre satisfait, carte appauvrie) | 🟠 Moyen — se lit dans la décomposition §2.3.3 | 2/3 |
| **Mapping tons → 406/408/410** | 🔴 **Risque n°1** — mais calibrable sur FFCO, réfutable en heures | 1b |
| Résultat cartographiquement pertinent à 1:10 000 | 🔴 Élevé | planche, à chaque étape |

## 8. Traçabilité

| Décision ou correction | Source |
|---|---|
| Nom et objet du plan | question utilisateur 2026-10-08 ; `main.py::step_assemble` |
| Critère 32 m / 64,5 % et état 16–19 m / 86,0–57,9 % | `docs/bilan_v0.md` §12.1 |
| Garde-fous §2.3 | critique utilisateur ; `src/qa.py` (`max_pct`, garde-fou percolation) |
| Vectorisation obligatoire | décision utilisateur 2026-10-08 |
| Chaîne minimale d'abord ; mapping tons→classes ; masques cumulatifs ; audit 0b/0c élargi ; lissage = finition | revue externe ChatGPT 2026-10-08, 1re passe (§1.8) |
| Dimensionnement des noyaux en mètres ; ROIs + validation tenue à part + monotonicité ; décomposition suppression/fusion ; décision d'échec de 1b | revue externe ChatGPT 2026-10-08, 2e passe (§1.8) |
| Marge de sécurité des ROIs ; FFCO = référence bruitée ; reformulation du noyau 7×7 ; plafond `max_pct` pré-engagé ; nuance « seuils de suppression » ; structure A/B/C | revue externe ChatGPT 2026-10-08, 3e passe (§1.8) |
| Séquence morphologique de Trier et conclusion « une seule classe de runabilité » ; minima de suppression 225 / 112,5 m² à 1:15 000 | Trier 2015, *Automatic mapping of forest density from airborne lidar data* — **vérifié à la source le 2026-10-08** |
| **Minima ISOM 100/49/30 m², largeurs 4/3/2,5 m à 1:10 000** | O-Map Wiki (spec ISOM 2017-2 rev. 6), vérifié aux trois fiches symboles |
| Écarté d'avance : médian supplémentaire | bilan §12.1 (mbs2=16) |
| Cascade de Trier ; résolution sémantique 3 m (`greendetectsize`) | Trier 2015 §2.2 ; KP `src/vegetation.rs` |
| Overage removal | `docs/pistes_entreprises_lidar.md` §2.1 |
| Volet 2 | `docs/pistes_contenu_fichiers_lidar.md`, `docs/pistes_symboles_isom.md` |
