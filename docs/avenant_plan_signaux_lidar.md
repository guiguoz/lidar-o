> **SUPERSEDED (2026-10-08)** — cet avenant est remplacé par le plan consolidé
> [`docs/PLAN_v2_du_decalque_au_calque.md`](PLAN_v2_du_decalque_au_calque.md). Il est conservé
> comme trace de la séquence de décisions (prémisses corrigées, filtre `.omap`, ordre v2).
> En cas de conflit, le plan v2 prime.

---

# Avenant n°01 au plan « Signaux LiDAR inexploités »

**Objet :** mettre à jour le plan du 2026-10-08 à la lumière des trois revues qui l'ont suivi
(`docs/revue_plan_signaux_lidar.md`, `docs/pistes_contenu_fichiers_lidar.md`,
`docs/pistes_entreprises_lidar.md`), et fixer l'ordre de travail qui en découle.
**S'applique à :** `docs/archive/PLAN_signaux_lidar_inexploites_2026-10-08.md`.
**Préséance :** en cas de conflit, cet avenant prime sur le plan.
**Esprit :** comme l'avenant n°02 du plan d'exécution — il **réduit** le périmètre, il
n'ajoute pas d'infrastructure. Aucune phase du plan n'est supprimée ; trois prémisses sont
corrigées, deux questions sont tranchées, et cinq travaux préalables sont insérés.

---

## 0. Réponse à la question posée

**Non, il ne faut pas un nouveau plan** : la structure du plan (Phase A « seuils par
échantillons », Phase B « intensité », Phase C « profil vertical », la distinction
mesure/décision du §2) reste la bonne, et son autocritique (§8) est renforcée par ce qu'on a
trouvé, pas affaiblie.

**Oui, une mise à jour est nécessaire** — sur cinq points précis (§1 à §5). Sans elle, le
plan **démarre par la Phase A**, qui est la plus chère et la plus prématurée : elle calibre
des seuils sur un canal dont les bornes sont en question, avec un témoin (les paramètres KP)
dont on ne sait pas ce qu'il contient réellement.

Le coût de la mise à jour est de **~1,5 à 2 jours**, et il réduit le risque de refaire la
Phase A deux fois.

**Décision du 2026-10-08 : la vectorisation est obligatoire en aval, quelle que soit la
situation.** L'alternative « livrer le fond de traçage seul » est donc écartée, et avec elle
la formulation en « ou bien / ou bien » : le critère de vectorisation (longueur médiane ≥ 32 m
**et** couverture ≤ 10 m ≥ 64,5 %) n'est plus une porte à rouvrir, c'est **l'objectif à
atteindre**. Conséquence directe sur le §5 : les étapes qui « n'atteignaient pas le `.omap` »
y atteignent désormais **par la vectorisation**, et l'ordre est réordonné par leur effet sur
la métrique qui échoue — pas par leur effet sur l'AUC.

**Ce que la mesure dit de cette métrique** (bilan §12.1) : sur la voie « vectoriser le rendu
KP », la **couverture passe déjà** (mbs2=1 : 86,0 % pour un seuil de 64,5 %) ; c'est la
**longueur médiane de composante** qui échoue (16 m, puis 19 m avec mbs2=16, pour 32 m
requis). Autrement dit, le problème bloquant est la **fragmentation**, pas la fidélité des
limites — donc un problème de **forme**, et le seul levier de ce type déjà mesuré (le filtre
médian) est un mauvais levier : il gagne 3 m de longueur et perd **28 points** de couverture.
Un réglage global ne peut pas satisfaire les deux conditions ; il faut une généralisation
**consciente de la forme** (fusion des taches proches puis nettoyage des formes fines), pas un
flou global. C'est exactement la famille non mesurée : cascade de Trier au niveau raster,
minimums ISOM et lissage de contours au niveau polygone.

---

## 1. Trois prémisses corrigées, deux confirmées

| # | Prémisse du plan | Verdict après vérification | Conséquence |
|---|---|---|---|
| 1 | « L'intensité n'a jamais été lue » | **Inexacte** : réfutation n°15, `docs/test_intensite.md` (AUC 0,3638 vs blanc, r angulaire 0,0339) | Ce qui s'ouvre en B2 est **l'essence** (feuillus/résineux), pas la franchissabilité — la population d'échantillonnage change (canopée, pas bande) |
| 2 | La NDVD est « déjà reproduite via omapmaker, rien de nouveau » | **Plus fort que dit** : avec `NDVD = (V−G)/(V+G)` et notre `ratio = bande/(bande+dessous)`, **NDVD = 2·ratio − 1** ; et `ratio` ≡ `NRD` à 0,0006 près (bilan §5) | La NDVD n'est **pas un levier** : c'est la validation externe de notre métrique. Le levier est la **calibration** (seuils ±1, banc vertical), pas la formule |
| 3 | Les paramètres de production KP sont « ceux du §10 » | **Non vérifiable en l'état** : `_build_ini` n'injecte que `lightgreentone` et `medianboxsize2` ; `greenshades` (obligatoire pour KP), `medianboxsize`, les facteurs de retour vivent dans un `pullauta.ini` **non versionné**, réécrit à chaque run | Un **audit de 10 min** devient la première tâche : on ne dérive pas des seuils contre un témoin inconnu |

