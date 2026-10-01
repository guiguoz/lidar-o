# PLAN 1 — Améliorer le raster végétation : expériences à portes

> **v2.1, 2026-09-30 — après revue v2.** La v1 (huit objectifs O1–O8 à dérouler)
> est remplacée : trop ambitieuse, elle mélangeait diagnostic, amélioration et
> modification de production, et laissait `qa.py` décider à la place du cartographe.
> **Brief destiné à Claude Code (ou tout exécutant).** Autonome.
> **Veilles en annexe (mapant.fr/Cassini/OCAD/vectorisation pro) :** F1–F6, F8 et
> F10–F17 sont des relevés de source ; F7 et F9 sont des **inférences**, marquées
> comme telles.
> **Production intouchée tant que la porte 1 n'est pas passée :** `config.yaml`,
> `scripts/run_terrain.py`, `scripts/process_hag.py`, `src/kp_raster.py`, `main.py`.
> **PORTE 1 (2026-10-01) : NON.** Piste undergrowth par le canal low (C1–C4) **close**
> sur la fenêtre Grimbosq fen3_410 : verdict et chiffres dans `docs/expe_journal.md`.
> Conséquences : Phases 2–3 non conduites sur cette piste ; sujets 4a/4b sans objet ;
> Phase 4 conditionnée aux portes 1–3 — statut des sujets restants au journal.
> **Expérience OVL (go explicite 2026-10-01) :** recouvrement rouvert en expérience
> **indépendante** (§3 réécrit, porte OVL-1) — qualité du signal de production,
> sans aucun lien avec l'undergrowth.

---

## 0. Règles non négociables (issues de la revue)

