# Portabilité du pipeline — hypothèses françaises trouvées

Premier test hors France : terrain Kilemäed (Estonie), EPSG:3301 (L-EST97).  
Run de référence : `python main.py kilemaed --skip-pdal` — 2026-08-11.

---

## Résumé rapide

| # | Hypothèse | Gravité | État |
|---|-----------|---------|------|
| H1 | EPSG:2154 codé en dur dans les fonctions OSM | Bloquant | **Corrigé** |
| H2 | `fetch.py` appelle la Géoplateforme IGN (France) | Bloquant | **Contourné** (skip si absent de `departement`) |
| H3 | `out_kp/` partagé entre terrains — DXF Grimbosq injectés silencieusement | Carte invalide | **Corrigé** (garde-fou bbox dans `build_relief_layers()`) |
| H4 | `crs: EPSG:2154` global dans `config.yaml` | Potentiellement bloquant | Identifié — **à vérifier** (PDAL non testé) |
| H5 | Profil QA `grimbosq_v0` utilisé par défaut | Non bloquant | Identifié — acceptable pour test |
| H6 | BD TOPO absente → masque dégradé silencieux | Non bloquant | Géré (warning + OSM-only) |
| H7 | `declination` georef XML = convergence méridienne, pas déclinaison magnétique | Carte tordue | **Corrigé** (`-1.27°` au lieu de `+8.3°`) |
| H8 | GPKG avec noms de tables encodés en latin-1 — `load_ffco_hull()` échoue | QA sans référence | **Corrigé** (OGR Python bindings, accès par index) |

---

## Détail des hypothèses

### H1 — EPSG:2154 codé en dur (OSM reprojection)

**Fichier** : `scripts/mask_vegetation.py`  
**Fonctions** : `_fetch_osm`, `_osm_mask_from_cache`, `_osm_geoms_by_tag`

Les trois fonctions utilisaient `EPSG:2154` comme CRS source/cible fixe.
Pour Kilemäed (EPSG:3301), la reprojection vers WGS84 (Overpass) aurait produit des coordonnées fausses.

**Correction** : ajout des paramètres `source_crs`/`target_crs` (défaut `EPSG:2154` — rétrocompatible),
threadés depuis `build_mask()` et `build_fill_layers()` via `terrain_crs`.
`main.py` lit `cfg["terrains"][terrain]["crs"]` et passe `terrain_crs` à chaque appel.

---

### H2 — `fetch.py` appelle la Géoplateforme IGN (France uniquement)

**Fichier** : `scripts/fetch.py`

Le script télécharge le GPKG BD TOPO IGN par département français (`D0{dept}`).
Sans équivalent pour le géodonnées estonien (Maa-amet), il échouerait pour Kilemäed.

**Contournement** : `main.py::step_fetch()` vérifie la présence de la clé `departement` dans
le terrain config. Si absente, l'étape est ignorée avec un log INFO. Un `fetch_maaamet.py`
dédié est hors périmètre de cette itération.

---

### H3 — `out_kp/` partagé entre terrains (problème critique) — CORRIGÉ

**Fichier** : `main.py::step_assemble()`, `scripts/generate_relief.py`

Le répertoire `out_kp/` est unique à la racine du projet. Les 42 DXF présents sont de
Grimbosq (noms `LHD_FXX_0448_6887_...`, coordonnées Lambert 93). Ils ont été inclus dans
le premier `kilemaed.omap` — la carte contenait des courbes de niveau normandes.

**Correction** : garde-fou bbox dans `build_relief_layers()`. Si `bbox` est fournie,
chaque segment et point est testé contre l'emprise du terrain. Si 0 géométries sur N
passent le filtre, un WARNING explicite est émis et le relief est ignoré.

```
WARNING  GARDE-FOU relief : 0/754 géométries dans l'emprise —
         DXF probablement issus d'un autre terrain. Relief ignoré.
```

Le répertoire `out_kp/` reste partagé (pas renommé) — la séparation par terrain est
un futur refactoring. Le garde-fou bloque silencieusement le bug en attendant.

---

### H4 — `crs: EPSG:2154` global dans `config.yaml`

**Fichier** : `config.yaml` ligne 1

```yaml
crs: EPSG:2154
scale: 10000
```

Ce `crs` global est potentiellement lu par certains scripts via `cfg["crs"]` plutôt que
`cfg["terrains"][terrain]["crs"]`. À vérifier : `src/vegetation.py`, `process_hag.py`,
et tout script qui lit `cfg` directement.

