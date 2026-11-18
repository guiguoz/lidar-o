# Lidar'O — Plan V2 pour améliorer la détection et la représentation de la végétation

## 1. Objectif général

L'objectif prioritaire n'est pas de maximiser la bonne classification des zones en 406 / 408 / 410.

La priorité métier est :

> **B > A >>> C**
>
> **B — obtenir des contours qui ressemblent à ceux d'une vraie carte de course d'orientation**  
> **A — retrouver au maximum la surface des taches**  
> **C — obtenir directement le bon vert**

Le problème est donc traité en priorité comme un **problème de segmentation, de géométrie et de représentation cartographique**, plus que comme un simple problème de classification.

### Besoin cartographique

Lors d'une reprise de carte, changer une zone de 406 en 408 ou 410 est relativement rapide. En revanche, redessiner manuellement le contour d'une « tache de vert » est coûteux en temps.

Lidar'O doit donc chercher à produire d'abord :

- des **taches de végétation géométriquement crédibles** ;
- une mosaïque de petites zones correspondant aux variations locales du sous-bois ;
- des contours simples, stables, lisibles et cartographiques ;
- une classe 406 / 408 / 410 qui reste facilement modifiable sans redessiner la géométrie.

---

## 2. Principe directeur de la V2

Le changement fondamental proposé est de **séparer trois problèmes** :

```text
A — Où sont les zones ?
    → segmentation

B — Où passe leur frontière ?
    → optimisation géométrique / cartographique

C — Quel symbole leur attribuer ?
    → classification 406 / 408 / 410
```

Pour le développement actuel :

```text
A + B >>> C
```

La classe ne doit donc plus être responsable directement de la géométrie.

### Architecture cible

```text
                         LiDAR
                           │
                    features structurées
                           │
                    régions primitives
                           │
                 segmentation hiérarchique
                           │
             ┌─────────────┴─────────────┐
             │                           │
       fidélité au signal         simplicité de forme
             │                           │
             └─────────────┬─────────────┘
                           │
                    patches carto
                           │
                   classification
                     406 / 408 / 410
                           │
                     export OMAP
```

---

## 3. Autocritique des approches initiales

Plusieurs idées initiales restent pertinentes, mais elles doivent être repositionnées.

### 3.1 Ne pas faire de la segmentation multi-échelle une vérité absolue

La stabilité à plusieurs échelles est une information utile, mais une petite zone parfaitement cartographique peut disparaître lorsqu'on augmente trop la résolution d'analyse.

Donc :

```text
stabilité multi-échelle ≠ vérité
```

Elle doit être une **feature parmi d'autres**, au même titre que l'homogénéité, le contraste avec les voisins ou la forme.

### 3.2 Ne pas utiliser une simple aire minimale comme filtre principal

Une surface minimale fixe ne suffit pas à caractériser une forme cartographique.

Deux objets de surface comparable peuvent être très différents :

```text
10 × 20 m → forme plausible
5 × 50 m  → forme potentiellement aberrante
```

Il faut donc tenir compte de :

- surface ;
- largeur minimale ;
- allongement ;
- compacité ;
- largeur des étranglements ;
- complexité du contour.

### 3.3 Ne pas multiplier les algorithmes trop tôt

Le plan ne doit pas devenir une succession de tests sans protocole.

Les trois familles prioritaires sont :

1. **Region Growing** — baseline simple et interprétable ;
2. **Superpixels + RAG** — contrôle fin de la granularité ;
3. **Segmentation par graphe hiérarchique** — candidat plus avancé.

Watershed peut servir de **benchmark**, mais pas de branche principale de développement au départ.

---

## 4. Pourquoi le pipeline actuel atteint ses limites

Le pipeline actuel suit essentiellement :

```text
LiDAR
  ↓
HAG / indicateurs dérivés
  ↓
seuils 406 / 408 / 410
  ↓
masques raster
  ↓
polygonisation
  ↓
dissolve / fusion / suppression de petits objets / chirurgie d'isthmes
  ↓
lissage / généralisation
  ↓
export cartographique
```

Le problème est que la géométrie des polygones est en grande partie héritée du seuillage du champ HAG.

Conséquences observées dans les expérimentations V0 :

