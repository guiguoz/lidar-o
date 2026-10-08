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

**Correction v2** : le critère de sortie des trois premières étapes est le critère de
vectorisation lui-même ; le signal (banc vertical, Phase A) passe en étape 5 et ne s'engage
que si la forme échoue encore.

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
  §5). C'est la validation externe de notre métrique, pas un levier. Le levier, s'il existe,
  est la **calibration** (seuils ±1, banc vertical).

### 1.4 L'erreur d'auteur : mon avenant n°01 a réduit le périmètre au lieu de réordonner

L'avenant que j'ai écrit hier soir quantifiait la suringénierie (« périmètre engagé : ½ j »)
mais **conservait la vectorisation comme une option suspendue** — il a donc fallu une décision
explicite pour remettre le livrable en tête. Leçon inscrite ici : *un avenant qui réduit le
périmètre sans demander « qu'est-ce qui produit le fichier ? » ne fait que reporter le
problème.*

### 1.5 Le critère lui-même est critiquable (nouveau)

Le critère `longueur médiane ≥ 32 m` **et** `couverture ≤ 10 m ≥ 64,5 %` est un critère
**géométrique**. Il peut être satisfait en **aplatissant** : fusionner tout en grosses masses
allonge les composantes et peut même améliorer la couverture, en détruisant l'information
cartographique. Un plan qui optimise un tel critère sans garde-fou fabrique un beau chiffre et
une mauvaise carte.

