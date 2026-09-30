# PLAN 1 — Améliorer le raster végétation : expériences à portes

> **v2, 2026-09-30 — réécrit après revue.** La v1 (huit objectifs O1–O8 à dérouler)
> est remplacée : trop ambitieuse, elle mélangeait diagnostic, amélioration et
> modification de production, et laissait `qa.py` décider à la place du cartographe.
> **Brief destiné à Claude Code (ou tout exécutant).** Autonome.
> **La veille mapant.fr/Cassini (faits F1–F9) reste valable : résumée en annexe.**
> **Production intouchée tant que la porte 1 n'est pas passée :** `config.yaml`,
> `scripts/run_terrain.py`, `scripts/process_hag.py`, `src/kp_raster.py`, `main.py`.

---

## 0. Règles non négociables (issues de la revue)

| # | Règle |
|---|---|
| R1 | **Une porte = votre jugement sur une planche 1:10 000**, même format que `docs/images/vege_mbs2_comparaison.png`. `qa.py` / rappel FFCO = mesures **informatives** rapportées à côté de la planche, jamais un critère de porte (un rappel peut éliminer un raster visuellement utile, ou récompenser un signal qui couvre beaucoup mais mal). |
| R2 | **Expérimentation ≠ production.** Code, configs, rasters, planches d'essai → `work/expe/` (gitignoré). Un commit n'intervient que pour (a) un **verdict** (doc), (b) du **code propre après porte passée**, avec le paramètre gelé et la planche de décision copiée dans `docs/images/`. Pas de commit par essai : les branches abandonnées ne doivent pas polluer l'historique. |
| R3 | **Une seule variable par expérience.** Tester un lissage = mêmes comptages, mêmes seuils, seul le lissage change. |
| R4 | **Verdicts négatifs tracés aussi** : `work/expe/JOURNAL.md` (persiste dans l'espace de travail) + commit doc `docs/expe_journal.md` à chaque porte. C'est la protection contre la régression « décision perdue six semaines plus tard ». |
| R5 | **Pas de branche git d'expérimentation** : la session Arena est fixée à `arena/01a0f111-lidar-o`. L'isolation est obtenue par le répertoire `work/expe/` + **aucun import du code de production** + pipelines PDAL expérimentaux dans `work/expe/pipelines/` (JSON propres, jamais ceux de `run_terrain.py`). |
| R6 | Les seuils expérimentaux vivent dans `work/expe/configs/*.yaml`. `config.yaml` de production ne reçoit un paramètre **qu'après** porte passée et commit de code propre. |

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
  `writers.gdal` DEM (Classification==2, mean, rés 0,5 m) → `filters.hag_dem` →
  `filters.voxeldownsize` (cell 0,5, mode first) → `writers.gdal` count 1 m uint8 par
  strate, `where` sur `HeightAboveGround` : (0,1], (0,3,1], (0,3,1,3], (1,4], (4,30].
  → `work/expe/pipelines/strata_cassini.json`.
- **V0.3 — notre pipeline à nous** : confirmer par lecture (sans modifier) que
  `run_terrain.py` n'a pas de voxeldownsize et identifier où le double-comptage de
  recouvrement entre dans nos densités. Note.
- **V0.4 — inventaire données** : `LIDAR/`, `out_kp_grimbosq/`, référence FFCO
  (chemin déclaré dans `config.yaml` qa / `autres cartes/`), **bbox exacte de la
  fenêtre des planches mbs2** (à relever une fois pour toutes et geler dans
  `phase0_notes.md` : toutes les planches du plan utiliseront cette fenêtre).
  Dire explicitement ce qui est exécutable où (machine à dalles vs sandbox).
- **V0.5 — noyau gaussien Cassini** (rayon r, σ = r/2, normalisé somme 1) :
  test unitaire `expe_undergrowth.py kernel_test`.

---

## 2. PHASE 1 — diagnostic undergrowth (la seule expérience décidée d'avance)

**Question unique de la porte :** *est-ce que ce canal fait apparaître visiblement les
zones où le fond KP actuel manque de sous-bois ?*

1. **Strates** : sur 1 tuile Grimbosq (+ 1 tuile témoin), `pdal pipeline
   work/expe/pipelines/strata_cassini.json` → comptages 1 m uint8 dans `work/expe/rasters/`.
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
5. **PORTE 1 = vous regardez.** Verdict dans `JOURNAL.md` + commit `docs/expe_journal.md`.
   - **NON** → stop définitif du plan sur cette piste ; note dans `bilan_v0.md`
     (« le canal undergrowth n'apporte rien sur nos données » est un résultat).
   - **OUI** → Phases 2 et 3 débloquées.

Implémentation de référence : `work/expe/undergrowth/expe_undergrowth.py`
(`strata` | `candidates` | `planche` | `kernel_test`), configs
`work/expe/configs/undergrowth_01..04.yaml`.

---

## 3. PHASE 2 — recouvrement LiDAR : mesurer, pas corriger

1. **Carte de recouvrement** : ∩ des emprises de dalles (noms/bbox des tuiles) →
   `overlap.tif` 0/1. Aucune modification de code.
2. **Deux runs expérimentaux** sur une tuile en recouvrement + une tuile témoin :
   comptages de strates **avec** et **sans** `voxeldownsize(0,5, first)`
   (deux JSON dans `work/expe/pipelines/`).
3. **Carte du biais** (ratio des densités avec/sans) + chiffres : médiane du ratio en
   recouvrement vs hors recouvrement, par strate.
4. **PORTE 2 = vous regardez la carte du biais.**
   - biais négligeable → clos par une note (résultat négatif tracé) ;
   - biais réel → **correction expérimentale** (comptages corrigés dans `work/expe/`)
     comparée par planche + mesures ; `run_terrain.py` ne sera touché que par un commit
     de code propre post-porte.

Le critère « biais divisé par 2 » de la v1 est abandonné : arbitraire.

---

## 4. PHASE 3 — médian vs gaussien : même signal, mêmes seuils

Seule variable = le lissage (R3). Représentation fixée = comptages de strates 1 m.

- **A** = comptages + **médian** (fenêtres équivalentes aux medianboxsize KP 9 puis 17 px,
  appliquées aux classes construites depuis les comptages) ;
- **B** = mêmes comptages + **gaussienne** σ1 = 1 m (strate medium) / σ2 = 2 m (low) ;
- **mêmes seuils** (pt/m²) appliqués ensuite à A et à B ;
- planche A / B / FFCO (+ KP actuel pour mémoire), fenêtre V0.4, 1:10 000.

**PORTE 3 = vous regardez** (protocole de jugement mbs2 : lisibilité vs fidélité).
Si B gagne : commit de code propre = option de lissage **après mosaïque** dans le pont
KP / `process_hag`, paramètre gelé dans `config.yaml`, planche de décision dans
`docs/images/`.

---

## 5. PHASE 4 — seulement si les portes 1–3 sont passées ; un sujet à la fois

Chaque sujet = sa planche, sa porte, son verdict. Ordre imposé :

- **4a fusion undergrowth → verts** : modes `none | merge | layer409` (sémantique
  Cassini, noms ISOM). `merge` = ajout au canal medium **avant seuillage** (pas un
  rehaussement de classe). `layer409` = couche .omap 409, **exclue de
  `coverage_partition`** (409 se superpose par conception) — fait le pont avec le
  plan 2, tâche V5.
- **4b découvert « min canopée »** : MIN du canal high (4, 30] sur fenêtre 5×5 m vs
  `yellow_threshold` ; mesure de désaccord avec BD TOPO / OSM ; **aucune** modification
  automatique du jaune (le jaune reste BD TOPO/OSM, protocole vectorisation §É2).
- **4c comparaison mapant.fr** : **d'abord** lire les conditions d'utilisation du
  service de tuiles ; puis planche de diff sur Grimbosq = contrôle indépendant
  (LiDAR HD France grande échelle), jamais une dépendance du produit.
- **4d seuil KP gaté par l'undergrowth** (piste planche D) : abaissement du premier
  seuil appliqué **seulement là où** le canal undergrowth = 1. **Condition absolue :**
  la note V0.1 confirme la sémantique supposée ; sinon abandon sans test.

---

## 6. Ce que ce plan ne fait pas

- Aucun critère `qa.py` comme porte (R1).
- Aucun commit par essai ; aucun paramètre dans `config.yaml` avant porte (R2, R6).
- Aucune modification de `run_terrain.py` / `process_hag.py` / `kp_raster.py` /
  `main.py` / `config.yaml` avant porte passée (R4 de la revue).
- Aucune branche git d'expérimentation (R5).
- Pas de ML/scoring (avenant 02 §0) ; pas de copie de code Cassini (GPL-3.0) :
  réimplémentation clean-room des formules, ou image Docker `nicorio42/cassini`
  appelée comme outil séparé pour comparaison.
- Pas de test terrain : toutes les mesures se font sur dalles et références existantes.

## 7. Definition of done, phase par phase

| Phase | Done |
|---|---|
| 0 | `phase0_notes.md` : sémantique greenshades, JSON strates, inventaire données + bbox planches |
| 1 | planche 4 panneaux 1:10 000 produite **et regardée** ; verdict commité (même négatif) |
| 2 | carte du biais + chiffres commités ; décision corrigé/pas-corrigé tracée |
| 3 | planche A/B commitée ; verdict ; si positif, code propre + paramètre gelé |
| 4 | chaque sujet a son verdict ; 409 éventuel raccordé au plan 2 V5 |

---

## Annexe — veille Cassini/mapant (résumé de la v1, sources vérifiées 2026-09-30)

F1 trois strates (0,1]/(1,4]/(4,30] comptées à 1 m, classification IGN végétation
ignorée, sol = classe 2 (`lidar.rs`) · F2 undergrowth = canal low lissé gaussienne
rayon 4, seuil pt/m², modes merge/406/409 (`vegetation.rs`) · F3 verts = gaussienne
rayon 2 sur la strate medium, seuils 0,2/1,0/2,0 pt/m² (blog) · F4 blanc = MIN du canal
high sur cercle 5×5 > yellow_threshold · F5 `voxeldownsize` 0,5 m mode first avant
comptage · F6 VRT tuile+voisines buffer 200 m avant lissage → sans couture ·
F7 `mapant-scripts/lidar_delete_overlap` écarte les tuiles en recouvrement → le
recouvrement LiDAR HD est un problème connu de la production française · F8 lissage
gaussien sur densités, pas médian sur indices · F9 famille mapant (fi/no/es/lu,
gokartor.se) = KP, ch = OCAD : **Cassini est le seul moteur avec undergrowth**.
Sources : github.com/NicoRio42/cassini (GPL-3), github.com/NicoRio42/mapant-scripts,
mapant.fr/blog/cassini-pour-les-nuls, cassini-map.com/what-and-why.