- contours trop directement liés aux fluctuations du signal ;
- formes trop détaillées ou ramifiées ;
- zones artificiellement reliées par de petits couloirs ;
- difficulté à obtenir la granularité d'une carte CO par des opérations de généralisation tardives ;
- baisse du rappel lorsqu'on monte les seuils et augmentation des faux positifs lorsqu'on les baisse ;
- impossibilité de récupérer certaines zones de 406 uniquement à partir du HAG.

Conclusion : **continuer à régler uniquement les seuils, le lissage ou les opérations de chirurgie géométrique n'attaque pas suffisamment le problème fondamental.**

---

## 5. Nouveau pipeline expérimental

Le pipeline cible doit d'abord produire une représentation intermédiaire riche avant la classe finale.

```text
LiDAR
 ↓
construction des features
 ↓
segmentation primitive
 ↓
graphe de voisinage
 ↓
fusion hiérarchique
 ↓
optimisation cartographique
 ↓
patches de végétation
 ↓
classification 406/408/410
 ↓
export cartographique
```

### Règle de développement

Ne pas modifier immédiatement le pipeline de production.

Créer d'abord un moteur expérimental indépendant, par exemple :

```text
scripts/vegetation_segmentation_experiment.py
```

Entrée :

```text
raster(s) HAG / features existantes
```

Sorties :

```text
veg_features/
boundary_score.tif
stability.tif
segments.gpkg
segments_preview.png
metrics.json
```

Une fois une méthode validée sur les 5 terrains, seulement alors intégrer progressivement le résultat dans le pipeline principal.

---

## 6. Phase 1 — Définir mathématiquement ce qu'est une bonne tache

Les 5 couples de cartes disponibles constituent le premier corpus de référence :

1. Grimbosq
2. Monthureux
3. Luxeuil
4. Bouhard
5. Bas des Conches

Les images officielles et les sorties Lidar'O ne sont pas toujours géoréférencées de façon identique. Ce n'est pas bloquant pour cette phase.

### Objectif

Mesurer sur les cartes officielles les propriétés morphologiques des zones de végétation :

- distribution des surfaces ;
- largeur typique et largeur minimale ;
- périmètre / surface ;
- compacité ;
- allongement ;
- complexité du contour ;
- densité de patches ;
- distance entre patches ;
- fréquence des petits îlots ;
- taille et fréquence des étranglements ;
- éventuelle hiérarchie de tailles.

Le but n'est pas de dire « telle forme est vraie » individuellement, mais de déterminer **la distribution statistique du style cartographique observé**.

### Important

Cette phase doit également mesurer séparément :

```text
surface de végétation
vs.
qualité de sa partition en patches
```

Une couverture correcte avec une mauvaise géométrie ne doit pas être considérée comme un bon résultat.

---

## 7. Phase 2 — Construire des features LiDAR plus riches

Ne pas réduire trop tôt l'information à un unique `veg_score`.

Conserver les composantes séparément autant que possible.

### Features verticales minimales

```text
Density 0.3–1.0 m
Density 1.0–2.0 m
Density 2.0–3.0 m
Density 0.3–3.0 m
```

### Features locales

Calculées sur plusieurs fenêtres, par exemple :

```text
mean 5 m
mean 10 m
std 5 m
std 10 m
gradient 5 m
```

Les tailles exactes restent à calibrer sur les 5 terrains.

### Features de transition

Ajouter :

```text
boundary_strength
transition_width
stability
```

`transition_width` est importante : une transition sur 1 m n'est pas équivalente à une transition progressive sur 15 m.

Dans une transition large, il peut ne pas exister de « vraie » frontière physique ; l'objectif devient alors de choisir une **frontière cartographiquement raisonnable**.

### Sorties raster proposées

```text
features/
├── density_030_100.tif
├── density_100_200.tif
├── density_200_300.tif
├── density_030_300.tif
├── mean_5m.tif
├── mean_10m.tif
├── std_5m.tif
├── std_10m.tif
├── gradient_5m.tif
├── boundary_strength.tif
├── transition_width.tif
└── stability.tif
```

---

## 8. Phase 3 — Sur-segmentation en régions primitives

Il ne faut pas passer directement du raster à quelques gros polygones.

Créer d'abord des **petites régions cohérentes**, volontairement plus nombreuses que nécessaire.

```text
raster
 ↓
sur-segmentation
 ↓
petites régions
```

Puis conserver leurs propriétés :

```text
region_id
geometry
surface
features moyennes
variance interne
```

L'avantage est de pouvoir ensuite fusionner les régions sans perdre leur structure initiale.

