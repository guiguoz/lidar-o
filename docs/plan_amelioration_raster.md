# PLAN 1 — Améliorer le raster végétation, avant toute vectorisation

> **Brief destiné à Claude Code (ou tout exécutant).** Autonome : tout le contexte
> nécessaire est ici + les fichiers cités. Ne pas toucher à la vectorisation
> (voir `docs/plan_vectorisation.md`, plan séparé).
> **État au 2026-09-30.** `medianboxsize2 = 16` est **figé** (tranché par jugement
> cartographique, planches `docs/images/vege_mbs2_*.png`). `greenshades` reste à la
> valeur de production. Le problème ouvert est unique : **le sous-bois léger n'est
> pas détecté**, et aucun paramètre KP testé n'y change rien.
> **Interdit :** ML/scoring (avenant 02 §0), tests terrain chronophages, copier du
> code Cassini (GPL-3.0 — réimplémentation « clean room » des *idées* seulement, ou
> exécution de Cassini comme processus Docker séparé).

---

## 1. Ce que mapant.fr apporte (sources vérifiées le 2026-09-30)

**Oui, il y a de l'information décisive sur mapant.fr.** Le projet (Nicolas Rio) a
produit **Cassini** ([github.com/NicoRio42/cassini](https://github.com/NicoRio42/cassini),
GPL-3.0, Rust, 207 commits, dernière release 0.16.0 *« Improved vegetation rendering
algorithm + undergrowth rendering »*), moteur de rendu de **toute la carte de France**
de mapant.fr à partir du LiDAR HD IGN — *nos* données, *notre* pays, *notre* échelle.
Lecture de `src/lidar.rs`, `src/vegetation.rs`, `src/config.rs`, `src/buffer.rs` :

| # | Fait Cassini/mapant | Fichier source | Pourquoi ça nous concerne |
|---|---|---|---|
| F1 | Trois strates LiDAR séparées, comptage 1 m uint8 : **low = HAG (0,1]**, **medium = (1,4]**, **high = (4,30]** ; sol = classe IGN 2 conservée, végétation **reclassifiée par HAG** (la classification IGN végétation n'est pas jugée fiable) | `lidar.rs` (pipeline PDAL) | notre `band_split` (Étape D) a low 0,3–1,3 / mid 1,3–4,0 mais **sans canal undergrowth** |
| F2 | **Undergrowth = canal indépendant** : moyenne gaussienne **rayon 4 (σ≈2 m)** du canal low, seuil `low_vegetation_density_threshold` (défaut 1 pt/m²) ; 3 modes : `merge` (s'additionne à la densité medium → devient du vert), `406` (vert clair), `409` (PNG séparé) | `vegetation.rs` (`UndergrowthMode`) | **c'est exactement le sous-bois léger qui nous manque** : KP le noie dans une densité unique puis le médian l'efface |
| F3 | Verts = moyenne gaussienne **rayon 2 (σ≈1 m)** du canal **medium** ; seuils en **points/m²** (blog : 0,2 / 1,0 / 2,0 ; défauts code : 1/2/3) | `vegetation.rs`, `config.rs` | seuils *physiques* et interprétables, vs `greenshades` KP sans unité |
| F4 | Blanc/jaune = **MIN** du canal high sur un cercle 5×5 > `yellow_threshold` (blog 0,5) : toute trouée de canopée → jaune | `vegetation.rs` | test de découvert déterministe, complémentaire BD TOPO |
| F5 | `filters.voxeldownsize` **cell 0,5 m, mode first** avant reclassification | `lidar.rs` | tue le double-comptage des **recouvrements LiDAR HD** ; notre pipeline (`filters.hag_nn`) ne le fait **pas** |
| F6 | VRT tuile + **voisines, buffer 200 m** avant tout lissage → **pas de couture inter-tuiles** | `buffer.rs` | nos coutures KP (médian par tuile) sont un risque listé au protocole §5 |
| F7 | `mapant-scripts` (scripts de production mapant.fr) contient **`lidar_delete_overlap`** : les tuiles des zones de recouvrement sont *mises de côté* | `mapant-scripts/lidar_delete_overlap/` | confirme : le recouvrement LiDAR HD est un problème connu de la production française |
| F8 | Lissage **gaussien sur densités** (linéaire) et non médian sur indices : le gradient du sous-bois léger survit | `vegetation.rs` | piste pour remplacer/compléter le médian KP *après* mosaïque |
| F9 | Famille mapant : fi/no/es/lu + gokartor.se = Karttapullautin ; ch = OCAD ; **Cassini est le seul moteur avec undergrowth** | cassini-map.com/what-and-why | il n'y a pas d'autre État de l'art à aller chercher sur l'undergrowth |

**Conséquence directe :** améliorer le raster ne demande **aucun test terrain**. Les
gains sont *structurels* (strates, canal undergrowth, voxeldownsize, buffer) et se
mesurent sur ce qu'on a déjà : dalles Grimbosq en `LIDAR/` (si présentes), raster KP
en `out_kp_grimbosq/`, carte FFCO de référence (`qa_targets`), planches A/B
(`docs/images/`), métriques `src/qa.py`. Un rendu A/B sur tuiles existantes = minutes,
pas jours.

---

## 2. Objectifs, dans l'ordre

Chaque objectif = 1 commit + mesure avant/après. Paramètres **dans `config.yaml`**
(section `vegetation.raster_improvements` à créer), jamais en dur.

### O1 — Canal undergrowth (cible : le problème ouvert)
- PDAL : comptage 1 m uint8 de la strate **HAG (0,3–1,0]** (borne basse = notre seuil
  de bruit 0,3 ; variante (0–1] à tester) → `output/undergrowth_count.tif`.
- Lissage gaussien σ = 2 m (noyau rayon 4, normalisé — même forme que Cassini).
- Seuillage `undergrowth_threshold` (pt/m², départ 1,0 comme Cassini) →
  `output/undergrowth.tif` (0/1) + ha couverte dans le log.
- **Acceptation :** (a) le canal couvre visiblement les zones de sous-bois léger
  identifiées sur la planche D de l'expérimentation mbs2 ; (b) recouvrement avec le
  406/408 KP existant < 50 % (sinon ce n'est pas de l'information nouvelle) ;
  (c) rappel FFCO 408+410 de la sortie combinée ≥ rappel actuel (mesure `qa.py`).

### O2 — Voxel downsize anti-recouvrement
- Ajouter `filters.voxeldownsize` (cell 0,5, mode `first`) dans le pipeline PDAL
  (`scripts/run_terrain.py`) **avant** `hag_nn`/comptages.
- Mesurer le biais de recouvrement : densité médiane dans les zones de recouvrement
  LiDAR HD (emprises de dalles ∩, calculables depuis les bbox des tuiles) vs ailleurs,
  avant/après. Script diag `scripts/diag/measure_overlap_bias.py`.
- **Acceptation :** biais |Δ| divisé par ≥ 2 ; densités hors recouvrement inchangées
  à ± 3 %.

### O3 — Mosaïque bufferisée avant lissage (coutures)
- Source `kp` : le médian KP est par tuile (inchangeable). Ajouter après mosaïque
  (`src/kp_raster.mosaic`) un lissage de raccord : recomputation des classes sur une
  bande de 200 m autour des joints ? **Non** — plus simple et fidèle à Cassini :
  pour la source `pdal`, lisser (O4) **après** mosaïque VRT voisines+buffer ; pour la
  source `kp`, mesurer l'amplitude réelle des coutures (diff de classes le long des
  joints) et ne corriger que si > 1 % des pixels de joint.
- **Acceptation :** mesure de couture publiée dans `docs/bilan_v0.md` ; correction
  uniquement si le seuil est dépassé (ne pas complexifier sans preuve).

### O4 — Lissage gaussien sur densité vs médian sur indices (A/B)
- Produire deux rasters classifiés Grimbosq : (A) pipeline actuel, (B) comptages
  strates + gaussienne σ1 (medium) / σ2 (low) + seuils pt/m² inizés sur les quantiles
  du raster A (pas de recalibration terrain).
- **Acceptation :** planche `docs/images/raster_ab_gaussien.png` (A, B, FFCO) + table
  `qa.py` ; décision cartographique documentée comme pour mbs2 (c'est le protocole qui
  a tranché medianboxsize2).

### O5 — Fusion undergrowth → verts, trois modes
- `undergrowth_mode: none | merge | layer409` (noms Cassini, sémantique ISOM) :
  - `merge` : les pixels undergrowth montent d'une classe de vert (406→408 interdit :
    merge = **ajout au canal medium avant seuillage**, pas un rehaussement de classe) ;
  - `layer409` : `undergrowth.tif` devient une couche .omap 409 (symbole présent dans
    le gabarit) — **pont vers le plan 2, task V5** ;
  - `none` : raster de diagnostic seulement.
- **Acceptation :** les trois modes tournent sur la démo synthétique
  (`scripts/diag/demo_vectorisation_kp.py`, étendu d'un canal low) sans erreur ;
  choix par défaut `none` tant que O1 n'est pas validé.

### O6 — Test de découvert « min canopée » (optionnel, si O1–O5 passent)
- MIN du canal high (4–30 m) sur fenêtre 5×5 m < seuil → candidat ouvert ; intersection
  avec BD TOPO `zone_de_vegetation`/OSM : mesurer les désaccords (le LiDAR voit des
  trouées que la BD TOPO ignore, et inversement).
- **Acceptation :** table de désaccord ha ; **aucune** modification automatique du
  jaune/401 sans validation humaine (le jaune reste BD TOPO/OSM, protocole §É2).

### O7 — Cible externe : les tuiles publiées de mapant.fr
- mapant.fr sert une pyramide de tuiles PNG (scripts de production = tile pyramid).
  Télécharger la couverture Grimbosq (~quelques tuiles 1:10 000), la géoréférencer
  (grille Web Mercator standard), produire une planche de diff contre notre raster.
- **Vérifier la licence/CGU avant tout usage** ; usage réservé : calibration visuelle
  et extraction de leurs seuils effectifs, **pas** de redistribution dans le dépôt.
- **Acceptation :** planche diff + note : leurs masses de sous-bois apparaissent-elles
  là où notre canal O1 apparaît ? (validation croisée indépendante de la FFCO)

### O8 — `greenshades[0] < 0,2` **gate** par l'undergrowth (piste planche D, enfin testable)
- Uniquement si O1 validé : appliquer l'abaissement du premier seuil KP **seulement
  là où** `undergrowth.tif = 1` (masque), pas globalement → pas de confetti général.
- **Acceptation :** planche A/B + % de pixels modifiés ; si le gain de rappel 408/410
  est < 2 points, abandonner et le dire dans `bilan_v0.md`.

---

## 3. Méthode, contraintes, pièges

- **Mesurer d'abord, changer ensuite** : O2 et O3 commencent par un script de mesure
  (`scripts/diag/`), pas par une modification.
- Chaque seuil nouveau part de la valeur Cassini (pt/m²) puis se règle sur **quantiles
  du raster Grimbosq existant** — jamais à l'œil, jamais sur le terrain.
- Le protocole de décision cartographique est celui de mbs2 : planche 3 panneaux
  (notre raster / variante / FFCO) + métriques `qa.py` + verdict écrit dans
  `docs/bilan_v0.md`.
- **GPL-3.0 :** ne pas copier-coller de code Cassini. Réimplémenter les formules
  (gaussienne normalisée rayon r, strates HAG, min 5×5) depuis zéro dans
  `src/metrics.py` / `scripts/process_hag.py`, ou appeler l'image Docker
  `nicorio42/cassini` en processus séparé pour comparaison (usage outil, pas lien).
- Ne pas réouvrir : `medianboxsize2`, `vegetation.source`, la vectorisation (plan 2),
  les symboles 407/416/419 (humains).
- Sorties intermédiaires dans `work/` (gitignoré) ; seules les planches
  `docs/images/*.png` et les docs sont commitées.

## 4. Definition of done du plan

1. `undergrowth.tif` produit sur Grimbosq, seuil gelé dans `config.yaml`, rappel FFCO
   408+410 ≥ valeur actuelle, planche diff commitée.
2. Biais de recouvrement LiDAR HD mesuré et, si > 5 %, corrigé (voxeldownsize).
3. Amplitude des coutures inter-tuiles mesurée et documentée (corrigée seulement si
   > 1 % des pixels de joint).
4. Décision gaussien-vs-médian tranchée par planche + métriques, verdict dans
   `bilan_v0.md`.
5. Note mapant.fr (licence + planche diff) dans `docs/bilan_v0.md`.
6. Aucun test terrain n'a été nécessaire ; chaque verdict cite une mesure reproductible
   (commande + commit).
