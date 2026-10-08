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

**Surgénierie ? Partiellement, et le §6 le tranche.** Sur les sept étapes du §5, **quatre
n'atteignent pas le `.omap`** : elles servent la classification 406/408/410, qui n'est pas
dans le livrable et dont la vectorisation est suspendue. Le §6 leur oppose un filtre explicite
et réduit le périmètre **engagé** à une demi-journée. Ce qui reste coûteux dans cet avenant
n'est donc pas le plan — c'est la tentation de l'exécuter avant d'avoir décidé si la
vectorisation reprend.

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

La colonne « `.omap` » est le **filtre du §6** : elle indique par quel chemin, s'il existe,
l'étape améliore le fichier livré.

| Ordre | Étape | Coût | Atteint le `.omap` ? | Critère de sortie |
|---|---|---|---|---|
| **0a** | Audit ini KP + épinglage | 10 min | **oui, direct** (ce sont les paramètres du PNG tracé) | les paramètres de production cessent d'être une hypothèse |
| **0b** | Audit du contenu des dalles | 15 min | **oui, préalable** (décide si un nettoyage d'overlap est faisable) | classes réelles, `DTM_MAKER` oui/non, intensité réelle |
| **1** | Banc vertical B0–B4 | ½ j | **non** (améliore notre raster 406/408/410, qui n'est pas dans le `.omap`) | AUC conditionnelle > 0,4919 → le canal n'est plus le plafond |
| **2** | Ordre V5/V6 | 1 h | **peut-être**, en post-traitant le PNG avant assemblage | le témoin de production (médian sur teintes) est défendable ou non |
| **3** | Overage removal | ½ j | **oui, indirect** (nettoie les dalles d'entrée de KP) | contraste de bande réduit **et** PNG au moins aussi lisible à 1:10 000 |
| **4** | **Phase A** — seuils par échantillons | 1 j | **non aujourd'hui** (même raison que l'étape 1) | portage Grimbosq → Sainte-Honorine, contre témoin figé |
| **5** | **B1/B2** intensité | ½ j | **ajout possible** au contenu du `.omap` | séparation essence exploitable ou piste fermée |
| **6** | **Phase C** (profil vertical) | — | non | conditionnelle (§6 du plan, inchangé) |

**Conséquence, dite franchement** : sur les sept étapes, **deux seulement (0a, 0b) sont
certaines d'atteindre le livrable, une (3) en a un chemin indirect, une (2) un chemin
conditionnel**. Les quatre autres servent la classification 406/408/410 — c'est-à-dire la
piste de vectorisation, **suspendue** (longueur médiane 19 m < 32 m ; couverture 57,9 % <
64,5 %). Tant que ce critère n'est pas franchi, ces étapes ne changent rien au `.omap` :
elles doivent donc attendre une décision explicite de relance, pas l'inertie d'un plan.

Deux règles d'arrêt restent en vigueur : **aucune étape ne se commence avant que la
précédente ait produit son critère** ; et si l'arbitrage est entre ce plan et la livraison
(vectorisation, Quick Start), la livraison passe devant.

---

## 6. Filtre — qu'est-ce qui atteint le `.omap` ? (nouveau)

Le livrable `output/<terrain>.omap` contient **exactement** ceci (`main.py::step_assemble`) :

| Contenu | Source | Rôle |
|---|---|---|
| Fond végétation KP (`vegetation.png`, opacité 50 %) | Karttapullautin | **décalque de traçage** — le cartographe trace par-dessus |
| Routes, chemins, bâti, eau | BD TOPO (+ OSM en remplissage) | contenu |
| Courbes de niveau, falaises, buttes | Karttapullautin → DXF → CRT | contenu |
| *(les couches 406/408/410 n'y sont plus — retirées du livrable)* | — | — |

**Règle d'engagement** (c'est la règle de l'avenant n°02 §0 appliquée au livrable) :

> Une piste ne s'engage que si elle nomme son chemin vers ce tableau — soit elle **améliore le
> PNG** (paramètres, ordre, nettoyage des dalles d'entrée), soit elle **ajoute une couche**
> jugée utile sur une planche, soit elle **franchit le critère de vectorisation** (longueur
> médiane ≥ 32 m **et** couverture ≤ 10 m ≥ 64,5 %). À défaut : volet 2, sans exception.

Vérification, piste par piste :

| Piste | Chemin vers le `.omap` | Verdict |
|---|---|---|
| Audit ini KP | les paramètres produisent le PNG tracé | **engagée (10 min)** |
| Audit du contenu des dalles | conditionne le nettoyage d'overlap | **engagée (15 min)** |
| Overage removal | nettoie les dalles d'entrée → PNG (et notre raster) | **engagée sous condition** : jugement à 1:10 000 sur le PNG, avant/après |
| V5/V6 (ordre) | post-traitement possible du PNG avant assemblage | **engagée (1 h)** — mais seul un mieux **vu sur planche** la retient |
| Banc vertical, Phase A | améliorent notre raster, pas le PNG | **en attente** : dépend de la relance de la vectorisation |
| B1/B2 intensité | couche d'essence en décalque supplémentaire | **en attente** : décision de contenu, sur planche |
| Couche-indice ISOM, gap fraction, MNT/MNH, classes IGN 3/4/5, filtrage 65/66, doublons | aucun aujourd'hui | **volet 2** |

**Conséquence opérationnelle** : le périmètre réellement engagé tient en **une demi-journée**
(0a + 0b + test d'overage + V5/V6). Tout le reste attend la décision « on relance la
vectorisation, ou on livre le fond de traçage en l'état ». C'est cette décision, pas une
nouvelle piste, qui débloque la suite.

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
| Question « qu'est-ce que ça apporte au `.omap` ? » (2026-10-08) | §6 : filtre d'engagement, colonne `.omap` au §5, périmètre engagé réduit à ½ j |

---

## 9. Références

`docs/revue_plan_signaux_lidar.md` · `docs/pistes_contenu_fichiers_lidar.md` ·
`docs/pistes_entreprises_lidar.md` · `docs/pistes_symboles_isom.md` ·
`docs/archive/PLAN_signaux_lidar_inexploites_2026-10-08.md` · `docs/bilan_v0.md` (§5, §7, §14,
réf. 15) · `docs/test_intensite.md` · `docs/archive/CONSIGNE_intensite_406_v2.md` ·
`docs/archive/avenant_02_omapmaker.md` (règle « paramètres = données ») ·
`scripts/diag/sweep_ordre_lissage.py` (V5/V6).