| # | Règle |
|---|---|
| R1 | **Une porte = votre jugement sur une planche 1:10 000**, même format que `docs/images/vege_mbs2_comparaison.png`. `qa.py` / rappel FFCO = mesures **informatives** rapportées à côté de la planche, jamais un critère de porte (un rappel peut éliminer un raster visuellement utile, ou récompenser un signal qui couvre beaucoup mais mal). |
| R2 | **Expérimentation ≠ production.** Code, configs, rasters, planches d'essai → `work/expe/` (gitignoré). Un commit n'intervient que pour (a) un **verdict** (doc), (b) du **code propre après porte passée**, avec le paramètre gelé et la planche de décision copiée dans `docs/images/`. Pas de commit par essai : les branches abandonnées ne doivent pas polluer l'historique. |
| R3 | **Une seule variable par comparaison contrôlée — Phases 2 à 4.** Tester un lissage = mêmes comptages, mêmes seuils, seul le lissage change. La **Phase 1 n'est pas** une expérience à variable unique : c'est un **screening de quatre hypothèses indépendantes** (C1–C4) soumises à une même porte visuelle ; R3 ne s'y applique pas. |
| R4 | **Verdicts négatifs tracés aussi** : `work/expe/JOURNAL.md` (persiste dans l'espace de travail) + commit doc `docs/expe_journal.md` à chaque porte. C'est la protection contre la régression « décision perdue six semaines plus tard ». |
| R5 | **Pas de branche git d'expérimentation** : la session Arena est fixée à `arena/01a0f111-lidar-o`. L'isolation est obtenue par le répertoire `work/expe/` + **aucun import du code de production** + pipelines PDAL expérimentaux dans `work/expe/pipelines/` (JSON propres, jamais ceux de `run_terrain.py`). |
| R6 | Les seuils expérimentaux vivent dans `work/expe/configs/*.yaml`. `config.yaml` de production ne reçoit un paramètre **qu'après** porte passée et commit de code propre. |
| R8 | **Une piste close reste close.** Undergrowth (porte 1 NON) : aucun seuil,
| strate, sigma ou fenêtre nouveau sur cette piste ; aucune réutilisation de ses
| sorties ailleurs sans étiquette explicite (l'expérience OVL n'en réutilise aucune). |
| R7 | **Une hypothèse n'est jamais un fait.** Tout énoncé portant sur *nos* données (Grimbosq, tuiles IGN, biais, sous-bois) est une hypothèse à mesurer ; seuls les énoncés sur les logiciels tiers (KP, Cassini, OCAD) sont des relevés de source, cités avec fichier/ligne. Aucune phrase du plan ne préjuge du résultat d'une porte. |

Arborescence expérimentale :

```text
work/expe/
├── JOURNAL.md                  verdicts datés, y compris négatifs
├── pipelines/strata_cassini.json
├── configs/undergrowth_01.yaml … _04.yaml
├── undergrowth/expe_undergrowth.py   implémentation de référence (strata|candidates|planche|kernel_test)
├── rasters/                    comptages de strates, candidats (uint8)
└── planches/                   PNG 1:10 000 pour jugement
```

Si `work/` est perdu, tout se reconstruit depuis le présent plan (§1–§4) : les formules
y sont écrites explicitement.

---

## 1. PHASE 0 — vérifier les éléments Cassini et nos prérequis (aucun raster produit)

Livrable : `work/expe/phase0_notes.md`. Pas de porte : ce sont des prérequis.

- **V0.1 — sémantique exacte de `greenshades` dans NOTRE KP (v2.12.1 Rust).** Lire
  `src/config.rs` + `src/vegetation.rs` du clone : quelle grandeur est seuillée
  (densité normalisée comment ?), ordre de la liste, rôle de la première entrée,
  effet des `99`. Note écrite. **Aucun objectif ne parle de « seuil bas » avant que
  cette note existe** (l'ex-O8 supposait cette sémantique).
- **V0.2 — pipeline PDAL Cassini reproduit à l'identique** (filtres, ordre, options) :
  DEM sol (`Classification == 2`, mean, rés 0,5 m) → `filters.hag_dem` →
  `filters.voxeldownsize` (cell 0,5, mode first) → un `writers.gdal` count 1 m uint8
  par strate. **Les clauses `where` de strates ne sont pas décidées dans ce plan :**
  V0.2 relève les expressions **exactes** écrites par Cassini (`src/lidar.rs`) pour
  ses trois strates, les recopie telles quelles dans `phase0_notes.md` **et** dans
  `work/expe/pipelines/strata_cassini.json`, et dérive les deux variantes low du plan
  (0,3–1 m et 0,3–1,3 m) dans la même syntaxe, figées aux mêmes endroits. Les bornes
  citées ailleurs dans le plan — (0,1], (0,3,1], (0,3,1,3], (1,4], (4,30] — sont une
  notation humaine pour la lecture, **pas des clauses à recopier** : aucun risque
  de réinterprétation (virgules décimales, crochets) par l'exécutant.
- **V0.3 — notre pipeline à nous** : confirmer par lecture (sans modifier) que
  `run_terrain.py` n'a pas de voxeldownsize et identifier où le double-comptage de
  recouvrement entre dans nos densités. Note.
- **V0.4 — inventaire données et gel de la fenêtre O1** (le point à verrouiller
  du plan). Les fenêtres candidates sont **déjà consignées** : les trois fenêtres
  mbs2 de `scripts/diag/testa_medianboxsize2.py` (`WINDOWS`, 500 × 500 m, centres
  Lambert-93) : `fen1_406` (448225, 6887720), `fen2_408` (448997, 6887939),
  `fen3_410` (449420, 6887239). Choix de la fenêtre O1 = celle où le désaccord
  KP-vs-FFCO montre du sous-bois manquant (pré-contrôle descriptif, pas une porte).
  Geler dans `phase0_notes.md` : bbox de la fenêtre, **noms des tuiles LiDAR HD qui
  la couvrent** (via `src/providers/france.py` ou la liste de `out_kp_grimbosq/`),
  statut V0.6. Toutes les planches du plan utiliseront cette fenêtre.
  Inventaire données : `LIDAR/`, `out_kp_grimbosq/`, référence FFCO (chemin déclaré
  dans `config.yaml` qa / `autres cartes/`) ; dire explicitement ce qui est
  exécutable où (machine à dalles vs sandbox).
- **V0.5 — noyau gaussien Cassini** (rayon r, σ = r/2, normalisé somme 1) :
  test unitaire `expe_undergrowth.py kernel_test`.
- **V0.6 — statut de recouvrement de la fenêtre O1** (sécurise la Phase 1) :
  ∩ des emprises des tuiles couvrant la fenêtre ; mesure simple de densité de
  retours dans la fenêtre vs hors fenêtre sur les mêmes tuiles (un chiffre par
  strate, pas de carte complète). Si la fenêtre est en recouvrement : le noter,
  la Phase 1 a lieu mais l'interprétation de la planche en tiendra compte ; le
  diagnostic complet reste la Phase 2. Objectif : ne pas fabriquer artificiellement
  une partie du signal undergrowth avec un biais de recouvrement.
- **V0.7 — équivalence spatiale `medianboxsize` ↔ mètres** (ajouté après exécution
  Phase 0, 2026-10-01). Mesurer `res_m` au `.pgw` des `{dalle}_vege.png` de
  production ; la fenêtre médiane **effective** produite par le code Rust est
  `2 × (medianboxsize div 2) + 1` px : la division entière sur un paramètre pair
  donne **+1 px** — `medianboxsize2 = 16` produit une fenêtre de **17 px** (pas
  16), `medianboxsize = 9` reste 9 px. Mesuré sur Grimbosq : `res_m ≈ 0,4233 m/px`
  (1:10 000 à 600 dpi) → mbs 9 → 9 px → **3,81 m** ; mbs2 16 → 17 px → **7,20 m**
  (la production lisse à 7,20 m, pas 16 × 0,4233 = 6,77 m). Sur le comptage 1 m :
  fenêtres médianes **3 px puis 7 px** (impairs les plus proches). Le paramètre de
  production reste **9/16** (validé) : reproduire la fenêtre dérivée de 17 px n'est
  pas « choisir 17 ». Utilisation → Phase 3.

---

## 2. PHASE 1 — diagnostic undergrowth (la seule expérience décidée d'avance)

**Question unique de la porte :** *est-ce que ce canal fait apparaître visiblement les
zones où le fond KP actuel manque de sous-bois ?*

C1–C4 sont **quatre hypothèses indépendantes testées en parallèle** (screening), pas
les niveaux d'un facteur : R3 s'applique aux Phases 2–4, pas ici.

1. **Strates** : `pdal pipeline work/expe/pipelines/strata_cassini.json` sur
   **toutes les tuiles LiDAR couvrant la fenêtre gelée** (V0.4) → comptages 1 m
   uint8 dans `work/expe/rasters/`, mosaïqués sur la fenêtre. **Règle de
   contenance :** la fenêtre de la planche doit être entièrement contenue dans
   la/les tuile(s) utilisée(s) ; si elle recouvre N tuiles, utiliser les N tuiles ;
   **ne pas tronquer la fenêtre** pour respecter une contrainte « une tuile ».
   **Tuile témoin :** tuile comparable (couvert forestier similaire) et **hors
   recouvrement**, pour ne pas confondre undergrowth et artefact de densité ;
   si aucune n'existe, le noter et interpréter avec V0.6.
   (`run_terrain.py` n'est pas appelé.)
2. **Candidats — 4 maximum**, chacun = une strate low + gaussienne σ = 2 m (noyau
   rayon 4, σ = r/2, normalisé) + un seuil en pt/m² :

   | id | strate | σ | seuil |
   |---|---|---|---|
   | C1 | (0,3, 1] | 2 m | 1,0 (valeur Cassini) |
   | C2 | (0,3, 1] | 2 m | 0,5 |
   | C3 | (0, 1] | 2 m | 1,0 |
   | C4 | (0,3, 1,3] | 2 m | 1,0 |

3. **Planche** `work/expe/planches/phase1_undergrowth.png`, 1:10 000, fenêtre V0.4,
   4 panneaux : **KP actuel** (mosaïque `vege_bit`) / **C1** / **C2** / **FFCO**
   (si la référence raster n'existe pas : C3 en 4ᵉ panneau + note). Même échelle,
   mêmes couleurs, mêmes légendes que la planche mbs2. Candidats binaires dessinés
   en vert 60 % sur blanc.
4. **Mesures informatives** (rapportées, pas un critère) : ha couvertes par candidat ;
   recouvrement avec le 406/408/410 KP actuel ; le cas échéant rappel FFCO 408+410.
   Le recouvrement avec les verts KP est **purement descriptif** : un undergrowth
   qui recouvre 70 % du vert existant peut parfaitement être utile s'il ajoute les
   bonnes petites structures là où elles manquent — aucun critère implicite de
   « nouveauté » (même logique que R1).
   **Garde-fou no-data** (stratégie OCAD « show area with no data in red ») : les
   cellules sans aucun retour dans aucune strate ne sont **pas** du découvert ; leur
   surface est rapportée à côté de la planche et exclue de l'interprétation des
   candidats (un trou de vol ne doit pas passer pour une clairière).
5. **PORTE 1 = vous regardez.** Verdict dans `JOURNAL.md` + commit `docs/expe_journal.md`.
   - **NON** → stop définitif du plan sur cette piste ; note dans `bilan_v0.md`
     (« le canal undergrowth n'apporte rien sur nos données » est un résultat).
   - **OUI** → Phases 2 et 3 débloquées.

Implémentation de référence : `work/expe/undergrowth/expe_undergrowth.py`
(`strata` | `candidates` | `planche` | `kernel_test`), configs
`work/expe/configs/undergrowth_01..04.yaml`.

---

## 3. PHASE 2 — recouvrement de dalles : expérience indépendante (porte OVL-1)

> **Réouverte 2026-10-01 sur go explicite, après porte 1 NON :** le recouvrement
> n'est plus un sous-étage de la piste undergrowth mais une question de **qualité
> du signal de production**, indépendante de tout canal végétation. Aucun seuil,
> strate, sigma ni fenêtre de la piste close n'est réutilisé ici (R8).
> **Production intouchée :** ni `run_terrain.py`, ni `process_hag.py`, ni
> `config.yaml`, ni `kp_raster.py`, ni `main.py`.

**Question unique de la porte :** *le recouvrement de dalles introduit-il une
surdensité suffisamment importante pour modifier visiblement le raster végétation
produit ?*

**Fenêtre O2 gelée** (nouvelle ; à consigner dans `work/expe/phase0_notes.md`) :
500 × 500 m centrée sur **(449420, 6887000)** L93 — la frontière inter-tuiles
0449_6887/0449_6888 y passe au milieu, donc la bande de recouvrement (V0.6 :
~30 m) est au **centre** de la planche, pas sur un bord. Les deux dalles sont
chargées **ensemble** (un seul pipeline PDAL listant les deux fichiers) : c'est
la seule manière de voir les points comptés deux fois. **Zone témoin** = même
fenêtre hors ±50 m autour de la frontière (même forêt, sans recouvrement) —
le témoin est dans la planche, pas ailleurs.

1. **Pipelines** `work/expe/pipelines/overlap_A.json` et `overlap_B.json` :
   mêmes clauses de strates V0.2 (figées), mêmes points, **une seule différence** =
   présence de `filters.voxeldownsize` (cell 0,5, mode first) dans B. Un writer
   par strate `low` / `medium` / `high`, 1 m, uint8, emprise O2 (R3).
2. **Livrables** dans `work/expe/overlap/` :
   `overlap_map.tif` (bande 0/1), `ratio_low.tif`, `ratio_medium.tif`,
   `ratio_high.tif`, `overlap_stats.md`, `planche_overlap.png`.
   `ratio = B / A` calculé **uniquement là où A > 0** ; part des cellules A = 0
   rapportée en/hors recouvrement (garde-fou no-data).
3. **Statistiques, par strate :** médiane du ratio **en recouvrement**, médiane
   du ratio **témoin**, et **différence recouvrement − témoin publiée** (contrôle
   nul : sans elle, l'effet de voxeldownsize sur le signal réel est indiscernable
   de son effet sur les doublons). Plus, informatif sur le mécanisme (jamais un
   critère) : part des points LAS classe 12 (overlap inter-lignes de vol, mesure
   OCAD) en/hors bande ; et une ligne « A chargé ensemble ressemble-t-il à la
   production dans la bande ? » (compare A au panneau 1) — elle tranchera plus
   tard comment la production mosaïque réellement.
4. **Planche** `planche_overlap.png`, même emprise O2, bande de recouvrement et
   zone témoin hachurées, quatre panneaux aux titres **sans préjugé** :
   (1) **production actuelle** (mosaïque `_vege.png` existante recadrée sur O2 —
   aucun rerun) ; (2) **densité A** = comptage brut low, dalles chargées
   ensemble ; (3) **densité B** = après voxeldownsize — *traitement candidat, pas
   correction prouvée* ; (4) **ratio B/A** (low). Medium/high : petits multiples
   ou stats seules. L'expérience montre **ce que fait le recouvrement et ce que
   change voxeldownsize** — pas que voxeldownsize est la bonne correction.
5. **STOP** après `planche_overlap.png` + `overlap_stats.md`.
   **PORTE OVL-1 = vous regardez.** Verdict dans `work/expe/JOURNAL.md` + entrée
   `docs/expe_journal.md` (R4) ; planche copiée dans `docs/images/` seulement au
   commit de verdict (R2).
   - surdensité invisible ou négligeable → clos par une note (négatif tracé) ;
   - surdensité visible → **la correction est un sujet séparé**, ouvert sur go
     explicite seulement ; rien dans cette phase ne la décide ni ne la code.

---

## 4. PHASE 3 — médian vs gaussien : même signal, mêmes seuils

> **Statut 2026-10-01 :** non conduite sur la piste undergrowth (porte 1 NON).
> Réouvrable en piste indépendante (lissage du raster de production, indépendant de
> l'undergrowth) sur go explicite seulement ; l'équivalence V0.7 (médian 3 px puis
> 7 px sur comptage 1 m) reste acquise si elle est réouverte.

Seule variable = le lissage (R3). Représentation fixée = comptages de strates 1 m.
**Équivalence spatiale — mesurée (V0.7, 2026-10-01) :** `res_m` au `.pgw` de
production ≈ **0,4233 m/px** (1:10 000 à 600 dpi) ; fenêtre médiane effective Rust =
`2 × (medianboxsize div 2) + 1` px — un paramètre pair donne **+1 px** :
`medianboxsize2 = 16` produit **17 px** (pas 16), `mbs = 9` reste 9 px. En mètres :
mbs 9 → **3,81 m** ; mbs2 16 → **7,20 m** (la production lisse à 7,20 m, pas
6,77 m). Sur le raster de comptage à 1 m : **médian 3 px puis 7 px** (impairs les
plus proches en mètres ; l'alternative 5 px pour 3,81 m est rapportée en sensibilité).
Le paramètre de production reste **9/16** (validé) : reproduire la fenêtre dérivée
n'est pas « choisir 17 » — `config.yaml` intouché. **Ne pas recopier « 9 px / 16 px »
tels quels** sur le comptage 1 m : ce seraient d'autres fenêtres spatiales (9 m et
16 m), et la comparaison A/B ne reproduirait pas le lissage de production validé
visuellement.
**Signal d'entrée gelé à l'issue de la Phase 2 :** comptage brut si aucune correction
n'est retenue, comptage corrigé si une correction a été validée expérimentalement.
A et B utilisent **exactement** ce même signal, et rien d'autre.

- **A** = comptages + **médian** (fenêtres **3 px puis 7 px** sur le comptage 1 m,
  dérivées de l'équivalence V0.7 mesurée : 9 px effectifs → 3,81 m puis 17 px
  effectifs → 7,20 m à `res_m` ≈ 0,4233 ; paramètre de production mbs 9/16
  intouché), appliquées aux classes construites depuis les comptages ;
- **B** = mêmes comptages + **gaussienne** σ1 = 1 m (strate medium) / σ2 = 2 m (low) ;
- **mêmes seuils** (pt/m²) appliqués ensuite à A et à B ;
- planche A / B / FFCO (+ KP actuel pour mémoire), fenêtre V0.4, 1:10 000.

**A et B constituent une expérience contrôlée indépendante du raster KP actuel :**
même comptage d'entrée, même seuil, seul le lissage varie. Le KP actuel est affiché
**uniquement comme référence visuelle externe** (sa chaîne diffère : indices de
palette, médian par tuile, seuils propres). La conclusion autorisée porte sur le
lissage à signal fixé — jamais « le gaussien est meilleur que KP ».

**PORTE 3 = vous regardez** (protocole de jugement mbs2 : lisibilité vs fidélité).
Si B gagne : commit de code propre = option de lissage **après mosaïque** dans le pont
KP / `process_hag`, paramètre gelé dans `config.yaml`, planche de décision dans
`docs/images/`.

---

## 5. PHASE 4 — seulement si les portes 1–3 sont passées ; un sujet à la fois

> **Statut 2026-10-01 :** porte 1 NON ⇒ 4a et 4b **sans objet** (undergrowth) ;
> 4c/4d/4e/4f formellement bloqués par la règle de portes « 1–3 ». Toute réouverture
> = révision du présent plan sur go explicite.

Chaque sujet = sa planche, sa porte, son verdict. Ordre imposé. **Aucun sujet n'est
enclenché automatiquement par le succès du précédent : chacun demande un go explicite.**

- **4a fusion undergrowth → verts — SANS OBJET (porte 1 NON)** : modes `none | merge | propose409` (sémantique
  Cassini). `merge` = ajout au canal medium **avant seuillage** (pas un rehaussement
  de classe). **Pas de `layer409` validante :** ISOM 2017-2 n'a aucune surface
  « undergrowth » (contrôle du gabarit : 409 = « walk, good visibility » ;
  « Green 100% for undergrowth » n'est qu'une couleur) — or 407/409 portent un
  jugement de visibilité, qui est un jugement de terrain. `propose409` = couche
  séparée dessinée en 409 **pour revue**, réaffectée par le cartographe ; **exclue
  de `coverage_partition`** (superposition par conception) — fait le pont avec le
  plan 2, tâche V5. Planche propre, porte 4a.
- **4b seuil KP gaté par l'undergrowth — SANS OBJET (porte 1 NON)** (piste planche D, ex-4d) : abaissement du
  premier seuil appliqué **seulement là où** le canal undergrowth = 1. **Ce n'est
  pas une suite logique de 4a** : hypothèse supplémentaire, enclenchée seulement sur
  décision explicite après la porte 4a ; planche propre, porte propre.
  **Condition absolue :** la note V0.1 confirme la sémantique supposée ; sinon
  abandon sans test.
- **4c découvert « min canopée »** : MIN du canal high (4, 30] sur fenêtre 5×5 m vs
  `yellow_threshold` ; mesure de désaccord avec BD TOPO / OSM ; **aucune** modification
  automatique du jaune (le jaune reste BD TOPO/OSM, protocole vectorisation §É2).
- **4d comparaison mapant.fr** : **d'abord** lire les conditions d'utilisation du
  service de tuiles ; puis planche de diff sur Grimbosq = contrôle indépendant
  (LiDAR HD France grande échelle), jamais une dépendance du produit.
- **4e croisement OCAD** (optionnel, go explicite, après 4d) : « Vegetation Base Map »
  du LiDAR Point Cloud Manager (range undergrowth 0,1–1,0 m / vegetation 1,0–3,0 m,
  seuil de points overlap) et carte d'intensité (frontières feuillus/résineux) en
  planches de contrôle externe sur la fenêtre V0.4. OCAD est propriétaire : stratégies
  lisibles sur le wiki public sans licence, planches comparatives seulement si licence
  disponible. Contrôle indépendant, jamais une dépendance ; les défauts OCAD
  (Steinhauserwald, canton de Zurich) sont des priors, pas des valeurs.
- **4f étalonnage « benchmark patches »** (optionnel, go explicite, après 4e ;
  technique Jagge/JWOC 2015, voir plan 2 §5 S7) : l'utilisateur place **par jugement**
  une dizaine de cercles (rayon ~10 m) sur la fenêtre V0.4 dont le type de végétation
  est connu (blanc / vert léger / moyen / foncé). Le script mesure sur ces cercles les
  histogrammes des strates issues des comptages de la Phase 1 et rapporte la position
  des seuils `greenshades` et des candidats undergrowth par rapport aux distributions
  réelles de chaque classe. **Étalonnage informatif, jamais une porte** (R1) ; aucune
  campagne terrain nécessaire (connaissance du terrain + cartes existantes suffisent).
  Le mécanisme existait dans le code privé de Jagge pour JWOC 2015 ; **absent du KP
  public** (vérifié par grep) → implémentation externe sur nos comptages. Rappel :
  `greenshades` est gelé par jugement utilisateur — 4f **documente** l'adéquation,
  il ne rouvre la décision que sur demande explicite de l'utilisateur.
  Composante undergrowth **close** (porte 1 NON) ; la composante `greenshades` reste
  optionnelle sur go explicite.

---

## 6. Ce que ce plan ne fait pas

- Aucun critère `qa.py` comme porte (R1).
- Aucun commit par essai ; aucun paramètre dans `config.yaml` avant porte (R2, R6).
- Aucune modification de `run_terrain.py` / `process_hag.py` / `kp_raster.py` /
  `main.py` / `config.yaml` avant porte passée (R2, R6).
- Aucune branche git d'expérimentation (R5).
- Pas de ML/scoring (avenant 02 §0) ; pas de copie de code Cassini (GPL-3.0) :
  réimplémentation clean-room des formules, ou image Docker `nicorio42/cassini`
  appelée comme outil séparé pour comparaison.
- Pas de test terrain : toutes les mesures se font sur dalles et références existantes.

## 7. Definition of done, phase par phase

| Phase | Done |
|---|---|
| 0 | `phase0_notes.md` : sémantique greenshades, JSON strates, inventaire données + bbox planches + équivalence medianboxsize↔mètres (V0.7) |
| 1 | planche 4 panneaux 1:10 000 produite **et regardée** ; verdict commité (même négatif) — **PORTE 1 NON 2026-10-01, close** (`docs/expe_journal.md`) |
| 2 (OVL) | stats recouvrement + planche produites **et regardées** ; verdict porte OVL-1 commité (même négatif) ; toute correction = sujet séparé sur go explicite |
| 3 | planche A/B commitée ; verdict ; si positif, code propre + paramètre gelé |
| 4 | chaque sujet a son verdict, renoncements compris ; propose409 éventuel raccordé au plan 2 V5 ; 4b/4e/4f enclenchés seulement sur go explicite |

---

## Annexe — veilles Cassini/mapant/OCAD/vectorisation pro (sources vérifiées 2026-09-30 et 2026-10-01)

F1 trois strates (0,1]/(1,4]/(4,30] comptées à 1 m, classification IGN végétation
ignorée, sol = classe 2 (`lidar.rs`) · F2 undergrowth = canal low lissé gaussienne
rayon 4, seuil pt/m², modes merge/406/409 (`vegetation.rs`) · F3 verts = gaussienne
rayon 2 sur la strate medium, seuils 0,2/1,0/2,0 pt/m² (blog) · F4 blanc = MIN du canal
high sur cercle 5×5 > yellow_threshold · F5 `voxeldownsize` 0,5 m mode first avant
comptage · F6 VRT tuile+voisines buffer 200 m avant lissage → sans couture ·
F7 `mapant-scripts/lidar_delete_overlap` met de côté des tuiles de zones de
recouvrement (relevé) ; **inférence, non vérifiée sur nos tuiles** : que le recouvrement
y soit un biais effectif · F8 lissage gaussien sur densités, pas médian sur indices ·
F9 famille mapant (fi/no/es/lu, gokartor.se) = KP, ch = OCAD (relevé cassini-map.com) ;
parmi ces moteurs **open source**, Cassini est le seul avec un rendu undergrowth —
OCAD, propriétaire, en a un aussi (F10).
F10 OCAD LiDAR Point Cloud Manager : range undergrowth (0,1–1,0 m) séparé de la
végétation, seuil dédié aux points LAS overlap (inter-lignes de vol), garde-fou
no-data en rouge, défauts calibrés par forêt (Steinhauserwald, Zurich) · F11 OCAD DEM
Import Wizard : classes de hauteur de végétation configurables, carte d'intensité =
frontières feuillus/résineux, « Extract Features » = vectorisation végétation native
mais « results should be treated with caution » selon l'éditeur · F12 OCAD « Check
Legibility Space » : contrôle des tailles minimales ISOM 2017 par symbole comme aide
à la généralisation ; les largeurs minimales ne sont pas contrôlées par OCAD.
F13 KP = Karttapullautin, auteur Jarkko Ryyppä (« Jagge ») ; réglage pro conseillé
(attackpoint.org, janv. 2026) : clip représentatif contenant tous les types de vert,
`greenshades` à 3–4 valeurs + 99 pour sauter une nuance, éclaircissage sans effet sur
la sortie ≥ 2 pts/m² · F14 « benchmark patches » (JWOC 2015, code privé de Jagge —
absent du KP public, vérifié) : cercles à végétation connue → histogrammes LiDAR →
étalonnage ; réimplémentable en externe sur nos comptages (sujet 4f) · F15 ISOM
2017-2 §2.6 : généralisation en deux phases — sélective (dimensions mini décidées au
relevé) et graphique (simplification, déplacement, exagération) ; « la lisibilité ne
doit jamais être sacrifiée » ; frontières nettes entre végétations = points de repère
du lecteur · F16 runnability = jugement : « there is no precise way of measuring
runnability » (BKO) ; plages de vitesse IOF par classe (blanc ≈ 100 %, 411 ≈ 0–20 %)
— conforte R1 ; traces GPS LivElox/3D Rerun téléchargeables (GPX) pour étalonnage
informatif agrégé · F17 FFCO règlement cartographie (éd. 2020) : les données de base
(LiDAR, MNT, orthophotos) ne sont pas couvertes par le droit d'auteur et sont
librement réutilisables ; les cartes de CO doivent être déclarées (FFCO + BNF).
Sources : github.com/NicoRio42/cassini (GPL-3), github.com/NicoRio42/mapant-scripts,
mapant.fr/blog/cassini-pour-les-nuls, cassini-map.com/what-and-why, ocad.com/wiki
(LiDAR_Point_Cloud_Manager, DEM_Import_Wizard, Map), omaps.worldofo.com (cartes
Grimbosq déc. 2015, id 159467/159468 → doma go78.org), attackpoint.org (fils Jagge),
orienteeringbc.ca/basemap-generation, whorienteers.net/Creating-Base-Maps,
helpx.adobe.com (Image Trace), ffcorientation.fr (ISOM 2017-2 FR/EN, règlement carto
2020), bko.org.uk (KYS-Vegetation.pdf), livelox.com/documentation, ocad.com/blog
(interview J. Weckman) — vérifiées 2026-09-30 et 2026-10-01.
