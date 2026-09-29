# Démarrage rapide — Lidar'O

> Parcours testé sur Grimbosq (Calvados, 2×3 km, 6 dalles LiDAR HD, BD TOPO D014).  
> Pour comprendre ce que le pipeline produit et ne produit pas, voir le [README](../README.fr.md).

---

## Données requises

| Donnée | Format | Source | Où trouver |
|---|---|---|---|
| Dalles LiDAR HD | `*.copc.laz` | IGN | [geoservices.ign.fr](https://geoservices.ign.fr/lidarhd) — Téléchargement par dalle 1 km² |
| BD TOPO | `.gpkg` (département) | IGN | [geoservices.ign.fr](https://geoservices.ign.fr/bdtopo) — Archive GPKG Lambert-93 |
| Karttapullautin | `pullauta.exe` | GitHub | Téléchargé automatiquement par `setup` (v2.12.1) |

**Emprise recommandée :** 2×3 km minimum (6 dalles). Moins de dalles = contours KP dégradés aux bords.

---

## Voie CLI

### 1. Créer le terrain

```
python main.py init <nom_terrain> --lat <lat> --lon <lon>
```

Calcule l'emprise autour du point central, déduit le CRS, génère le géoréférencement.  
Exemple : `python main.py init foret --lat 49.043 --lon -0.421`

### 2. Configurer les chemins et valider

```
python main.py setup <nom_terrain>
```

Dialogue interactif : répertoire LiDAR, fichier BD TOPO, binaire KP.  
À la fin, affiche un contrôle complet :

```
── Contrôle final ──────────────────────────────────────────────
Emprise   ✓ 448000–450001 × 6886000–6889001 · 2×3 km · Lambert-93
LiDAR HD  ✓ 6/6 dalles · dalles jointives
BD TOPO   ✓ BDT_3-5_GPKG…D014… · couches validées · couverture OK
KP        ✓ v2.12.1
────────────────────────────────────────
PROJET PRÊT
```

**KP non installé :** `setup` propose le téléchargement automatique depuis GitHub Releases (~15 MB). Il suffit d'appuyer sur Entrée.

### 3. Lancer le pipeline

```
python main.py run <nom_terrain>
```

Enchaîne les étapes dans l'ordre :

| Étape | Ce qui se passe | Durée indicative |
|---|---|---|
| `fetch` | Télécharge la BD TOPO si département connu | 10–30 s |
| `pdal` | Calcul densité LiDAR → rasters HAG | ~20 min / 6 dalles |
| `process_hag` | Classification → raster végétation | 1–2 min |
| `relief` | KP batch → DXF courbes + végétation KP | ~40 min / 6 dalles |
| `vegetation` | Polygonisation + généralisation → `vegetation.gpkg` | 1–2 min |
| `mask` | Masquage BD TOPO + OSM → `vegetation_masked.gpkg` | 30 s |
| `assemble` | Assemblage → `output/<terrain>.omap` | 1–2 min |
| `qa` | Contrôle qualité végétation (optionnel) | 10 s |

**Durée totale sur 6 dalles (2×3 km) : environ 60–70 min** (dont 40 pour KP).

Pour reprendre après une étape déjà faite :

```
python main.py run <terrain> --skip-pdal
python main.py run <terrain> --from-step vegetation --force
```

---

## Voie GUI

```
python main.py gui
```

Ouvre une fenêtre tkinter. Workflow :

1. **Terrain** — saisir le nom (doit exister dans `config.yaml`)
2. **Charger LiDAR…** — sélectionner le répertoire contenant les `*.copc.laz`
3. **Charger BD TOPO…** — sélectionner le `.gpkg` département
4. **Générer** — lance le pipeline ; progression dans le panneau de log

La GUI ne remplace pas `setup` pour la première configuration (elle lit `config.yaml` existant).

---

## Ce qui peut coincer

**Python géospatial**  
Utiliser `C:/Users/<user>/miniconda3/python.exe`, pas le Python système.  
Le Python système (3.14) ne possède pas geopandas/pyogrio/pyproj.

**BD TOPO — couches manquantes**  
Le pipeline utilise uniquement 4 couches : `troncon_de_route`, `batiment`, `surface_hydrographique`, `troncon_hydrographique`. S'assurer de télécharger l'archive GPKG complète (pas l'export par thème).

**Emprise BD TOPO trop petite**  
Le fichier département doit couvrir le terrain. `setup` le vérifie automatiquement (`Couverture spatiale OK`).

**KP — version incorrecte**  
Le pipeline est épinglé sur v2.12.1. Une autre version peut produire des DXF incompatibles. `setup` vérifie la version au démarrage.

**Tuiles non jointives**  
Si des dalles sont manquantes, `check` signale `✗ dalles non jointives`. Télécharger les dalles manquantes sur geoservices.ign.fr.

**Réseau**  
`fetch` (BD TOPO) et le téléchargement KP nécessitent internet. Si hors ligne, pointer `kp_binary` vers un binaire déjà téléchargé et fournir le `.gpkg` manuellement.

---

## Sortie produite

Fichier : `output/<terrain>.omap` — ouvert directement dans OpenOrienteering Mapper.

Contenu assemblé :

- Courbes de niveau (101/102/103) et dépression (109/111)
- Routes et chemins (502–505)
- Bâtiments (521), zones interdites (520)
- Eau (301/302/305)
- Terrain découvert (401/403)
- Fond KP végétation géoréférencé (template raster)
- Couches végétation vectorielles 406/408/410 — estimations automatiques, **à vérifier et corriger au terrain**

Pour ce que le pipeline ne produit pas (falaises, point features, sous-bois léger), voir [README](../README.fr.md#ce-que-lidarо-ne-produit-pas).

---

## Reproduire exactement le run Grimbosq

```bash
# Données de référence (testées)
# LiDAR : 6 dalles 0448-0449 × 6887-6889, acquisition feuilles tombées
# BD TOPO : BDT_3-5_GPKG_LAMB93_D014-ED2026-06-15.gpkg
# KP : v2.12.1, medianboxsize2=16, lightgreentone=160

python main.py setup grimbosq   # valider la configuration
python main.py run grimbosq     # run complet
```

Résultat attendu : `output/grimbosq.omap`, 3 300–3 400 objets, géoréf. (449000, 6888000), échelle 1:10 000.
