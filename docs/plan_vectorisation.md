# PLAN 2 — Vectoriser le raster KP en végétation `.omap` modifiable

> **Brief destiné à Claude Code (ou tout exécutant).** Autonome.
> **Prérequis de lecture :** `docs/protocole_vectorisation_kp.md` (le protocole adopté,
> ses preuves et ses limites) — ce plan n'en répète pas le contenu, il ordonne **ce qui
> reste à faire** après le commit `47e01eb` (2026-09-30).
> **Indépendance :** ce plan est exécutable **sans** le plan 1
> (`docs/plan_amelioration_raster.md`) ; les anciennes marques « P1-Phase n » sont des
> branches mortes : **au 2026-10-02, le plan 1 est clos sans modification de
> production** (undergrowth, OVL, sous-bois).
> **Interdit :** nouveau vectoriseur (CoVe/potrace/graphe de frontières — écartés,
> protocole §3), ML/scoring, modification des étapes 1–9 du moteur sans mesure corpus.
> **Veille vectorisation pro (Illustrator, cartes O réelles, ISOM, OCAD, LivElox) : §5** —
> références conceptuelles et comparateurs ; jamais portes, jamais dépendances.
> **Statut v3 (2026-10-02) :** réécrit sur revue utilisateur — calibration supprimée
> de V1 (fidélité = round-trip), polygonisation topologique isolée en V2,
> simplification de couverture en V3, rôle de la veille réduit.
> **Question unique du plan :** le même contenu que `vegetation.png` peut-il devenir
> des objets `.omap` propres et éditables ?

---

## 1. Ce qui est déjà fait (ne pas le refaire)

| Fait | Où |
|---|---|
| Pont raster KP → raster classifié (DN 85/170/255), lecture bit/indexé/RGB, mosaïque sur classes, garde-fous | `src/kp_raster.py` + 20 tests `tests/test_kp_raster.py` |
| `vege_bitmode=1` écrit dans le `pullauta.ini` généré | `src/run_engine.py` |
| Source `kp` câblée : vegetation / mask / assemble ; couches veg_406/408/410 injectées en objets ; template piloté par `keep_template` | `main.py` |
| Étape 10 `coverage_partition` (partition plane 410>408>406, chevauchements → 0) | `src/vegetation.py` |
| Calibration teinte→ISOM par couverture : `python -m src.kp_raster report` | `src/kp_raster.py` |
| Démo sans données + figure 3 panneaux + `.omap` contrôlé | `scripts/diag/demo_vectorisation_kp.py`, `docs/images/demo_vectorisation_kp.png` |
| Bugs pré-existants corrigés : SyntaxError `run_engine._build_ini`, double remapping de ton `_merge_vege_tiles` | commits |

**Lisibilité (confusion signalée le 2026-10-02) :** les commits de ce tableau
(dont `47e01eb`) vivent sur la branche `arena/01a0f111-lidar-o`, **non fusionnée
dans `main`** : un checkout de `main` ne montre ni `src/kp_raster.py` ni ces
commits. Le plan cible la branche de session.