**Correction v2** — trois garde-fous, appliqués à chaque variante :
1. la **surface totale** et la **répartition par ton** restent dans ±20 % de l'état actuel
   (pas d'aplatissement) ;
2. **lisibilité à 1:10 000** jugée sur planche, avant/après, documentée par une capture ;
3. le critère hérité (32 m / 64,5 %) est **re-vérifié sur la référence FFCO** avant d'être
   traité comme une cible définitive — il vient du bilan §12.1, pas d'une spécification ISOM.

### 1.6 Ce qui reste incertain, et qui est le vrai risque du plan

| Hypothèse | Statut | Comment on la tue vite |
|---|---|---|
| La généralisation ISOM (surfaces minimales + fusion + simplification) suffit à passer de 16–19 m à 32 m | **NON TESTÉ — c'est l'hypothèse centrale** | étape 1, ½ j |
| Le PNG KP porte l'artefact de bande (mesuré sur **notre** raster : 84,6 vs 41,2 pts/m², jamais sur le PNG) | **NON TESTÉ** | regarder le PNG à 1:10 000 : 5 min |
| La cascade de Trier (closing/opening progressifs) défragmente sans aplatir | **NON TESTÉ sur le PNG** — mais testable sans PDAL | étape 2, 1 h |
| Le signal (banc vertical) est nécessaire derrière | **NON TESTÉ — hypothèse parquée** | seulement si 1–3 échouent |

### 1.7 Autocritique de rythme

Quatre documents ont été produits en une journée (revue, symboles, contenu des fichiers,
entreprises). C'est de la documentation utile, mais **le plan v2 s'interdit d'en produire un
cinquième** avant que le critère soit franchi ou que la famille soit épuisée. La règle du
projet — « une idée ne s'engage que si elle supprime une étape, réduit la complexité ou
améliore objectivement le résultat » — vaut aussi pour les documents.

---

## 2. Le critère (écrit avant mesure, avec ses garde-fous)

**Critère de vectorisation, hérité du bilan §12.1 :**

| Condition | Seuil | État actuel |
|---|---|---|
| Longueur médiane d'une composante | ≥ **32 m** | 16 m (mbs2=1) · 19 m (mbs2=16) — **ÉCHEC** |
| Couverture ≤ 10 m | ≥ **64,5 %** | 86,0 % (mbs2=1) · 57,9 % (mbs2=16) |

**Lecture** : une seule des deux conditions échoue sur la variante non lissée — la
**fragmentation**. Le seul levier mesuré de ce type (le filtre médian) est un mauvais levier :
+3 m de longueur pour **−28 points** de couverture. Un réglage global ne peut pas satisfaire
les deux conditions : il faut une généralisation **consciente de la forme**.

**Garde-fous (§1.5)** : surfaces et répartition par ton à ±20 % ; lisibilité à 1:10 000 sur
planche ; seuils re-vérifiés sur la référence FFCO.

---

## 3. Les étapes

### 0a — Audit de l'ini KP effectif (10 min)
Lire le `pullauta.ini` du dernier run (`work/pullauta.ini`, `out_kp_*/pullauta.ini`) et
comparer à ce que `_build_ini` injecte. Épingler les valeurs réelles dans `config.yaml` et les
injecter explicitement. **Sortie** : les paramètres de production cessent d'être une hypothèse.

### 0b — Audit du contenu des dalles (15 min)
`pdal info --schema` / `--stats` sur une dalle : classes présentes et effectifs, présence de
65/66, de `DTM_MAKER`/`DSM_MAKER`, bornes réelles d'`Intensity`. **Sortie** : décide si les
étapes 4 et 6 sont possibles.

### 0c — Regarder le PNG (5 min)
Ouvrir `vegetation.png` de Grimbosq à 1:10 000 : les bandes de vol sont-elles visibles sur le
rendu ? **Sortie** : l'étape 4 existe ou est close en cinq minutes.

### 1 — Vectoriser les aplats KP, puis généraliser selon l'ISOM (½ j) — **étape charnière**
- **Entrée** : `vegetation.png` (par dalle), déjà classé par KP.
- **Traitement** : segmentation en tons → polygonisation → nettoyage (trous, îlots) →
  **suppression des objets sous les surfaces minimales ISOM** (`docs/iof_generalization_rules.md` :
  406/401 ≈ 50 m², 408 ≈ 30 m², 410 ≈ 20 m² à 1:10 000) → fusion des composantes proches →
  simplification (Douglas-Peucker) et lissage **déjà présents** (`_chaikin_ring`).
- **Contrainte de conformité** : opérations **locales et déterministes** (fusion par proximité,
  simplification, suppression par surface) — autorisées par l'avenant n°02 ; pas de moteur de
  décision.
- **Sortie** : polygones + mesure du critère §2 sur les trois garde-fous.

### 2 — Cascade de Trier sur les tons du PNG (1 h)
Fermetures/ouvertures progressives (7-3-9-5-11-7 px), appliquées **par ton** sur l'image, puis
re-polygonisation. C'est la réponse de la littérature à la fragmentation (§2.2 de Trier 2015),
et elle est **applicable sans PDAL**.
- **Écarté d'avance** : la variante « un médian de plus » (famille `medianboxsize2`) — déjà
  mesurée, déjà perdante (57,9 % de couverture). Ne pas la refaire sous un autre nom.

### 3 — Lissage des contours vectoriels (½ j)
Piste §12.2 et §12.3 du bilan, **écrites et jamais testées** : lissage géométrique des
contours (pas du raster), et niveaux de lissage multiples (grandes masses vs lisières).
Dernier levier de **forme** non mesuré.

### 4 — Overage removal (½ j, conditionnel à 0c)
Si le PNG montre les bandes : garder par cellule les points de la ligne de vol la plus proche
du nadir (`lasoverage`, essai gratuit sur fenêtre, ou Python), relancer KP, comparer.
La réponse standard du métier (TerraMatch, Esri, LAStools, OCAD) à l'artefact mesuré.

### 5 — Signal (½ j + 1 j, **dégradé** : seulement si 1–3 échouent)
Banc vertical B0–B4 (bandes [0,3–3,0] production, [0,2–2,0] Trier, [1,0–2,65] KP, strates
pondérées), puis Phase A (seuils par échantillons, **sur notre indice continu** — KP n'exporte
pas son indice). Ces étapes améliorent notre raster ; elles ne servent la vectorisation que si
la fragmentation est un symptôme de limites mal placées.

### 6 — Intensité (½ j, en attente d'une décision de contenu)
B1 (comparabilité, `lasoverlap -intensity`) puis B2 (essence vs BD Forêt V2, sur un terrain
portant les deux formations). Débouché : une **couche** de plus dans le `.omap`, à juger sur
planche. Aucun effet sur la vectorisation.

### 7 — Profil vertical (conditionnel, probablement non)
Profil complet en tranches de 20 cm comparé à des profils de référence. Inchangé depuis v1 §6.

---

## 4. Volet 2 — documenté, non engagé

Symboles ISOM supplémentaires / Feature Map (`docs/pistes_symboles_isom.md`) · gap fraction
impulsions/retours · validation externe du sol par MNT/MNH IGN · ratio sur les classes IGN
3/4/5 · filtrage des points virtuels 65/66 · hygiène multi-dalles (doublons de bord).
**Raison du parcage, inchangée** : aucun n'a de chemin vers le `.omap` aujourd'hui.

## 5. Invariants (inchangés, confirmés)

Paramètres de production (`lightgreentone` 160, `medianboxsize` 9, `medianboxsize2` 16, les
onze `greenshades`, opacité 50 %, KP 2.12.1) : les étapes mesurent **contre** eux ; aucune ne
les remplace sans jugement cartographique sur planche. Injection des 406/408/410 dans le
`.omap` : hors périmètre. Les trois pistes refermées du §1 de v1 (sous-bois, `voxeldownsize`,
ratio de classification) : réouverture **seulement** par une mesure nouvelle. Paramètres =
données (avenant n°02 §0 bis).

## 6. Règles d'arrêt

1. Aucune étape ne commence avant que la précédente ait produit son critère.
2. La généralisation reste déterministe et configurable — opérations locales.
3. Aucun nouveau document d'exploration tant que le critère n'est pas franchi ou la famille
   épuisée (§1.7).
4. Si une variante satisfait le chiffre mais dégrade la planche : elle est rejetée.

## 7. Traçabilité

| Décision ou correction | Source |
|---|---|
| Nom et objet du plan | question utilisateur 2026-10-08 ; contenu réel du `.omap` (`main.py::step_assemble`) |
| Critère 32 m / 64,5 % et état 16–19 m / 86,0–57,9 % | `docs/bilan_v0.md` §12.1 |
| Garde-fous du §1.5 | critique utilisateur « est-ce que ça apporte quelque chose à mon futur omap ? » |
| Vectorisation obligatoire | décision utilisateur 2026-10-08 |
| Forme avant signal | `docs/revue_plan_signaux_lidar.md` §3.1 (bande de Trier) + mesure de la fragmentation |
| Audit ini | `src/run_engine.py`, KP `config.rs`, `.gitignore`, bilan §15.1.4 |
| Cascade de Trier | Trier 2015 §2.2 ; `scripts/diag/sweep_ordre_lissage.py` (V6) |
| Overage removal | `docs/pistes_entreprises_lidar.md` §2.1 (LAStools, Esri, TerraMatch, OCAD) |
| Écarté d'avance : médian supplémentaire | bilan §12.1 (mbs2=16) |
| Volet 2 | `docs/pistes_contenu_fichiers_lidar.md`, `docs/pistes_symboles_isom.md` |
| Journal des corrections v1 → v2 | §1 ci-dessus ; `docs/avenant_plan_signaux_lidar.md` (historique) |
