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
| sorties ailleurs sans étiquette explicite — l'expérience OVL (§3) ne réutilise
| que les trois strates V0.2 figées, en sorties de mesure, et le dit. |
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

> **Réouverte le 2026-10-01 sur go explicite, après Porte 1 = NON :** le
> recouvrement n'est plus un sous-étage de la piste undergrowth. C'est une
> question indépendante de **qualité du signal de production**.
>
> Aucun seuil, strate expérimentale, sigma ou fenêtre de la piste undergrowth
> close n'est réutilisé ici, à l'exception des **trois strates V0.2 déjà figées**
> (`low`, `medium`, `high`) utilisées uniquement comme sorties de mesure.
>
> **Production intouchée :** ni `run_terrain.py`, ni `process_hag.py`, ni
> `config.yaml`, ni `kp_raster.py`, ni `main.py`.

> **PORTE OVL-1 (2026-10-01) : OUI — surdensité significative.** Juge : agent,
> sur délégation explicite ; chiffres, lectures et mécanisme (passes de vol
> convergentes en bord de tuile, pas doublon inter-tuiles) dans
> `docs/expe_journal.md`. Clause visuelle panneau 1 à confirmer au commit de
> verdict. **Sujet correction non ouvert — go explicite requis.** Clause visuelle
> panneau 1 tranchée le 2026-10-01 : pas de couture visible dans la production
> sur O2 → verdict requalifié « surdensité significative en comptages, trace en
> classes à mesurer » ; mesure décisive = audit de basculement de classes sur
> toutes les coutures (étape 1 du périmètre, sur go).

### Question unique de la porte

> **Le recouvrement réel entre les deux dalles introduit-il une surdensité
> suffisamment importante pour modifier visiblement le raster végétation
> produit ?**

### Fenêtre O2 gelée

Nouvelle fenêtre, à consigner dans `work/expe/phase0_notes.md` :

- centre : **(449420, 6887000)** en Lambert-93 ;
- dimensions : **500 × 500 m** ;
- la frontière entre `0449_6887` et `0449_6888` traverse le centre de la fenêtre ;
- la bande de points effectivement fournie par les deux dalles, identifiée en
  V0.6, est d'environ **30 m** et se trouve donc au centre de la planche ;
- les deux dalles sont toujours chargées ensemble pour les traitements A et B.

**Zone témoin :** dans cette même fenêtre O2, utiliser les cellules situées à
plus de **50 m de la frontière**, hors zone de recouvrement, comme contrôle
interne. Ne pas utiliser une autre emprise comme témoin.

### 1. Pipelines contrôlés

Créer :

```text
work/expe/pipelines/overlap_A.json
work/expe/pipelines/overlap_B.json
```

A et B doivent recevoir exactement le même ensemble de points d'entrée :
les deux dalles chargées ensemble.

Les deux pipelines utilisent :

- les mêmes filtres et le même ordre que V0.2 ;
- les mêmes clauses de strates V0.2 ;
- la même emprise O2 ;
- une résolution de 1 m ;
- un writer par strate low / medium / high ;
- uint8.

Une seule différence :

- A = comptage brut ;
- B = comptage après `filters.voxeldownsize` (cell = 0,5 m, mode = first).

Aucune autre modification de traitement n'est autorisée.

### 2. Carte réelle du recouvrement

Construire `overlap_map.tif` à partir des points effectivement présents dans
chaque dalle, et non à partir de l'intersection de leurs bbox nominales :
**on mesure le recouvrement des points, pas le recouvrement administratif des
tuiles** — c'est le verrou clé de l'expérience.

Pour chaque dalle, produire un masque de présence sur la grille O2
(implémentation : deux pipelines minimaux, un par dalle isolée, comptage
tous-points sans clause where sur O2 ; M = comptage > 0) :

- M1 = au moins un point de `0449_6887` dans la cellule ;
- M2 = au moins un point de `0449_6888` dans la cellule ;

puis `overlap_map = M1 AND M2`, avec :

- 0 = une seule dalle fournit des points ;
- 1 = les deux dalles fournissent des points.

La bande obtenue doit être cohérente avec le recouvrement d'environ 30 m observé
en V0.6. Cette définition est la référence spatiale de toute la phase OVL-1.

### 3. Livrables

Dans `work/expe/overlap/`, produire : `overlap_map.tif`, `ratio_low.tif`,
`ratio_medium.tif`, `ratio_high.tif`, `overlap_stats.md`, `planche_overlap.png`.