**Vérifications de revue (2026-10-02) :** constantes de palette KP vérifiées
ligne par ligne contre `src/palette.rs` (karttapullautin/karttapullautin, clone
du 2026-10-02) : Yellow2 = (255, 219, 166) indice 3 ✓ ; GREEN_SHADE_PALETTE_OFFSET
= 16 → premier vert indice 16 ✓. Bug mosaic (offset source non calculé quand la
bbox rogne la tuile à l'ouest/nord) **corrigé** avec test de régression
(échec avant correctif, succès après) ; structure `shade_to_isom` déjà documentée
en commentaire dans `config.yaml`, pointeur ajouté dans la docstring de
`build_class_raster`.

## 2. Tâches restantes, dans l'ordre

### V1 — Prouver la fidélité raster → classes → vecteurs

**Objectif : ne modifier aucune information du raster KP.**

Le raster source retenu est `vegetation.png` / `vege_bit`. Mécanique du décodage
(code, 2026-10-02) :

```text
vege_bit.png      teintes, valeurs bit 2 à 8 (7 teintes actives, greenshades défaut)
shade_to_isom     config, gelée : teintes → classes, many-to-one (fait partie du décodage)
sortie du pont    DN 85 / 170 / 255 = 406 / 408 / 410 (fixé par construction)
```

Le mapping étant many-to-one, il est sous-déterminé : son placement actuel est
**gelé comme définition du décodage** (motif : ordre des greenshades = ordre de
pénétrabilité), identique sur tous les terrains. V1 le prouve exact ; **V1 n'y
touche pas**. Tout replacement futur = sujet séparé à porte propre (planche),
hors de ce plan.

Le travail de V1 n'est donc **pas de calibrer ces correspondances sur la
couverture des cartes de référence**. Il consiste à démontrer que le décodage
utilisé par `kp_raster.py` restitue exactement les classes présentes dans le
raster source.

### Test

Sur un extrait réel de Grimbosq :

```text
vegetation.png / vege_bit
    ↓
décodage gelé (shade_to_isom → DN)
    ↓
raster catégoriel 0 / 406 / 408 / 410
    ↓
polygonisation (sans simplification ni filtrage)
    ↓
rasterisation de nouveau sur la grille source
```

Comparer le raster reconstitué au raster catégoriel de départ **pixel par
pixel**.

Mesurer :

```text
pixels différents
pixels 406/408/410 perdus
pixels ajoutés
surface différente
```

**Convention :** rasterisation sur la même grille, même règle de bord de pixel
que la polygonisation ; convention documentée dans le rapport. Toute différence
hors convention = bug.

**Porte V1 : round-trip raster = vecteur = raster.**

La cible est :

```text
0 pixel différent
```

à condition que la vectorisation soit effectuée sans simplification ni filtrage
des micro-polygones.

Si une différence apparaît, l'expérience s'arrête : on corrige la brique de
polygonisation avant d'aller plus loin.

### Ce que V1 ne fait PAS

Ne pas utiliser `qa_targets` (19,3 / 6,9 / 8,0 %) pour déplacer des coupures.
Ces valeurs peuvent être rapportées comme **contrôle descriptif**, mais elles ne
définissent pas la correspondance des classes.

Ne pas créer de `shade_to_isom` dépendant du terrain : le décodage est
identique sur tous les terrains (contrôle de palette en V7).

### Sorties

```text
work/expe/vectorisation/
├── source_classes.tif
├── vectorized_raw.gpkg
├── roundtrip.tif
└── v1_roundtrip_report.md
```

(`work/` gitignoré, convention du repo.)

---

### V2 — Polygonisation topologiquement fidèle

À partir du raster catégoriel exact validé par V1 :

```text
0 / 406 / 408 / 410
        ↓
polygonisation unique
        ↓
dissolve par classe
        ↓
vérification topologique
```

Les frontières entre classes doivent être issues de la **même grille source**.

Invariant :

```text
aucun chevauchement
aucune lacune géométrique artificielle
```

Un espace correspondant à des pixels `0` est légitime.

Un espace créé entre deux polygones alors que les pixels adjacents étaient tous
végétalisés est une erreur — **mesurée par le round-trip** (pixels differents là
où la source était végétalisée).

Les trous internes doivent être conservés.

### Porte V2

Sur les données réelles :

```text
chevauchements = 0
slivers artificiels = 0
round-trip identique
```

Aucune simplification ni suppression de micro-polygones n'est encore autorisée.

---

### V3 — Simplification de couverture

**Objectif : rendre les géométries éditables sans détruire la topologie.**

Ne pas appliquer de Douglas-Peucker indépendamment à chaque polygone.

Ne pas appliquer Chaikin indépendamment à chaque polygone après
`coverage_simplify` : cela recréerait précisément les divergences de frontières
que V2 a supprimées. **Une arête partagée se traite une fois.**

### Expérience contrôlée

Comparer :

```text
A — géométrie brute (sortie de V2)
B — coverage_simplify (GEOS ≥ 3.12, shapely 2.1 ; couverture traitée comme un tout)
C — B + lissage seulement si ce lissage agit sur la couverture entière
    et conserve les arêtes partagées — candidat : Chaikin appliqué une fois
    par arête partagée (graphe de frontières, nœuds/arêtes), variante
    coins verrouillés (S1) en sous-variante
```

La variable étudiée est uniquement la simplification.

`coverage_simplify` est la référence topologique.

### Variante « coins »

L'observation issue d'Illustrator reste intéressante : les angles peuvent être
préservés plutôt qu'arrondis.

Cette variante ne doit être testée que si elle peut être appliquée **à la
couverture entière** sans casser les frontières partagées.

Sinon :

```text
variante coins = abandonnée
```

et ce résultat est documenté.

### Mesures

Avant / après :

```text
nombre de sommets
nombre de polygones
aire médiane
% d'objets < 1 mm² à l'échelle de la carte
longueur totale des frontières
distribution des angles
chevauchements
lacunes / slivers
perte de généralisation (pixels différents vs raster catégoriel avant
simplification, rapportée par bras)
```

### Acceptation

Pas de seuil arbitraire isolé.

La simplification n'est retenue que si :

```text
topologie conservée (chevauchements = 0, lacunes = 0)
+
round-trip suffisamment fidèle (perte de généralisation rapportée,
aucun seuil caché)
+
réduction géométrique réellement utile à l'édition
```

**L'utilité à l'édition se juge sur planche 1:10 000 avant/après par bras,
regardée par un humain (R1).** Le gain de sommets est une mesure informative.
Le critère « −30 % » de la version précédente reste comme **objectif
expérimental à observer**, pas comme condition unique de validation.
Test de topologie dans `tests/test_vegetation.py` : couverture à frontières
partagées, intersections deux à deux = 0, somme des aires = aire de la
couverture.

---

### V4 — Vérification OOM de bout en bout

Construire le `.omap` réel à partir des vecteurs issus de V2/V3 :

```text
406
408
410
```

et conserver le template KP comme couche de fond.

Vérifier dans OpenOrienteering Mapper :

```text
sélection des objets par classe
présence des trois symboles
géométrie et anneaux intérieurs
absence d'objets hors emprise
ouverture du fichier
temps d'ouverture
taille du fichier
```

Produire deux versions :

```text
keep_template = true
keep_template = false
```

La seconde vérifie que les vecteurs sont réellement autonomes.

**Ce n'est pas une décision sur l'utilisation du template :** le template reste
le fond de décalque retenu du workflow actuel.

### Mode dégradé

Si OOM n'est pas disponible :

```text
validation XML
+
comptes d'objets par symbole
+
bbox
+
géoréférencement
+
round-trip raster
+
planche 1:10 000
```

La validation OOM reste recommandée mais non bloquante.

### Acceptation

```text
.omap valide
+
406/408/410 sélectionnables
+
aucun objet orphelin
+
géoréférencement correct
```

---

### V5 — Couche `propose409`

**CLOS.**

La porte 1 du plan undergrowth et la Phase 0 du canal sous-bois ont toutes deux
fermé cette piste.

Il n'existe donc :

```text
ni canal undergrowth
ni couche propose409
ni autre source à tester pour rouvrir ce sujet
```

La section est conservée uniquement pour mémoire documentaire.

La sémantique ISOM reste documentée (note de clôture dans `docs/bilan_v0.md` :
409 = « Vegetation: walk, good visibility », pas de surface « undergrowth »
dans ISOM 2017-2), mais aucune implémentation 409 ne doit être ajoutée dans ce
plan.

L'étalonnage éventuel par traces GPS est traité uniquement en V6 comme
information sur les classes existantes 406/408/410.

---

### V6 — Contrôle comparatif du résultat vectorisé

Objectif : vérifier que le livrable vectoriel issu de KP est exploitable
cartographiquement.

Sur Grimbosq :

```text
source KP
    ↓
vectorisation fidèle
    ↓
généralisation éventuelle
    ↓
.omap
```

Produire :

```text
table QA
planche 1:10 000
```

Mesures :

```text
nombre d'objets par classe
distribution des aires
sommets
chevauchements
slivers
distance aux limites FFCO
```

Les mesures utilisant FFCO restent **informatives**.

### Comparaison avec le pipeline PDAL

La chaîne PDAL actuellement abandonnée du livrable peut être conservée comme
comparateur historique si elle est encore exécutable.

Sinon :

```text
KP vectorisé
+
référence humaine S3
+
contrôles géométriques
```

suffisent.

**Ne pas réintroduire PDAL dans le livrable simplement pour avoir un deuxième
candidat.**

### Référence professionnelle S3

Ajouter la carte humaine de Grimbosq (déc. 2015, JPG sans tracés,
géoréférencement 3 points) comme panneau de comparaison visuelle.

Elle sert de :

```text
référence cartographique
```

et non de vérité pixel par pixel.

### S4 / ISOM

Utiliser les dimensions minimales ISOM et les fonctions de contrôle de
lisibilité comme **indicateurs de généralisation** :

```text
objet trop petit
largeur insuffisante
isthme trop fin
```

Ils ne décident jamais seuls de la suppression d'une forme : le cartographe
garde la décision finale.

### S5 / GPS

Si des traces LivElox / 3D Rerun existent et que leur utilisation est autorisée
(accord des organisateurs) :

```text
agrégation par classe existante (406/408/410)
→ comparaison des vitesses
```

uniquement comme contrôle informatif.

Aucune trace individuelle n'est republiée et aucune porte ne dépend de cette
mesure.

### Acceptation

```text
table + planche commitées
+
documentation de ce que le vectoriel KP permet réellement
+
pas de prétention à une classification automatique parfaite
```

---

### V7 — Portabilité sur un second terrain

Reproduire la chaîne **V1 → V4** sur un second terrain normand dans le domaine
ciblé.

Objectif principal :

> vérifier que la brique de vectorisation et le décodage des classes KP restent
> valides hors de Grimbosq.

Mesurer :

```text
round-trip
nombre d'objets
distribution des aires
sommets
topologie
taille du .omap
```

Si le mode bit reste utilisé :

> **aucune recalibration terrain n'est attendue pour la correspondance
> teintes → classes → DN** — **si la palette KP (greenshades) est identique** ;
> contrôle de palette à l'arrivée ; palette différente = sujet séparé à porte.

Une différence de répartition des surfaces entre terrains est un résultat sur
les données KP, pas une raison de déplacer des coupures.

Kuti / Kilemaed / Airelles restent hors domaine sauf comparaison explicitement
annoncée.

### Acceptation

```text
round-trip valide
+
topologie valide
+
.omap exploitable
```

sur le terrain 2.

---

### V8 — Consolidation documentaire

Mettre à jour :

```text
docs/bilan_v0.md
docs/protocole_vectorisation_kp.md
README
```

Le protocole ne doit plus présenter comme résultats réels les chiffres
provenant de la démo synthétique.

Il doit distinguer explicitement :

```text
mesuré sur données réelles
mesuré sur données synthétiques
valeur issue de la documentation externe
hypothèse non validée
```

Ajouter une annexe :

```text
valeurs gelées
```

avec notamment :

```text
mode de décodage KP (teintes bit 2–8, shade_to_isom gelée, DN 85/170/255)
classes 406/408/410
règles topologiques (arêtes partagées traitées une fois)
méthode de simplification retenue
paramètres effectivement validés
```

Le README ne mentionne une recommandation de configuration que si elle découle
d'un résultat réel documenté.

---

## 3. Contraintes transversales

- Toute modification du moteur = mesure corpus avant/après avec
  `scripts/measure_corpus.py` + commit séparé.
- Aucun changement de deux briques cartographiques dans le même commit.
- Les paramètres expérimentaux vivent dans `work/`.
- Seules les planches de décision et documentations validées sont commitées ;
  planches de décision en `docs/images/` seulement au commit de verdict (R2).
- Tout nouveau comportement possède un test.
- `coverage_simplify` doit être testé explicitement sur une couverture comportant
  des frontières partagées.
- Le test de round-trip raster est un invariant de la brique de vectorisation.
- Les seuils de généralisation vivent dans `config.yaml`
  (`generalization.profiles.*`) ; aucune valeur par terrain attendue (V1/V7).
- OCAD / Illustrator / autres logiciels propriétaires restent des **comparateurs
  conceptuels ou externes**, jamais des dépendances.
- Les données GPS ne servent qu'à des statistiques agrégées et ne constituent
  jamais une porte.
- Les trois tests préexistants en échec sur `main` (`test_init_terrain` check,
  georef 450 000 vs 449 000) restent hors périmètre et ne doivent pas être
  réparés dans ce plan.

## 4. Definition of done

1. **Fidélité :** round-trip raster → vecteur → raster validé sur ≥ 2 terrains.
2. **Topologie :** aucune superposition ni lacune artificielle après la
   vectorisation retenue.
3. **Édition :** `.omap` ouvrable dans OOM, objets 406/408/410 sélectionnables.
4. **Généralisation :** méthode choisie et documentée, sans destruction de la
   topologie.
5. **Documentation :** aucun chiffre synthétique présenté comme mesure réelle ;
   valeurs gelées et limites explicitement séparées.

## 5. Veille — stratégies de vectorisation pro (2026-10-01, rôle réduit au 2026-10-02)

**Rôle réduit :** références conceptuelles et comparateurs — jamais portes,
jamais dépendances. La question unique du plan reste : le même contenu que
`vegetation.png` peut-il devenir des objets `.omap` propres et éditables ?
S1 apporte l'idée Corners (V3) ; S2 le vocabulaire de généralisation (V3/V6) ;
S3 la référence humaine (V6) ; S4–S6 des pratiques de contrôle et d'édition
(V6, OOM) ; S7 une référence de méthode KP (notre moteur).

| # | Stratégie | Source | Intégration |
|---|---|---|---|
| S1 | **Image Trace** (Illustrator) : 5 réglages — Threshold, Paths (fidélité), Corners (préservation des angles), Noise (nombre minimal de pixels adjacents ignorés), Ignore White (fond) — puis nettoyage pro : `Object > Path > Simplify` (« le minimum de points qui tient la forme »), alignement des ancres vacillants (Direct Selection + Align), `Clean up` des objets non peints | helpx.adobe.com « Image tracing presets » ; tutoriels pro | Équivalents déjà présents : Threshold = greenshades (gelé), Noise = aire mini ISOM (V6), Ignore White = fond, Clean up = contrôle orphelins (V4). **Apport : Corners → variante de V3**, testée seulement si applicable à la couverture entière, sinon abandon documenté |
| S2 | **ISOM 2017-2 §2.6** : la généralisation a deux phases — *sélective* (choisir ce qu'on représente ; dimensions mini adoptées dès le relevé) et *graphique* (simplification, déplacement, exagération). « La lisibilité ne doit jamais être sacrifiée pour représenter un excès de détails » ; la cohérence entre cartes est une qualité première ; **les frontières nettes entre types de végétation sont des points de repère du lecteur** | ISOM 2017-2, PDF bilingue FFCO (mars 2022) ; baoc.org | Vocabulaire et critères de V6 ; V2/V3 : la topologie (0 chevauchement, 0 lacune, frontières partagées) est une exigence ISOM, pas seulement une propreté interne |
| S3 | **Carte pro du même terrain** : Grimbosq la Motte, 6 déc. 2015 — « One-man relais RDE » et « WE RDE court-long » (CO Pédestre / Orientation Caennaise ; collection Axel Pannier). JPG **sans tracés** téléchargeable ; worldofo ne publie **aucun fichier vectoriel** | omaps.worldofo.com id 159467/159468 → doma go78.org | V6 : panneau de référence supplémentaire (géoréférencement 3 points) ; comparaison visuelle uniquement, pas de statistiques de polygones |
| S4 | **OCAD contrôle les dimensions mini IOF pendant le dessin** (indicateur vert/rouge + % trop petit), en plus de Check Legibility Space en fin de carte ; le mapper du WOC 2025 (Janne Weckman, ~50 km² dont 20 km² WOC) l'utilise en contrôle final | ocad.com/blog (tag ISOM 2017 ; interview Weckman) | V6 : indicateurs de généralisation (jamais arbitres) ; référence pour l'édition manuelle dans OOM : « dessiner assez grand ou omettre » |
| S5 | **LivElox / 3D Rerun** : traces GPS téléchargeables (GPX), allures par patte ; runnability IOF = plages de vitesse (blanc ≈ 100 %, 406 slow running, 408 walk, 410 fight, 411 impassable ≈ 0–20 %) mais « there is no precise way of measuring runnability — c'est un jugement du cartographe » | livelox.com/documentation ; bko.org.uk KYS-Vegetation.pdf | V6 : allure agrégée par classes existantes (406/408/410) = contrôle de vitesse **informatif** (accord organisateurs requis ; données personnelles : agrégats seulement) ; confirme R1. N'informe plus de placement de coupures : V1 n'en place pas |
| S6 | **OOM pro workflow** : `Edit > Find` par tag d'objet → sélection groupée → `Convert to object` (utilisé p. ex. pour réaffecter les courbes importées de Karttapullautin) | attackpoint.org (Jagge) | Pratique d'édition OOM : mémoire V5 (pas de propose409) ; utilisable par le cartographe sur toute couche à la reprise |
| S7 | **Karttapullautin = KP, notre propre outil** (auteur Jarkko Ryyppä, « Jagge ») : réglage conseillé — clip représentatif contenant tous les types de vert, `greenshades` à 3–4 valeurs + `99` pour sauter une nuance, éclaircissage sans effet ≥ 2 pts/m² ; **« benchmark patches »** (JWOC 2015) : cercles à végétation connue → histogrammes LiDAR → étalonnage — code privé, **absent du KP public** (vérifié par grep) | attackpoint.org ; orienteeringbc.ca ; whorienteers.net | Pas un comparateur (c'est notre moteur) : conseils de réglage valides pour tout run KP ; « benchmark patches » = prior informatif **si** le mapping gelé est un jour replacé — sujet séparé à porte, hors de ce plan |