**État** : identifié — à auditer. Si un script utilise `cfg["crs"]` au lieu de
`cfg["terrains"][terrain]["crs"]`, les rasters seront traités comme du Lambert 93
même pour Kilemäed.

**Premier candidat** : `scripts/run_terrain.py` (pipeline PDAL) — non testé car `--skip-pdal`.

---

### H5 — Profil QA `grimbosq_v0` par défaut

**Fichier** : `src/qa.py`, `config.yaml`

Le profil de généralisation actif (`active_profile: grimbosq_v0`) et les cibles FFCO
sont spécifiques à Grimbosq. La QA de Kilemäed utilise donc les cibles françaises :
- `max%406 : 23.4%` → alerte percolation (>15%) basée sur seuil Grimbosq
- Comparaisons `dmed` / `d%<1` vs FFCO Grimbosq : sans signification pour l'Estonie

**État** : non bloquant pour un test de portabilité (la QA s'affiche et ne plante pas).  
La carte estonienne de référence (`rapports/kilemaed/`) permettra d'ajouter un profil
`kilemaed_v0` ultérieurement.

---

### H6 — BD TOPO absente : masque et fill dégradés

**Contexte** : Kilemäed n'a pas de BD TOPO compatible.

`step_mask()` : absence de `kilemaed_bdtopo.gpkg` → warning + masquage OSM uniquement
(3.7 ha de zones agricoles OSM masquées).  
`step_assemble()` : absence de BD TOPO → warning + couches BD TOPO ignorées.
Les fills OSM (zone_401 = 3.75 ha farmland) sont conservés.

**État** : géré proprement. Les fonctions `build_mask()` et `build_fill_layers()`
acceptent `bdtopo_gpkg=None` via try/except sur les lectures GPKG.

---

## Ce qui a fonctionné sans modification

- **OSM masking** : requête Overpass en WGS84 (bbox reprojetée depuis EPSG:3301) — OK
- **`vegetation.gpkg`** existant : réutilisé via `--skip-pdal` — OK
- **`georef_kilemaed.xml`** : EPSG:3301 + déclinaison +8.3° — OK
- **`write_omap()`** : le géoréférencement est lu depuis le XML, pas codé en dur — OK
- **`omap_writer.py`** : CRS-agnostique (travaille en coordonnées projetées) — OK
- **`output_dir: output_kilemaed`** dans config → OUTPUT terrain-spécifique — OK

---

### H7 — `declination` georef XML = convergence méridienne, pas déclinaison magnétique

**Fichier** : `assets/georef_kilemaed.xml`

L'attribut `declination` de l'élément `<georeferencing>` OOM est la **convergence
des méridiens** (angle entre nord grille et nord géographique au point de référence),
pas la déclinaison magnétique.

Pour EPSG:3301 au point (413000, 6483000) :
```
convergence = (λ - λ₀) × sin(φ) = (22.51° - 24°) × sin(58.48°) = -1.27°
```
OOM a détecté la discordance avec la valeur déclarée (+8.3°, déclinaison magnétique)
et corrigé automatiquement à -1.27°.

**Correction** : `declination="-1.27"` dans `georef_kilemaed.xml`.  
La déclinaison magnétique (+8.3°E) n'est pas un paramètre du georef XML — elle
s'ajoute manuellement dans les paramètres carte OOM si nécessaire.

**Nota** : pour Grimbosq (EPSG:2154), la déclinaison magnétique (~-2.4°) et la
convergence méridienne (~-2.4°) coïncident par hasard, ce qui masquait ce bug.

---

## Couverture OSM Kilemäed

Requête Overpass bbox : `58.467°N, 22.490°E → 58.488°N, 22.530°E` — coordonnées correctes
(reprojection EPSG:3301 → WGS84 opérationnelle).

Résultat : 1523 éléments, dont 3 ways avec tags pertinents :
- `landuse=forest` : 2 polygones (non soustraits — forêt = cible, pas masque)
- `landuse=farmland` : 1 polygone → 3.75 ha (couche 401 dans la carte)

Couverture faible confirmée : Kilemäed est un terrain forestier estonien, peu d'agriculture
ni de zones résidentielles cartographiées. La reprojection est correcte.

---

### H8 — Noms de tables GPKG encodés en latin-1

**Fichier** : `src/qa.py::load_ffco_hull()`  
**Terrain** : Kilemäed (GPKG exporté depuis OOM en latin-1)

Le fichier `Kilemäed.gpkg` stocke les noms de tables comme bytes latin-1 :
`b'Kilem\xe4ed_areas'` (`\xe4` = ä en latin-1). GDAL/ogr2ogr utilise UTF-8
en interne → la couche spécifiée en ligne de commande (`Kilemäed_areas`, UTF-8)
ne correspond pas au nom stocké (`\xe4` ≠ `\xc3\xa4`).

Deux problèmes distincts sur Windows :
- `pathlib.Path("autres cartes/Kilemäed.gpkg").exists()` → False malgré l'existence
  du fichier (encodage NTFS vs Python Unicode). **Résolu** : glob fallback `Kilem*.gpkg`.
- `ogr2ogr ... path.gpkg Kilemäed_areas` → "fetch requested layer: layer not found".
  **Résolu** : fallback `_load_hull_from_sqlite()` qui utilise les bindings OGR Python.

OGR Python accède aux couches par index (`GetLayerByIndex(i)`) et passe les noms de
tables comme bytes bruts au C sqlite3. Le nom de couche retourné contient un caractère
surrogate (`'Kilem\udce4ed_areas'`) mais l'accès aux features fonctionne.
La table `gpkg_geometry_columns` confirme la colonne géométrie : `b'geom'`.

```python
# Preuve : 208 features végétation trouvées par OGR
# Layer [2] 'Kilem\udce4ed_areas', 429 features
# matched : 169×'Vegetation: slow running' + 35×'Vegetation: walk' + 4 truncated
```

---

## Calibration Kilemäed — verdict

Le pipeline est **portable techniquement** mais **hors portée cartographiquement**.

### Comptages

**Emprise globale (sans clip) :**

| Classe | Pipeline | Cartographe | Ratio |
|--------|----------|-------------|-------|
| 406 (lent) | 3024 | 169 | ×18 |
| 408 (marche) | 2561 | 35 | ×73 |
| 410 (combat) | 1899 | 0 | ∞ |

**Dans le hull convexe végétation FFCO (178.5 ha) :**

| Classe | cov% pipeline | n | med mm² | %<1mm² | max% |
|--------|--------------|---|---------|--------|------|
| 406 | 25.5% | 325 | 2.14 | 11.4% | 19.9% |
| 408 | 16.6% | 254 | 2.24 | 9.4% | 19.1% |
| 410 | 7.9% | 274 | 1.64 | 28.8% | 7.6% |

Note : le rapport affiche aussi les cibles Grimbosq FFCO (profil `grimbosq_v0` actif)
pour cohérence de format, mais ces cibles sont sans signification pour Kilemäed
(terrains différents). La colonne `dcov` compare vs cibles normandes, pas vs FFCO Kilemäed.

### Explication

Kilemäed est un terrain de landes et marais (Estonie, côte ouest).
Le sol est couvert de sphaignes, bruyères et buissons bas qui renvoient
un signal LiDAR dense à 0.3–3 m de hauteur — **identique optiquement à
une végétation forestière dense** pour le pipeline basé sur HAG.

La couche 410 (combat, végétation dense empêchant la course) produit 1899
polygones là où le cartographe en compte 0 : Kilemäed n'a pas de forêt
fermée. Le pipeline classe comme 410 des formations qui sont cartographialement
« terrain découvert avec végétation basse » (401/402/403).

**Conclusion** : les seuils HAG (0.3–3 m) et les seuils de densité calibrés
sur Grimbosq (forêt feuillue mature normande) ne sont pas transférables à
un terrain de landes boréales. Le profil nécessiterait un recalibrage complet
sur corpus estonien — hors périmètre Phase 1.

### Ce que le test confirme

- L'orchestrateur `main.py` est portable (8 étapes, 2 terrains, sans crash)
- Les hypothèses H1–H8 sont documentées et corrigées ou contournées
- La QA s'affiche et lit le hull de référence FFCO via OGR (H8 corrigé)
- Le garde-fou H3 (bbox relief) fonctionne
- L'hypothèse fondamentale — HAG = végétation orienteering — n'est valide
  que pour les terrains forestiers tempérés (scope Phase 1 confirmé)

---

## Diagnostic banding

Le raster `density_hag.tif` de Kilemäed présente un artefact de bandes.

Mesures brutes (σ des moyennes par ligne / par colonne) :

| Terrain | σ_row | σ_col | ratio |
|---------|-------|-------|-------|
| Grimbosq | 4.08 | 2.47 | **1.65** |
| Kilemäed | 0.30 | 0.16 | **1.86** |

**La métrique σ_row/σ_col ne tranche pas.** Grimbosq a un ratio de 1,65 — la
variation inter-lignes y est structurellement plus forte, reflet de la variation
naturelle du couvert forestier en direction N-S (topographie, lisières). Le ratio
similaire sur Kilemäed signifie que le test capte autant de variation spatiale
réelle que d'artefact éventuel. **Formulation retenue :** le banding est visible
sur Kilemäed, son origine n'est pas formellement attribuée.

L'argument de rapport signal/bruit reste valable comme explication du fait que
la variation est imperceptible à Grimbosq (~150 retours/m²) et visible à Kilemäed
(~3,77 pts/m²), mais ce n'est pas une preuve que l'artefact est de même amplitude.

**Diagnostic formel, si nécessaire (terrain de production estonien) :**

1. **FFT des moyennes par colonne** — les strips sont N-S, donc la périodicité
   apparaît dans le profil des moyennes par colonne (pas par ligne). Un pic net
   à une fréquence correspondant à une largeur de bande plausible (200–500 m selon
   l'altitude de vol et l'angle de balayage) confirme l'origine ; un spectre plat
   indique une variation naturelle.

2. **Contrôle `PointSourceId`** — méthode décisive : rasteriser l'identifiant
   de ligne de vol (attribut `PointSourceId` du LAS) et vérifier si les frontières
   de strips coïncident avec les discontinuités de densité. Un passage PDAL
   supplémentaire avec `writers.gdal` sur le champ `PointSourceId`. C'est la
   machinerie mise en place pour H3 (dépendance angulaire de l'intensité).

**Pas de correction dans ce run.**

---

## Résultat final

```
output_kilemaed/kilemaed.omap  — 4 couches
  406 : ~3024 polygones  (cible FFCO Kilemäed : 169)
  408 : ~2561 polygones  (cible FFCO Kilemäed : 35)
  410 : ~1899 polygones  (cible FFCO Kilemäed : 0)
  401 : 1 polygone (3.75 ha farmland OSM)
  declination = -1.27° (convergence méridienne L-EST97)
```

Le `.omap` s'ouvre dans OOM sans alerte, avec les polygones aux coordonnées EPSG:3301
correctes. Pas de courbes de niveau (garde-fou H3 a rejeté les DXF Grimbosq).

**Portabilité technique : OK. Portabilité cartographique : Hors portée.**  
Scope validé : Phase 1 = terrains forestiers tempérés (Grimbosq, Airelles).

---

## Kuti (Estonie, EPSG:3301) — Hors portée, cause distincte

Run : `python main.py kuti --skip-pdal` — 2026-08-13. 20 dalles LiDAR Maa-amet.  
Hull FFCO : `autres cartes/Kuti.gpkg`, layer `Kuti_areas`.

### Résultats QA dans le hull

| Classe | cov% pipeline | n | cible FFCO |
|--------|--------------|---|------------|
| 406 | 19.3% | 463 | — |
| 408 | **37.6%** | 432 | — |
| 410 | 8.0% | 363 | — |

`max%408 = 32.3%` — blob massif. Les 38,4 ha de 408 existent **avant toute fusion**,
dans le raster classifié. Ce n'est pas un artefact de généralisation.

### Cause racine

Kuti est une épicéaie dense à sous-bois de *Vaccinium myrtillus* (myrtille).
Le signal HAG[0.3–3 m] est **uniformément dense** sur toute l'emprise.

Mesures à 2 m de résolution :
- `p50_nz = 53` retours/cellule (vs Grimbosq `p50_nz = 28`)
- `p95/p50 = 6,4` (vs Grimbosq `24,7`)

La plage dynamique est compressée : après normalisation `p95_local`, la quasi-totalité
des cellules tombe dans [0,3–0,8] — au-dessus du seuil T_408 = 0,45. Le pipeline
ne peut pas distinguer « beaucoup » de « peu » de végétation quand tout le signal
est dans la même fourchette.

### Hypothèses testées et fermées

| Hypothèse | Test | Résultat |
|---|---|---|
| H-norm : p95_local gonfle le signal | `fixed_percentile=31.018` (p95 Grimbosq) | QA inchangé — H fermée |
| H-zero : zéros HAG = vides à masquer | `mode=ratio, n_min=1` | 0,2% masqué — H fermée |
| H-res : agrégation 2 m réduit le bruit | `grid_resolution_m=2` | QA inchangé (38,1% vs 37,6%) — H fermée |

**Cause confirmée** : dynamique insuffisante, pas un problème de normalisation, de masquage
ou de résolution.

### Mode de défaillance

Différent de Kilemaed. À Kilemaed, l'échec vient d'un **désaccord sémantique** (végétation
basse en terrain ouvert ≠ sous-bois sous canopée). À Kuti, l'échec vient d'un **signal
indifférencié** : HAG dense et uniforme partout → impossible de distinguer les classes.

---

## Analyse du corpus disponible — 2026-08-13

Six cartes disponibles. Surface FFCO analysée par extraction XML des coordonnées omap.

| Terrain | 403 cov% | Vert (406+408+410) | Eau/HorsLimite | Verdict |
|---|---|---|---|---|
| Grimbosq | ~0% | ~15% (406 seul) | — | Dans le domaine |
| Airelles | élevé | élevé mais indiscernable | — | Hors portée (indiscernabilité) |
| Kilemäed | — | fort faux positif | — | Hors portée (désaccord sémantique) |
| Kuti | — | 37,6% cov 408 | — | Hors portée (signal uniforme) |
| Sandringham | **35,7%** (370 ha) | 6,6% sur 1039 ha | — | Hors portée probable (même type Kilemäed) |
| Broadland | 3,2% | 4,1% sur 826 ha | ~299 ha (code 601) | Inconnu — forêt humide |

### Sandringham — analyse de surface (EPSG:27700)

Bbox BNG : `[567099, 326300, 570024, 329852]` (~1039 ha)  
Le compte de 554 objets 410 était trompeur : la surface moyenne est 0,08 ha (touffes isolées).  
Le terrain est dominé par la lande ouverte (35,7%) — profil comparable à Kilemäed.  
Test inutile pour la question qui bloque : produirait un quatrième cas du mode déjà documenté,
pour un chantier d'adaptation complet (CRS 27700, portail EA, georef).

### Broadland — analyse de surface (EPSG:27700)

Bbox BNG : `[616200, 315552, 618818, 318709]` (~826 ha)  
Hydrographie identifiée : code 601 = 298 ha (Broads), 419 = 204 fossés linéaires.  
Hors eau : ~527 ha effectifs. 3,2% de lande, 6,4% de vert, **~90% de blanc**.

Le blanc n'est pas de la lande — c'est de la forêt humide (aulnaie, saussaie) sans
sous-bois symbolisé par le cartographe. Ce terrain testerait le **faux positif** :
est-ce que l'aulnaie génère assez de signal HAG pour être classée 406/408, alors
qu'elle est cartographiée en blanc (praticable) ? Aucun des quatre terrains précédents
n'a testé ce mode.

---

## Conclusion sur la délimitation du domaine de validité

### Ce que les données autorisent à dire

Le corpus de six cartes produit quatre terrains hors portée et un seul dans le domaine.
Les modes de défaillance sont distincts :

1. **Indiscernabilité inter-classes** (Airelles) : signal HAG identique entre classes FFCO
2. **Désaccord sémantique ouvert/couvert** (Kilemaed, Sandringham probable) : végétation
   basse en terrain ouvert ≠ sous-bois sous canopée en HAG
3. **Signal indifférencié** (Kuti) : dynamique compressée, impossible de distinguer les classes

Un critère unique de fiabilité automatique (p95/p50, variance, etc.) a peu de chances de
capturer les trois — chaque mode est d'une autre nature.

**Formulation rigoureuse du domaine :** le corpus disponible ne permet pas de délimiter
le domaine de validité par le haut. Un seul terrain y figure (Grimbosq), et rien ne dit
si le pipeline y fonctionne pour des raisons générales ou particulières à ce terrain.

### Le biais structurel du corpus CO

Les terrains de course d'orientation sont choisis pour leur **intérêt sportif** — variété
du terrain, mixité ouvert/fermé, contrastes géographiques. Un corpus de cartes CO est donc
structurellement biaisé contre les forêts domaniales homogènes, qui font de mauvaises
courses mais de bonnes cibles pour ce pipeline.

Grimbosq est probablement l'exception dans un corpus CO, pas la règle.

### Conséquence pratique

Cette contrainte dépasse la question de la validation. Si les terrains cartographiés en
CO sont majoritairement variés, semi-ouverts ou humides, l'outil sert rarement dans son
domaine nominal — quelle que soit la qualité du pipeline.

Trois directions possibles, mutuellement exclusives à court terme :

1. **Élargir le domaine** : traiter les landes et zones semi-ouvertes. Exige de résoudre
   le désaccord sémantique jaune/vert — problème difficile, hors périmètre Phase 1.

2. **Assumer un outil de niche** : documenter explicitement que le pipeline cible les
   forêts domaniales feuillues denses, et orienter l'utilisation en conséquence.

3. **Chercher la validation hors corpus CO** : les forêts domaniales françaises ne manquent
   pas, mais elles ne sont pas cartographiées en ISOM. Obtenir une FFCO de référence sur
   un second terrain de ce type est le seul moyen de valider la généralité.