Pour chaque strate : `ratio = B / A`, calculé uniquement pour les cellules où
`A > 0`. Les cellules A = 0 sont rapportées séparément (part A=0 dans la zone
overlap, part A=0 dans la zone témoin) : elles constituent un garde-fou de
couverture et ne doivent pas être utilisées comme ratios.

### 4. Statistiques

Pour low, medium et high, rapporter séparément :

- médiane du ratio B/A dans overlap ;
- médiane du ratio B/A dans témoin ;
- **différence overlap − témoin**.

La comparaison overlap − témoin est obligatoire : elle permet de distinguer
l'effet général de voxeldownsize sur le signal de l'effet spécifique du double
apport de points dans la zone de recouvrement.

Ajouter, uniquement comme informations mécanistiques :

- part des points LAS de classe 12 dans la bande de recouvrement ;
- part des points LAS de classe 12 dans la zone témoin ;
- comparaison du comptage A avec le signal de la production actuelle dans la
  bande de recouvrement.

Cette dernière comparaison répond uniquement à la question : le comptage A
chargé ensemble reproduit-il le comportement observé dans la production
actuelle ? Elle ne constitue pas une mesure de qualité cartographique.

Aucune de ces statistiques n'est un critère numérique de passage.

### 5. Planche `planche_overlap.png`

Même emprise O2, même échelle 1:10 000. Localiser visuellement :

- la bande réelle de recouvrement ;
- la zone témoin située à plus de 50 m de la frontière.

Produire quatre panneaux, avec des titres descriptifs et sans préjuger du
résultat :

1. **Production actuelle** — mosaïque `_vege.png` existante, simplement recadrée
   sur O2 ; aucun rerun ;
2. **Densité A** — comptage low brut, les deux dalles chargées ensemble ;
3. **Densité B** — même comptage après voxeldownsize ; traitement expérimental,
   pas correction validée ;
4. **Ratio B/A** — strate low.

medium et high sont traités par les statistiques et peuvent être montrés en
petits multiples uniquement si cela améliore la lecture.

La planche doit permettre de voir **ce que produit réellement le recouvrement +
ce que change voxeldownsize**, et pas de démontrer à l'avance que voxeldownsize
constitue la bonne correction.

### 6. STOP — Porte OVL-1

Ne rien faire au-delà de cette étape. Livrables minimaux avant jugement :
`planche_overlap.png`, `overlap_stats.md`, `overlap_map.tif`.

**PORTE OVL-1 = jugement humain sur la planche.** Tracer le verdict dans
`work/expe/JOURNAL.md` et `docs/expe_journal.md` ; la planche est copiée dans
`docs/images/` uniquement avec le commit du verdict.

- Si la surdensité est invisible ou négligeable : fermer cette piste par une
  note documentée.
- Si la surdensité est visiblement significative : ne pas corriger dans cette
  phase ; ouvrir uniquement sur go explicite une nouvelle expérience consacrée
  à la correction du recouvrement.

Aucun changement de production n'est effectué par OVL-1.

### 7. Sujet conditionnel OVL-2 — audit des basculements de classe (second go)

> **Mesure seule. Aucun code de correction, aucune modification du pipeline,
> aucun paramètre KP.** Porte explicite à la fin (PORTE OVL-2) : sans second
> feu vert, rien ne s'écrit ensuite. Aucun commit avant relecture (R2).

**Ce que OVL-1 a établi :** surdensité réelle en bande frontière (low 1,25× ·
medium 1,35× · high 1,85× vs témoin) ; voxeldownsize retire proportionnellement
plus en frontière (B/A 0,33–0,52 vs 0,50–0,68) ; aucune couture **visible** dans
la production sur O2 ; voxeldownsize disqualifié comme correctif (il lave le
signal partout : 32–50 % de réduction hors de tout recouvrement).

**Le défaut est comptable. Il n'est pas démontré cartographique.** « Pas ici »
n'est pas « pas ailleurs » : O2 est une fenêtre aux comptages loin des seuils
(4→5, 20→27, 92→170 pts/m²) ; une couture traversant une densité proche d'un
seuil `greenshades` basculerait de classe — et 30 m à 1:10 000 font 3 mm de
liseré : visible si ça bascule, invisible sinon.

#### 7.1 Question unique

> **Existe-t-il, sur l'ensemble de la carte, des basculements de classe alignés
> sur une couture de dalle ?**

- **OUI** → le défaut est cartographique ; les étapes 2 et 3 s'ouvriront, sur un
  second go explicite.
- **NON** → le recouvrement rejoint `bilan_v0.md` comme caractéristique de
  production documentée et close.

#### 7.2 Entrées et références