---

## 9. Phase 4 — Graphe de voisinage et segmentation hiérarchique

Construire un Region Adjacency Graph (RAG) :

```text
       A ─── B ─── C
       │     │     │
       D ─── E ─── F
```

Pour chaque paire de voisins, enregistrer notamment :

```text
shared_boundary
mean feature difference
boundary_strength
relative_size
transition_width
```

### Fusion hiérarchique

Fusionner progressivement deux régions lorsque leur union est suffisamment cohérente.

Produire plusieurs niveaux de découpage :

```text
LOD 0 → peu de patches
LOD 1 → granularité intermédiaire
LOD 2 → granularité fine
LOD 3 → très fin
```

Cette hiérarchie permet de rechercher quelle granularité ressemble le mieux au comportement des cartes officielles.

---

## 10. Trois algorithmes candidats

### A — Region Growing

Baseline très simple.

Des zones « graines » très sûres sont identifiées ; la croissance continue tant que la différence locale reste acceptable.

Les seuils servent donc de **graines / critères de croissance**, et non de frontières rigides.

### B — Superpixels + RAG

Créer des superpixels adaptés à la texture du raster, puis fusionner les régions via leur graphe de voisinage.

Avantages recherchés :

- contrôle de la granularité ;
- régions compactes ;
- méthode facilement visualisable ;
- possibilité de produire plusieurs LOD.

### C — Segmentation par graphe hiérarchique

Utiliser un graphe de régions avec un coût de fusion combinant :

```text
homogénéité interne
+ différence entre voisins
+ stabilité
+ coût géométrique
```

C'est le candidat potentiellement le plus puissant, mais il ne doit être développé que si les deux baselines montrent leurs limites.

### Watershed

À tester seulement comme référence comparative pour vérifier si une segmentation guidée par gradient apporte quelque chose. Ne pas en faire la solution principale par défaut.

---

## 11. Phase 5 — Définir une frontière cartographique

C'est un élément central de la V2.

Une frontière ne doit pas être définie simplement comme :

```text
position du gradient maximal
```

Elle doit être évaluée comme une frontière :

- suffisamment fidèle au signal ;
- suffisamment stable ;
- peu sinueuse ;
- ne créant pas de petits appendices inutiles ;
- ne créant pas de couloirs artificiels ;
- compatible avec une largeur minimale plausible.

### Deux niveaux de score

#### Score local

```text
boundary_strength
```

Mesure la force de la transition de part et d'autre.

#### Coût global de frontière

```text
boundary_cost =
    faible fidélité
  + complexité du contour
  + sinuosité
  + petits détours
  + mauvais effet sur la forme des patches
```

On cherche donc non pas la frontière la plus proche du signal, mais **la meilleure frontière globale**.

---

## 12. Principe fondamental : fidélité vs simplicité cartographique

Le moteur doit explicitement considérer un compromis :

```text
qualité = fidélité au signal - λ × complexité géométrique
```

Conceptuellement :

```text
λ faible
→ suivre davantage le LiDAR

λ élevé
→ privilégier des contours plus simples
```

Exemple conceptuel :

```text
signal brut :
~~~~/\~~/~~~~
~~/~~~\/~~~~~

représentation cartographique :
─────────────
```

Le but n'est pas de lisser arbitrairement le polygone à la fin, mais de **faire intervenir la simplicité pendant la construction du patch**.

---

## 13. Contraintes morphologiques

Remplacer la logique « aire minimale » par plusieurs critères.

### Surface

Éviter les objets ridiculement petits, mais sans imposer une valeur unique trop forte.

### Largeur

Contrôler :

```text
minimum_width
```

### Étranglements

Détecter les petits « isthmes » qui créent des connexions artificielles.

### Allongement

Une forme très longue et mince peut être suspecte même si sa surface est importante.

### Compacité

Utiliser notamment des indicateurs du type :

```text
P² / A
```

pour pénaliser les contours excessivement complexes.

---

## 14. Les patches doivent rester indépendants de leur classe

Une fois les patches obtenus :

```text
patch_id = 1842
geometry = ...
```

on peut leur associer :

```text
class = 406
```

puis modifier simplement :

```text
class = 408
```

sans recalculer la géométrie.

### Modèle de données cible

```text
patch_id
geometry
vegetation_features
class
class_confidence
stability
boundary_confidence
```