Confirmées telles quelles : les seuils OCAD se calculent par échantillons (*Statistics*) ;
les défauts OCAD sont assumés comme réglés sur **une** forêt suisse (Steinhauserwald) — ce qui
valide la démarche de la Phase A ; et la « Feature Map » est bien une image d'indices à 0,5 m
sur points non-sol, pas une couche de symboles.

---

## 2. Ce qui change, paragraphe par paragraphe

| § du plan | Modification |
|---|---|
| **§1** (canaux) | Corriger la ligne `Intensity` ; ajouter deux lignes : **classes IGN 3/4/5** (calculées par l'IGN, jamais lues) et **65/66** (points virtuels et artefacts, comptés sans filtre dans `total_count` et le HAG) |
| **§2** (transposition) | Requalifier : la transposition n'est pas seulement « dériver les seuils de la donnée » — Trier fait aussi une **cascade morphologique progressive** (7-3-9-5-11-7) après seuillage. Les deux volets sont testables séparément |
| **§3.1** (NDVD) | Remplacer « rien de nouveau à implémenter » par « notre métrique est déjà la NDVD à une transformation affine près : la question est la calibration ». La plage **±1** et les seuils publiés par densité (Trier, tab. 5) deviennent la référence de lecture |
| **§3.3** (carte d'intensité) | Requalifier : c'est **l'essence**, pas la franchissabilité ; et le test de comparabilité (§5 du plan) a maintenant un outil : `lasoverlap -intensity` |
| **§5 B1** | **Débloquée** : `lasoverlap -intensity` (essai gratuit sur une fenêtre) donne le raster des écarts inter-lignes. La clôture V0 donne déjà r = 0,0339 comme point de départ |
| **§5 B2** | Ajouter une **condition de faisabilité** : vérifier par BD Forêt V2 (WFS `LANDCOVER.FORESTINVENTORY.V2`, déjà accessible) que la dalle d'essai porte **deux formations** (feuillus/résineux ≥ 10 ha chacune). Grimbosq est feuillus, Airelles résineux : le contraste ne se mesure pas dans un seul massif |
| **§7** (ordre seuil/généralisation) | **Tranchée par la source** : Trier seuille puis généralise (cascade), Cassini généralise puis seuille. V5 (ordre KP) et V6 (cascade de Trier) sont **déjà implémentés et testés** dans `scripts/diag/sweep_ordre_lissage.py` (22 tests) — il ne reste qu'à les exécuter sur les données |
| **§9** (ordre) | Remplacé par l'ordre du §5 ci-dessous |
| **§8 et §10** | **Inchangés**, et renforcés : l'autocritique reste valide ; le §10 gagne une condition préalable (épingler l'ini effectif, cf. §1.3) |

---

## 3. Ce que le plan n'avait pas et qui entre dans le périmètre (volet 1)

Cinq travaux qui servent directement A et B, tous adossés à une mesure :

1. **Audit de l'ini KP effectif** (10 min) — `grep` sur le `pullauta.ini` du dernier run ;
   épinglage dans `config.yaml` (règle « paramètres = données », avenant n°02 §0 bis).
2. **Audit du contenu des dalles** (15 min) — schéma PDAL, histogramme des classes, présence
   de `DTM_MAKER`/`DSM_MAKER`, bornes d'intensité. C'est lui qui décide si la correction
   d'overlap est possible en une ligne.
3. **Banc vertical B0–B4** (½ j) — bandes [0,3–3,0] (production), [0,2–2,0] (Trier),
   [0,3–2,0], [1,0–2,65] (zone KP), et 3 strates pondérées. Comparateurs : AUC conditionnelle
   (plancher 0,4919), AUC inter-classes, contraste de bande.
4. **Ordre de généralisation V5/V6** (1 h) — déjà codé, aucune donnée nouvelle.
5. **Overage removal** (½ j) — garder par cellule les points de la ligne de vol la plus
   proche du nadir (`lasoverage` d'essai, ou Python sur la dalle). **Se substitue à la
   variante lourde du multi-looks (L2)** : même question, réponse du métier, plus simple.

## 4. Ce qui reste **hors** plan (volet 2 — documenté, non engagé)

Parquer ici, sans les supprimer : couche-indice ISOM façon *Feature Map*
(`docs/pistes_symboles_isom.md`, ½–1 j) ; **gap fraction** impulsions/retours (½–1 j) ;
validation externe du sol par MNT/MNH IGN (½ j) ; ratio sur les classes IGN 3/4/5 (2 h) ;
filtrage des points virtuels 65/66 (1 h) ; hygiène multi-dalles / doublons de bord (1 h).

**Raison du parcage** : §9 du plan — « ce plan explore, il ne livre pas ». Ces six pistes sont
réelles et documentées, mais aucune ne conditionne A ou B ; les engager maintenant ferait
glisser le projet vers une seconde campagne d'exploration alors que la vectorisation et le
Quick Start restent, eux, des livrables.

---

## 5. Ordre de travail mis à jour (remplace le §9 du plan)

**Version 2 de l'ordre (vectorisation obligatoire).** Le critère de vectorisation devient le
critère de sortie des étapes 1 à 3 ; l'AUC ne reprend la main qu'à partir de l'étape 5. La
vérification « quelle piste atteint le `.omap` » est au §6.

| Ordre | Étape | Coût | Critère de sortie |
|---|---|---|---|
| **0a** | Audit ini KP + épinglage | 10 min | paramètres réels du PNG connus |
| **0b** | Audit du contenu des dalles | 15 min | classes réelles, `DTM_MAKER`, intensité |
| **1** | **Vectorisation des aplats KP + généralisation ISOM** (`docs/iof_generalization_rules.md` : 406/401 ≈ 50 m², 408 ≈ 30 m², 410 ≈ 20 m², trous, Douglas-Peucker/Chaikin existants) | ½ j | **longueur médiane ≥ 32 m** et couverture ≤ 10 m **≥ 64,5 %** |
| **2** | Ordre V5/V6 — cascade de Trier au niveau raster | 1 h | la matière première fournie à l'étape 1 s'améliore (longueur médiane), sans perdre la couverture |
| **3** | Lissage des contours vectoriels (§12.2 du bilan, non testé) + niveaux de lissage multiples (§12.3) | ½ j | critère franchi ou famille épuisée |
| **4** | Overage removal | ½ j | contraste de bande réduit **et** PNG au moins aussi lisible à 1:10 000 |
| **5** | Banc vertical B0–B4, puis **Phase A** | ½ + 1 j | AUC conditionnelle > 0,4919 (signal) ; n'est engagé que si 1–3 échouent encore |
| **6** | B1/B2 intensité | ½ j | séparation essence exploitable ou piste fermée |
| **7** | Phase C (profil vertical) | — | conditionnelle (§6 du plan, inchangé) |

**Pourquoi le signal passe après la forme** : la mesure disponible dit que le blocage est la
fragmentation (16/19 m contre 32 m requis) alors que la couverture est déjà franchie (86 %).
Or les 15 leviers de signal et les 9 leviers de forme testés portaient respectivement sur
`density_hag` et sur les polygones du pipeline HAG — **aucun des deux n'est la voie retenue
pour la vectorisation** (rendu KP → polygones). Les leviers réellement non mesurés sont donc
ceux des étapes 1 à 3. Engager le banc vertical avant eux serait reproduire le raisonnement
que le §6 vient de corriger.

Deux règles restent en vigueur : **aucune étape ne se commence avant que la précédente ait
produit son critère** ; et la généralisation polygonale doit rester **déterministe et
configurable** (opérations locales de fusion/proximité, simplification, suppression par
surface) — c'est ce que l'avenant n°02 autorise explicitement, et ce n'est pas un « moteur de
généralisation ».

---

## 6. Filtre — qu'est-ce qui atteint le `.omap` ? (nouveau)

Le livrable `output/<terrain>.omap` contient **exactement** ceci (`main.py::step_assemble`) :

| Contenu | Source | Rôle |
|---|---|---|
| Fond végétation KP (`vegetation.png`, opacité 50 %) | Karttapullautin | **décalque de traçage** — le cartographe trace par-dessus |
| Routes, chemins, bâti, eau | BD TOPO (+ OSM en remplissage) | contenu |
| Courbes de niveau, falaises, buttes | Karttapullautin → DXF → CRT | contenu |
| *(les couches 406/408/410 n'y sont plus — retirées du livrable)* | — | — |

**Règle d'engagement, version 2** (la vectorisation étant obligatoire, le critère n'est plus
une option mais la condition de sortie) :

> Une piste ne s'engage que si elle nomme son chemin vers ce tableau — soit elle **améliore le
> PNG** (paramètres, ordre, nettoyage des dalles d'entrée), soit elle **conduit à des polygones
> qui franchissent le critère** (longueur médiane ≥ 32 m **et** couverture ≤ 10 m ≥ 64,5 %),
> soit elle **ajoute une couche** jugée utile sur une planche. À défaut : volet 2, sans
> exception.

Vérification, piste par piste :

| Piste | Chemin vers le `.omap` | Verdict |
|---|---|---|
| Audit ini KP | les paramètres produisent le PNG tracé | **engagée (10 min)** |
| Audit du contenu des dalles | conditionne le nettoyage d'overlap | **engagée (15 min)** |
| Overage removal | nettoie les dalles d'entrée → PNG (et notre raster) | **engagée sous condition** : jugement à 1:10 000 sur le PNG, avant/après |
| V5/V6 (ordre) | post-traitement possible du PNG avant assemblage | **engagée (1 h)** — mais seul un mieux **vu sur planche** la retient |
| Vectorisation des aplats KP + généralisation ISOM | produit directement les polygones du `.omap` | **engagée (½ j)** — étape 1 |
| Lissage de contours (§12.2/§12.3) | idem, sur les polygones | **engagée si 1–2 échouent (½ j)** |
| Banc vertical, Phase A | améliorent le signal ; utiles seulement si la fragmentation est un symptôme de limites mal placées | **dégradée** : après 1–3, et seulement si le critère échoue encore |
| B1/B2 intensité | couche d'essence en décalque supplémentaire | **en attente** : décision de contenu, sur planche |
| Couche-indice ISOM, gap fraction, MNT/MNH, classes IGN 3/4/5, filtrage 65/66, doublons | aucun aujourd'hui | **volet 2** |

**Conséquence opérationnelle** : le périmètre engagé tient en **une demi-journée à une
journée** (0a + 0b + étape 1, avec 2 et 3 en réserve). Ces trois étapes ont en commun de
n'exiger **aucune donnée nouvelle** : elles partent du PNG et des polygones déjà produits.

---

## 7. Invariants (le §10 du plan, confirmé)

Paramètres de production (`lightgreentone` 160, `medianboxsize` 9, `medianboxsize2` 16, les
onze `greenshades`, opacité 50 %, KP 2.12.1) : chaque phase mesure **contre** eux, aucune ne
les remplace sans jugement cartographique sur une planche. Injection des polygones
406/408/410 dans l'`.omap` : hors périmètre. Les trois pistes refermées du §1 : refermées —
réouverture **seulement** par une mesure nouvelle, jamais par la citation d'un logiciel qui
fait autrement.

---

## 8. Traçabilité — quelle observation a produit quel changement

| Observation (source) | Changement |
|---|---|
| `docs/test_intensite.md` + bilan réf. 15 | §1.1 : ligne `Intensity` corrigée |
| Trier 2015, éq. 1 + bilan §5 (0,0006) | §1.2 : NDVD requalifiée en validation |
| `src/run_engine.py` + KP `config.rs` + `.gitignore` | §1.3 : audit de l'ini en tâche 0a |
| Trier 2015 §2.2 (cascade) + KP/Cassini | §7 tranchée ; V5/V6 implémentés |
| IGN 2025 (`DTM_MAKER`) + OCAD « Overlap Points » + `lasoverage` | §3.5 : overage removal entre dans le plan |
| IGN (11 classes) + lecture du code | §3.2 : audit du contenu en tâche 0b |
| IGN MNT/MNS/MNH + BD Forêt V2 | §4 : volet 2 parqué (validation sol, classes 3/4/5) |
| NV5 (polygones 0,45–1,8 m) + OCAD Feature Map | §4 : couche-indice parquée |
| MapAnt / bulle CO bénévole | §4 : « pas de concurrent à battre », priorité au livrable |
| Question « qu'est-ce que ça apporte au `.omap` ? » (2026-10-08) | §6 : filtre d'engagement |
| **Décision : vectorisation obligatoire en aval** (2026-10-08) | §0 : l'alternative est close, le critère devient l'objectif ; §5 : ordre v2, forme avant signal ; §6 : règle d'engagement v2 |

---

## 9. Références

`docs/revue_plan_signaux_lidar.md` · `docs/pistes_contenu_fichiers_lidar.md` ·
`docs/pistes_entreprises_lidar.md` · `docs/pistes_symboles_isom.md` ·
`docs/archive/PLAN_signaux_lidar_inexploites_2026-10-08.md` · `docs/bilan_v0.md` (§5, §7, §14,
réf. 15) · `docs/test_intensite.md` · `docs/archive/CONSIGNE_intensite_406_v2.md` ·
`docs/archive/avenant_02_omapmaker.md` (règle « paramètres = données ») ·
`scripts/diag/sweep_ordre_lissage.py` (V5/V6).
