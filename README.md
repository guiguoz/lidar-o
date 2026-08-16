# co-vector-fr

Génération d'une carte de base ISOM à partir du LiDAR HD IGN (France), sortie en `.omap` ouvrable dans OpenOrienteering Mapper ou OCAD.

<!-- Image représentative à l'échelle — copier un extrait de la carte générée dans docs/images/ -->
<!-- ![Extrait Grimbosq](docs/images/extrait_grimbosq.png) -->

---

## Comment l'essayer

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

- **Karttapullautin** (optionnel, pour le relief) — [github.com/karttapullautin](https://github.com/karttapullautin/karttapullautin) — lancer manuellement sur les dalles LiDAR, sortie dans `out_kp/`

### Données d'entrée (France)

| Donnée | Source | Emplacement |
|--------|--------|-------------|
| LiDAR HD (dalles COPC, ~500 MB/dalle) | [IGN Géoplateforme](https://geoservices.ign.fr/lidarhd) | `LIDAR/` ou `--tiles-dir DIR` |
| BD TOPO (GPKG département) | [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo) | `data/bdtopo/` |

**Spécifique France :** le LiDAR provient de la Géoplateforme IGN HD (COPC), la donnée anthropique de la BD TOPO v3. Hors France, voir [docs/portabilite.md](docs/portabilite.md).

Télécharger ~1–3 dalles LiDAR sur votre terrain. Compter 10–30 min de traitement selon la machine (PDAL + rasterisation + vectorisation). Un premier test sur 1 dalle (1×1 km) est suffisant.

### Lancer le pipeline

```bash
# Déclarer le terrain dans config.yaml (bbox EPSG:2154, CRS, département)
python main.py grimbosq --tiles-dir LIDAR/ --skip-pdal
```

Options :

| Option | Usage |
|--------|-------|
| `--skip-pdal` | Saute PDAL si `density_hag_classified.tif` existe déjà |
| `--tiles-dir DIR` | Répertoire des dalles `.copc.laz` |
| `--from-step STEP` | Reprend à : `fetch`, `pdal`, `process_hag`, `vegetation`, `mask`, `assemble`, `qa` |
| `--force` | Ignore les vérifications de fraîcheur |

Sortie : `output/{terrain}.omap`

---

## Ce que l'outil capture

> Mesuré sur **un seul terrain** (forêt de Grimbosq, Calvados, France), contre une carte FFCO
> de référence, sur emprise commune (hull 324 ha). Ces valeurs ne sont pas garanties ailleurs.

| Classe | Détecté | Dans la bonne classe |
|--------|---------|----------------------|
| 406 sous-bois léger | 35 % | 28 % |
| 408 marche | 61 % | 26 % |
| 410 progression difficile | 82 % | 48 % |

*"Détecté"* = fraction de la surface FFCO couverte par n'importe quelle classe du pipeline — ce que le cartographe n'a pas à dessiner.  
*"Dans la bonne classe"* = fraction dans la bonne classe exacte — ce qu'il n'a pas à retoucher.  
Le symbole se corrige en deux clics dans OCAD/OOM ; un polygone absent se dessine à la main.

*Ces métriques ont été mesurées contre une carte de référence non redistribuable — les chiffres ne sont donc pas reproductibles en l'état depuis ce dépôt.*

---

## Domaine de validité

Le pipeline a été testé sur 5 terrains. Le signal HAG[0.3–3 m] sépare bien les végétations denses ; il est insuffisant pour le sous-bois léger praticable.

| Terrain | Type | Résultat 406 | Cause |
|---------|------|-------------|-------|
| Grimbosq (Normandie) | Hêtraie mature | Partiel (35 %) | Signal léger indiscernable du blanc |
| Airelles (Pyrénées) | Lande résineux altitude | Hors domaine | Signal HAG identique entre classes |
| Kilemäed (Estonie) | Lande/forêt mixte | Hors domaine | Désaccord sémantique ouvert/couvert |
| Kuti (Estonie) | Épicéas + Vaccinium | Hors domaine | Signal uniforme dense |
| (5e terrain, test) | Forêt tempérée | 408/410 détecté | Confirme le domaine dense |

**406 léger hors domaine, y compris sur Grimbosq.** AUC Mann-Whitney = 0.487 : la densité HAG[0.3–3 m] dans les zones 406 manquées est statistiquement indiscernable du terrain courable. Baisser le seuil crée autant de faux positifs qu'il ne récupère de vrais positifs.

**408/410 dans le domaine** sur les forêts à structuration verticale claire (forêt tempérée dense, 61 %/82 % de détection). Testé et hors domaine : landes d'altitude, landes-marais, forêts à sous-bois uniforme.

---

## QA et carte de référence

Le pipeline tourne sans référence (métriques QA dégradées à la seule évaluation de la distribution de classes). Pour activer la comparaison quantitative :

1. Fournir sa propre carte au format GPKG ou `.omap` avec les couches `veg_406`, `veg_408`, `veg_410`
2. La déclarer dans `config.yaml` :

   ```yaml
   terrains:
     grimbosq:
       qa_reference: data/ma_carte_reference.gpkg
   ```

3. Les métriques (recall par classe, couverture hull) s'affichent en fin de run et sont sauvées dans `output/run_metadata.json`

---

## Utilisation hors de France

Le pipeline a tourné sur des données estoniennes (COPC LiDAR + OSM). Adaptations nécessaires :

- **CRS** : changer `crs` dans `config.yaml` (ex. `EPSG:3301` pour l'Estonie)
- **Géoréférencement** : créer `assets/georef_{terrain}.xml` (voir les exemples dans `assets/`)
- **Mappings** : adapter `scripts/mappings/bdtopo_isom.yaml` si la donnée anthropique ne vient pas de la BD TOPO
- **BD TOPO** : aucun équivalent direct hors France — utiliser OSM via l'option `osm_landuse` dans `config.yaml`

Voir [docs/portabilite.md](docs/portabilite.md) pour un guide détaillé.

---

## Ce que le projet a établi

Onze pistes d'amélioration ont été testées et mesurées (bandes d'intensité, NDVI-like HAG, variation spatiale des seuils, apprentissage supervisé, segmentation objet…). La plupart ont été réfutées par la mesure sur corpus multi-terrain.

Documentées dans [docs/bilan_v0.md](docs/bilan_v0.md) pour éviter à d'autres de refaire le chemin.

---

## Statut du projet

Publié en l'état comme travail posé — preuve de concept fonctionnelle sur forêt tempérée française.

Le pipeline fonctionne et produit des sorties utilisables, avec les limites documentées ci-dessus. Les issues GitHub seront lues mais les réponses ne sont pas garanties. Les pull requests documentant de nouveaux terrains testés ou améliorant la portabilité sont bienvenues.

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
  metrics.py                 densités HAG (ratio, NRD)

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
