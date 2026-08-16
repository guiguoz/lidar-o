# Lidar'O

*[English version](README.md)*

Génération d'une carte de base ISOM à partir du LiDAR HD IGN (France), sortie en `.omap` ouvrable dans OpenOrienteering Mapper ou OCAD.

<!-- Extrait de carte représentatif à l'échelle — copier une capture dans docs/images/ -->
<!-- ![Extrait Grimbosq](docs/images/extrait_grimbosq.png) -->

---

## Pour commencer

### Prérequis

- **Python géospatial** — recommandé via [miniconda](https://docs.conda.io/en/latest/miniconda.html) :

  ```bash
  conda install -c conda-forge geopandas shapely scipy numpy python-pdal pdal
  pip install pyyaml requests ezdxf
  ```

  Ou depuis le dépôt :

  ```bash
  pip install -e .
  # Note : gdal, python-pdal et pyogrio nécessitent conda ou un wheel précompilé
  ```

- **OpenOrienteering Mapper** — [openorienteering.org](https://www.openorienteering.org/) — pour ouvrir le `.omap` produit

- **Karttapullautin** (optionnel, pour les courbes de niveau) — [github.com/karttapullautin](https://github.com/karttapullautin/karttapullautin) — à lancer manuellement sur les dalles LiDAR, sortie dans `out_kp/`

### Données d'entrée (France)

| Donnée | Source | Emplacement |
|--------|--------|-------------|
| LiDAR HD (dalles COPC, ~500 Mo/dalle) | [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd) | `LIDAR/` ou `--tiles-dir DIR` |
| BD TOPO (GPKG département) | [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo) | `data/bdtopo/` |

**Spécifique France :** le LiDAR provient de la Géoplateforme IGN HD (format COPC), la donnée anthropique de la BD TOPO v3. Hors France, voir [docs/portabilite.md](docs/portabilite.md).

Télécharger 1–3 dalles LiDAR sur votre zone. Compter 30–60 min de traitement selon la taille de l'emprise. Une seule dalle (1×1 km) suffit pour un premier test.

### Déclarer votre terrain

Ajouter une entrée dans `config.yaml` sous `terrains:` :

```yaml
terrains:
  ma_foret:
    bbox: [448000, 6886000, 451000, 6889000]  # emprise projetée (même CRS que ci-dessous)
    crs: EPSG:2154          # Lambert-93 pour la France ; EPSG:3301 pour l'Estonie, etc.
    departement: "14"       # code de département BD TOPO — à omettre hors France
```

Puis créer `assets/georef_ma_foret.xml` — il indique à OpenOrienteering Mapper où positionner la carte :

```xml
<georeferencing scale="10000" auxiliary_scale_factor="0.999966" declination="-2.5">
  <projected_crs id="EPSG">
    <spec language="PROJ.4">+init=epsg:2154</spec>
    <parameter>2154</parameter>
    <ref_point x="449000" y="6887000"/>  <!-- coordonnée ronde dans l'emprise -->
  </projected_crs>
  <geographic_crs id="Geographic coordinates">
    <spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>
    <ref_point_deg lat="49.043" lon="-0.421"/>  <!-- équivalent WGS84 — via epsg.io/transform -->
  </geographic_crs>
</georeferencing>
```

- `ref_point` : une coordonnée projetée ronde dans l'emprise (ex. 449000 / 6887000)
- `ref_point_deg` : sa conversion WGS84 sur [epsg.io/transform](https://epsg.io/transform)
- `declination` : convergence des méridiens — formule : `(longitude − méridien_central) × sin(latitude)`. Pour Lambert-93 : méridien central = 3°E. Exemple : (−0.42 − 3) × sin(49.04°) ≈ −2.58° → arrondi à 0.5° près : −2.5°
- `auxiliary_scale_factor` : facteur d'échelle de la projection — 0.999966 correct pour terrain plat en Lambert-93 ; recalculer sur [epsg.io](https://epsg.io) en zone de montagne

Voir `assets/` pour quatre exemples fonctionnels (grimbosq, kilemaed, kuti, port_en_bessin).

### Lancer le pipeline

```bash
# Premier run — traite le LiDAR de bout en bout (30–60 min selon la taille de la zone)
python main.py ma_foret --tiles-dir LIDAR/

# Runs suivants — saute PDAL si density_hag_classified.tif existe déjà (5 min)
python main.py ma_foret --skip-pdal
```

Arborescence attendue :

```
lidar-o/
├── LIDAR/                        ← dalles .copc.laz
│   └── LHD_FXX_0448_6887_...laz
├── data/bdtopo/                  ← GPKG département BD TOPO (France uniquement)
├── out_kp/                       ← DXF Karttapullautin (optionnel, pour le relief)
├── output/                       ← créé automatiquement
│   └── ma_foret.omap             ← le résultat
└── config.yaml                   ← déclarer votre terrain ici
```

Options :

| Option | Description |
|--------|-------------|
| `--tiles-dir DIR` | Répertoire des dalles `.copc.laz` |
| `--skip-pdal` | Saute PDAL (uniquement si `density_hag_classified.tif` existe d'un run précédent) |
| `--from-step STEP` | Reprend à : `fetch`, `pdal`, `process_hag`, `vegetation`, `mask`, `assemble`, `qa` |
| `--force` | Ignore les vérifications de fraîcheur et relance toutes les étapes |

Sortie : `output/{terrain}.omap`

---

## Exemple complet (Grimbosq, France)

Déroulement complet sur une zone réelle de 2 × 3 km. À utiliser comme modèle.

### 1 — Repérer les dalles LiDAR (IGN France)

Les dalles LiDAR HD IGN sont nommées par leur **bord nord** (pas leur coin SO). La dalle `LHD_FXX_XXXX_YYYY` couvre :

```
x ∈ [XXXX × 1000, (XXXX + 1) × 1000]
y ∈ [(YYYY − 1) × 1000,  YYYY × 1000]      ← YYYY est le bord NORD
```

**Exemple** — bbox `[448000, 6886000, 450001, 6889001]` en Lambert-93 :
- colonnes x : 448, 449 → `0448`, `0449`
- lignes y : bords nord 6887, 6888, 6889 → couvre y de 6886000 à 6889000

Dalles à télécharger (6 fichiers) :
```
LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz
LHD_FXX_0448_6888_PTS_LAMB93_IGN69.copc.laz
LHD_FXX_0448_6889_PTS_LAMB93_IGN69.copc.laz
LHD_FXX_0449_6887_PTS_LAMB93_IGN69.copc.laz
LHD_FXX_0449_6888_PTS_LAMB93_IGN69.copc.laz
LHD_FXX_0449_6889_PTS_LAMB93_IGN69.copc.laz
```

Télécharger depuis la [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd), déposer dans `LIDAR/`.

### 2 — config.yaml

Le terrain `grimbosq` est déjà déclaré. Pour votre propre terrain, copier le template commenté en tête de la section `terrains:`.

### 3 — Créer assets/georef_grimbosq.xml

Voir le fichier `assets/georef_grimbosq.xml` existant. Pour le remplir :

| Champ | Comment l'obtenir |
|-------|-------------------|
| `ref_point x/y` | Coordonnée projetée ronde dans l'emprise (ex. 449000 / 6887000) |
| `ref_point_deg lat/lon` | Convertir sur [epsg.io/transform](https://epsg.io/transform) |
| `declination` | Convergence des méridiens (°) : `(longitude − méridien_central) × sin(latitude)`. Lambert-93 : méridien = 3°E. Exemple : (−0.42 − 3) × sin(49.04°) ≈ −2.58° → arrondi à 0.5° près : −2.5° |
| `auxiliary_scale_factor` | Facteur d'échelle de la projection — 0.999966 correct pour terrain plat en Lambert-93 ; recalculer sur [epsg.io](https://epsg.io) en zone de montagne |

> **Attention au signe de `declination`** : négatif à l'ouest du méridien central, positif à l'est. Une erreur de signe décale tous les symboles de l'angle de convergence.

### 4 — Télécharger la BD TOPO (France uniquement)

Télécharger le GPKG du département 14 sur [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo) → « Téléchargement par département » → déposer dans `data/bdtopo/`.

### 5 — Lancer

```bash
python main.py grimbosq --tiles-dir LIDAR/
```

Temps par étape (6 dalles, ~6 km², laptop récent) :

| Étape | Ce qu'elle fait | Durée |
|-------|----------------|-------|
| `fetch` | Découpe la BD TOPO sur l'emprise | < 1 min |
| `pdal` | Rasterise la densité HAG depuis le LiDAR | 20–35 min |
| `process_hag` | Normalise et classifie le raster (3 classes) | 1–2 min |
| `vegetation` | Moteur de généralisation (dissolve → lissage → coupes) | 3–5 min |
| `mask` | Supprime routes, bâtiments, terres agricoles | 1–2 min |
| `assemble` | Fusionne toutes les couches en un .omap | < 1 min |
| `qa` | Affiche les métriques de recall (si carte de référence déclarée) | < 1 min |

> Si le pipeline semble bloqué à `pdal`, il travaille — le traitement LiDAR est intensif CPU et ne produit pas de sortie intermédiaire. Attendre au moins 5 min par dalle avant de conclure à un blocage.

### 6 — Sortie attendue

Un run réussi se termine par :
```
INFO  Assemblé : output/grimbosq.omap (18 couches)
=== QA végétation — profil 'grimbosq_v0' ===
INFO  406 : n=942  cov=35%  …
INFO  408 : n=611  cov=61%  …
INFO  410 : n=465  cov=82%  …
```

Ouvrir `output/grimbosq.omap` dans OpenOrienteering Mapper. Les couches attendues :
- Polygones de végétation verts (course lente / marche / progression difficile) sur la zone forestière
- Routes, chemins, bâtiments et cours d'eau depuis la BD TOPO (symboles noirs/bleus/marron)
- Courbes de niveau de Karttapullautin (marron) — uniquement si `out_kp/` était présent

Si la carte apparaît vide ou décalée par rapport au fond de carte, vérifier que le signe de `declination` dans le fichier georef est correct.

---

## Ce que l'outil détecte

> Mesuré sur **un seul terrain** (forêt de Grimbosq, Calvados, France), contre une carte FFCO
> de référence, sur emprise commune (hull 324 ha). Ces valeurs ne sont pas garanties ailleurs.

| Classe | Détecté | Bonne classe |
|--------|---------|--------------|
| 406 course lente | 35 % | 28 % |
| 408 marche | 61 % | 26 % |
| 410 progression difficile | 82 % | 48 % |

*« Détecté »* = fraction de la surface FFCO couverte par n'importe quelle classe du pipeline — ce que le cartographe n'a pas à dessiner.  
*« Bonne classe »* = fraction dans la bonne classe exacte — ce qu'il n'a pas à retoucher.  
Corriger le symbole prend deux clics dans OCAD/OOM ; dessiner un polygone absent de zéro prend bien plus de temps.

*Ces métriques ont été mesurées contre une carte de référence non redistribuable — les chiffres ne sont donc pas reproductibles depuis ce dépôt.*

---

## Domaine de validité

Le pipeline a été testé sur 5 terrains. Le signal HAG[0.3–3 m] sépare bien les végétations denses ; il est insuffisant pour le sous-bois léger praticable.

| Terrain | Type | Résultat 406 | Cause |
|---------|------|-------------|-------|
| Grimbosq (Normandie) | Hêtraie mature | Partiel (35 %) | Signal léger indiscernable du terrain courable |
| Airelles (Pyrénées) | Lande résineux altitude | Hors domaine | Signal HAG identique entre classes FFCO |
| Kilemäed (Estonie) | Lande/forêt mixte | Hors domaine | Désaccord sémantique ouvert/couvert |
| Kuti (Estonie) | Épicéas + Vaccinium | Hors domaine | Signal uniforme dense |
| Port-en-Bessin (Normandie) | Forêt tempérée | 408/410 détecté | Confirme le domaine dense |

**Classe 406 hors domaine, y compris sur Grimbosq.** AUC Mann-Whitney = 0.487 : la densité HAG[0.3–3 m] dans les zones 406 manquées est statistiquement indiscernable du terrain courable. Baisser le seuil crée autant de faux positifs qu'il ne récupère de vrais positifs.

**408/410 dans le domaine** sur les forêts à structuration verticale claire (forêt tempérée dense, 61 %/82 % de détection). Testé et hors domaine : landes d'altitude, landes-marais, forêts à sous-bois uniforme.

---

## QA et carte de référence

Le pipeline tourne sans référence (métriques QA limitées à la distribution de classes). Pour activer la comparaison quantitative :

1. Fournir sa propre carte au format GPKG ou `.omap` avec les couches `veg_406`, `veg_408`, `veg_410`
2. La déclarer dans `config.yaml` :

   ```yaml
   terrains:
     ma_foret:
       qa_reference: data/ma_carte_reference.gpkg
   ```

3. Le recall par classe et la couverture hull s'affichent en fin de run et sont sauvés dans `output/run_metadata.json`

---

## Utilisation hors de France

Le pipeline a tourné sur des données estoniennes (LiDAR COPC + OSM). Adaptations nécessaires :

- **CRS** : changer `crs` dans `config.yaml` (ex. `EPSG:3301` pour l'Estonie)
- **Géoréférencement** : créer `assets/georef_{terrain}.xml` (voir les exemples dans `assets/`)
- **Mappings** : adapter `scripts/mappings/bdtopo_isom.yaml` si la donnée anthropique ne vient pas de la BD TOPO
- **BD TOPO** : aucun équivalent direct hors France — utiliser OSM via l'option `osm_landuse` dans `config.yaml`

Voir [docs/portabilite.md](docs/portabilite.md) pour un guide détaillé.

---

## Ce que le projet a établi

Onze pistes d'amélioration ont été testées et mesurées : ajustement du seuil de détection, filtre de surface minimale, sigma gaussien, résolution de grille (1 m vs 2 m), stratégie de normalisation (fixe vs p95_local), intensité LiDAR comme signal secondaire, masque canopée, suppression de trous (deux approches), chirurgie des isthmes, sweep des seuils inter-classes. La plupart ont été réfutées par la mesure sur corpus multi-terrain.

Documentées dans [docs/bilan_v0.md](docs/bilan_v0.md) pour éviter à d'autres de refaire le chemin.

---

## Statut du projet

Publié en l'état comme travail posé — preuve de concept fonctionnelle sur forêt tempérée française.

Le pipeline fonctionne et produit des sorties utilisables, dans les limites documentées ci-dessus. Les issues GitHub seront lues mais les réponses ne sont pas garanties. Les pull requests documentant de nouveaux terrains testés ou améliorant la portabilité sont les bienvenues.

---

## Architecture

```
main.py                      orchestrateur principal (7 étapes)
config.yaml                  tous les paramètres — seuils, profils, endpoints

src/
  vegetation.py              CO Generalization Engine (9 étapes enchaînées)
  omap_writer.py             génération fichiers .omap (XML OOM)
  qa.py                      métriques QA + snapshot config
  guards.py                  détection dérives de config entre runs
  metrics.py                 calcul densités HAG (ratio, NRD)

scripts/
  fetch.py                   extraction BD TOPO depuis GPKG département
  process_hag.py             normalisation + classification raster HAG
  mask_vegetation.py         masque anthropique sur la végétation
  generate_bdtopo.py         BD TOPO → couches .omap
  generate_relief.py         DXF Karttapullautin → courbes de niveau .omap
  run_terrain.py             pipeline PDAL standalone
  measure_corpus.py          comparaison pipeline vs référence FFCO
  mappings/                  tables de correspondance ISOM (BD TOPO, KP)

scripts/diag/                scripts de calibration (historique des expérimentations)
assets/                      gabarit ISOM 2017-2, géoréférencements, CRT KP
docs/                        portabilité, bilan v0, règles IOF
```

---

## Licence et crédits

**GNU Affero General Public License v3.0** — voir [LICENSE](LICENSE).

Utilisation libre, modification libre. Tout dérivé ou service réseau doit être publié sous AGPL v3 avec le code source.

Assets tiers :
- Gabarit ISOM 2017-2 extrait d'[OpenOrienteering Mapper](https://www.openorienteering.org/) (GPL-3.0)
- Table CRT extraite de [Blaze / Trailblaze Software](https://github.com/Trailblaze-Software/Blaze) (Apache-2.0)
- [Karttapullautin](https://github.com/karttapullautin/karttapullautin) — non inclus, à télécharger séparément