Cette séparation est fondamentale pour réduire le temps de reprise manuelle.

---

## 15. Classification 406 / 408 / 410 — seulement après la géométrie

Une fois les patches construits, calculer leurs statistiques internes :

```text
mean density
median density
quantiles
vertical profile
texture
heterogeneity
neighborhood
```

Puis attribuer :

```text
patch → 406 / 408 / 410
```

La classe doit être accompagnée d'une confiance.

Exemple :

```text
Patch A → 408 — confiance 0.94
Patch B → 408 — confiance 0.63
Patch C → 406 — confiance 0.55
Patch D → 410 — confiance 0.98
```

Cela permet de concentrer l'intervention humaine sur les zones ambiguës.

### Conséquence importante

Certaines zones 406 ne seront probablement jamais récupérables à partir du HAG seul. Les expérimentations V0 montrent que, sur Grimbosq, certaines zones 406 ont une signature HAG trop proche du blanc.

Il ne faut donc pas dégrader toute la géométrie dans le but de forcer leur récupération.

---

## 16. Mesurer la performance de la bonne manière

La métrique principale ne doit pas être la seule accuracy 406/408/410.

### Niveau 1 — Couverture

```text
vegetation recall
```

### Niveau 2 — Géométrie

Mesurer notamment :

```text
boundary precision / recall
boundary F-score
Chamfer distance
distance moyenne entre contours
```

### Niveau 3 — Morphologie

Comparer les distributions :

```text
surface
largeur
compacité
allongement
complexité
patches / hectare
```

entre la carte officielle et la sortie Lidar'O.

### Niveau 4 — Coût de retouche humaine

C'est la métrique métier la plus importante.

Objectif : estimer :

```text
% de contour conservable
nombre / longueur des corrections nécessaires
nombre de patches à redessiner
nombre de patches seulement à recolorer
```

Un résultat avec une classe moins précise mais des contours presque directement utilisables peut être supérieur à un résultat avec une meilleure classification et des contours à refaire.

---

## 17. Nouvelle métrique centrale : le coût de retouche

Exemple conceptuel :

```text
Algorithme A
84 % de surface retrouvée
72 % de classes correctes
14 000 m de contour à reprendre

Algorithme B
75 % de surface retrouvée
43 % de classes correctes
3 500 m de contour à reprendre
```

Pour Lidar'O, B peut être nettement préférable.

Le développement doit donc chercher à **minimiser le travail humain final**, pas simplement à maximiser la ressemblance pixel par pixel.

---

## 18. Utilisation des cinq cartes de référence

Le corpus actuel :

```text
1 — Grimbosq
2 — Monthureux
3 — Luxeuil
4 — Bouhard
5 — Bas des Conches
```

Pour chaque terrain :

```text
carte officielle
    ↓
extraction / analyse morphologique
    ↓
statistiques de patches
```

Puis construire des distributions globales :

```text
surface
largeur
compacité
complexité
densité
voisinage
```

Ces statistiques serviront à régler la segmentation.

### Alignement imparfait

Les cartes n'étant pas systématiquement géoréférencées de façon identique, l'évaluation des formes peut d'abord être faite sur les propriétés morphologiques globales et, lorsque possible, sur des sous-zones réalignées.

Pour aller plus loin, quelques cas avec raster LiDAR intermédiaire géoréférencé seraient très utiles.

---

## 19. Protocole expérimental recommandé

### Étape 1 — Analyse des cartes officielles

Produire un rapport :

```text
reference_morphology.json
```

avec les distributions caractéristiques.

### Étape 2 — Baseline actuelle

Faire passer les 5 terrains dans le pipeline Lidar'O actuel et enregistrer les mêmes métriques.

Cela crée un **point de référence objectif**.

### Étape 3 — Première segmentation

Tester seulement :

```text
Region Growing
Superpixels + RAG
Graph segmentation
```

à partir des mêmes features LiDAR.

### Étape 4 — Tester plusieurs granularités

```text
LOD 0
LOD 1
LOD 2
LOD 3
```

Comparer chaque niveau au profil morphologique officiel.

### Étape 5 — Introduire la régularisation géométrique

Tester plusieurs valeurs de `λ` :

```text
λ = 0
λ = faible
λ = moyen
λ = fort
```

Chercher une zone où la fidélité au signal baisse légèrement mais la qualité cartographique progresse fortement.