- **Raster d'entrée :** mosaïque de production **telle quelle**
  (`output/vegetation.png` + pgw, 1 m/px, classes 406/408/410 + ouvert/blanc).
  Aucun recalcul, aucune réinterprétation.
- **Coutures :** arêtes internes entre tuiles réellement utilisées en production
  (liste depuis `out_kp_grimbosq/`), deux orientations.
- **Référence du test d'alignement :** la **ligne nominale de coupe** (droite par
  construction). **Corridor de recherche :** bande M1∧M2 de OVL-1 (§2), ou ±25 m
  là où M1∧M2 n'est pas calculable. Ne pas aligner sur le bord de M1∧M2 : c'est
  la ligne nominale qui est rectiligne par construction.

#### 7.3 Critère : alignement exact, pas proximité

- **Mauvais :** appartenance à une bande ±25 m — une limite de parcelle peut s'y
  trouver par hasard.
- **Bon :** écart à la ligne nominale **au pixel** (±1 px = 1 m) ; écart médian ;
  longueur sur laquelle l'alignement se maintient.

Détection opérationnelle : pixels de frontière de classe
(classe(x, y) ≠ classe(x, y−1) pour une couture horizontale ; symétrique en x
pour une verticale) ; **segment aligné** = run maximal de pixels de frontière
avec |y − y0| ≤ 1 px. **Contrôle nul par ligne :** comptage des transitions par
ligne dans le corridor, niveau de chance = médiane des lignes hors ±2 px ;
excès sur la ligne rapporté. Sans ce niveau de chance, toute frontière
rectiligne qui passe là augmente mécaniquement la densité de transitions.

> Un artefact de recouvrement est rectiligne par construction — il suit la limite
> de dalle. Une structure du terrain ne l'est que par coïncidence, et pas sur
> toute sa longueur.

#### 7.4 Candidat prioritaire — à traiter en premier

Fenêtre O2, tiers droit, x > 449500 : un bord vert/beige court dans la bande.
Lecture actuelle : **limite de parcelle** (bord rectiligne aligné avec les rangs
de plantation visibles en densité A ; contresens physique : une surdensité de
+85 % sur la strate haute pousse vers PLUS de vert, jamais vers du découvert —
un artefact de couture VERDIRAIT la bande, il ne l'ouvrirait pas).

Test : y de frontière par x sur [449500, 449670] → médiane, IQR,
max |y − 6887000|, et longueur sur laquelle |y − 6887000| ≤ 1 px.

- y exactement 6887000 sur plusieurs dizaines de mètres → la lecture « parcelle »
  est contredite, et l'inférence du contresens physique tombe avec elle ;
- sinon → elle est confirmée.

> Vérification qui apprend dans les deux sens : si les chiffres contredisent
> l'œil, ce sont les chiffres qui gagnent.

#### 7.5 Périmètre par couture

Pour chaque couture de l'emprise : nombre de transitions de classe dans le
corridor ; part de ces transitions alignées au pixel sur la ligne ; longueur
cumulée des segments alignés ; classes concernées et **sens du basculement**
(classe dans la bande vs classe juste hors corridor) : une surdensité doit faire
*monter* d'une classe de vert (406→408→410), jamais descendre — un basculement
dans le mauvais sens signale autre chose qu'un recouvrement.

#### 7.6 Ne pas faire

- ❌ écrire du code de correction (étape 2, elle attend un second go) ;
- ❌ modifier pipeline, voxeldownsize, paramètres KP ;
- ❌ conclure « aucun problème » depuis une non-détection sur une seule fenêtre
  (le NON de cet audit est un résultat mesuré map-wide, pas une absence locale) ;
- ❌ tolérance d'alignement large : elle confondrait parcelles et artefacts.

#### 7.7 STOP — PORTE OVL-2

Livrables dans `work/expe/overlap/audit/` : `audit_stats.md`,
`aligned_segments.tif` (ou geojson par couture), `planche_audit.png` (segments
alignés superposés à la production, s'il y en a). Rapporter : résultat du test
candidat (y exact, longueur) ; par couture : transitions, part alignée,
longueur, classes et sens ; planche. **Puis STOP.**

- aucun basculement aligné → note de clôture dans `bilan_v0.md` :
  « recouvrement de dalles : surdensité mesurée, sans effet cartographique
  constaté sur l'emprise de Grimbosq » ; sujet **CLOS** ; verdict + note
  commités (R4), planche dans `docs/images/` au commit de verdict seulement ;
- basculements alignés trouvés → ampleur et localisation rapportées ; les
  étapes 2 et 3 attendent un **SECOND GO** explicite.

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