### Étape 6 — Comparaison multi-terrain

Une méthode ne doit être retenue que si elle améliore globalement le corpus, et pas seulement un terrain.

### Étape 7 — Classification

Ajouter 406/408/410 seulement après validation de la géométrie.

### Étape 8 — Intégration

Seulement après validation :

```text
segmentation expérimentale
→ vegetation.py
→ export OMAP
```

---

## 20. Sorties expérimentales à prévoir

Pour permettre l'analyse dans QGIS et le diagnostic :

```text
experiment/
├── features/
│   ├── ...tif
├── boundary_strength.tif
├── transition_width.tif
├── stability.tif
├── primitive_regions.gpkg
├── segmentation_lod0.gpkg
├── segmentation_lod1.gpkg
├── segmentation_lod2.gpkg
├── segmentation_lod3.gpkg
├── candidate_patches.gpkg
├── preview_official.png
├── preview_lidar_o.png
└── metrics.json
```

Le principe est de toujours pouvoir répondre à la question :

> **Pourquoi ce contour a-t-il été créé ici ?**

---

## 21. Ce qui ne doit plus être la priorité

Ne pas consacrer de gros efforts, à ce stade, à :

- chercher un seuil 406 universel ;
- multiplier les passes de lissage Gaussian ;
- augmenter indéfiniment `fusion_distance` ;
- multiplier les passes Chaikin ;
- ajouter des chirurgies géométriques successives ;
- optimiser séparément chaque type de vert avant d'avoir une bonne géométrie.

Ces techniques peuvent rester utiles comme finitions, mais elles interviennent trop tard pour résoudre la cause principale du problème.

---

## 22. Hypothèse centrale à tester

L'hypothèse de travail de la V2 est :

> **Les meilleures zones de végétation cartographique ne correspondent pas exactement aux isolignes d'un seuil HAG. Elles correspondent à une partition spatiale de la forêt qui conserve suffisamment d'information LiDAR tout en imposant une simplicité géométrique comparable à celle d'un dessin cartographique humain.**

Cette hypothèse doit être considérée comme falsifiable.

Elle sera validée ou rejetée sur les 5 terrains de référence.

---

## 23. Critère de réussite de Lidar'O V2

Le succès ne sera pas :

> « Lidar'O retrouve exactement les pixels verts de la carte officielle. »

Le succès sera plutôt :

> **« Lidar'O fournit une mosaïque de patches dont les contours sont suffisamment proches de ceux d'une carte CO pour que le cartographe puisse principalement les conserver et modifier leur classe, au lieu de les redessiner. »**

Ordre de priorité :

```text
1. qualité des contours
2. qualité de la partition en patches
3. couverture des zones pertinentes
4. bonne classe 406/408/410
```

---

## 24. Prochaine expérimentation recommandée

Ne pas coder immédiatement toute la V2.

Commencer par un petit prototype qui fait seulement :

```text
HAG / features
 ↓
sur-segmentation
 ↓
RAG
 ↓
fusion hiérarchique
 ↓
patches
```

et produit des visualisations comparant :

```text
Carte officielle
vs.
Lidar'O actuel
vs.
nouvelle segmentation
```

avec, pour chaque résultat, les métriques morphologiques et le coût estimé de retouche.

Si cette première étape montre que la segmentation produit des formes réellement plus proches du langage cartographique, les autres éléments — frontière optimisée, stabilité, classification et export — pourront être ajoutés progressivement.

---

## 25. Résumé exécutif

### Aujourd'hui

```text
LiDAR → seuils → masques → polygones → chirurgie géométrique → carte
```

### V2 visée

```text
LiDAR
 ↓
features
 ↓
sur-segmentation
 ↓
RAG / régions
 ↓
fusion hiérarchique
 ↓
optimisation fidélité ↔ simplicité
 ↓
patches cartographiques
 ↓
classification 406/408/410
 ↓
OMAP
```

### Idée clé

> **Ne plus demander au seuil de dessiner la tache.**
>
> Le signal LiDAR doit aider à déterminer les régions et leurs frontières, mais une contrainte explicite de simplicité et de plausibilité cartographique doit décider de la géométrie finale.

### Métrique clé

> **Combien de travail humain faut-il encore pour obtenir une carte utilisable ?**

C'est cette métrique, plus que l'accuracy brute des classes, qui doit guider les choix d'algorithmes de Lidar'O V2.
