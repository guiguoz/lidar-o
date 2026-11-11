# Mode supervised_e — Documentation

**Version :** 1.0 — 2026-11-11
**Statut :** expérimental — pas d'équivalence exacte avec OCAD

---

## 1. Principe

Le mode `supervised_e` prédit les catégories de végétation directement depuis
les fichiers LAZ bruts, sans référence à une carte OCAD à l'inférence.

**Pipeline complet :**

```
LAZ bruts
  → DTM (min-Z sol + remplissage voisin)
  → 9 bins HAG (Hauteur Au-dessus du Sol, 0–10 m)
  → Strates T dérivées (4 bandes) + strates E (9 bins + ordres de retour)
  → 63 descripteurs (30 T + 33 E)
  → RandomForest (RF_leaf5, 300 arbres, depth=20, balanced)
  → Raster prédiction uint8 (2 bandes : classes + support)
  → Vectorisation → GPKG
  → Assemblage .omap
```

**Sorties produites** :

| Fichier | Description |
|---|---|
| `output/supervised_e_prediction.tif` | Raster prédiction 2 bandes (classes 0–4/255, support 0/1) |
| `output/vegetation_supervised_e_faithful.gpkg` | Polygones veg_401/406/408/410 |
| `output/vegetation_supervised_e_faithful.json` | Métadonnées durables (mode, CRS, n_polygones) |
| `output/supervised_e_coverage.tif` | Masque couverture LiDAR (1=couvert, 0=inconnu) |
| `{terrain}.omap` | Carte assemblée (via step_assemble) |

---

## 2. Dépendances

**Interpréteur Python géospatial :**

```
C:/Users/glemi/miniconda3/python.exe
```

Le Python système (3.14) ne possède pas les bibliothèques géospatiales.

**Bibliothèques requises** (Miniconda) :

```
numpy, scikit-learn, rasterio, shapely, geopandas, scipy, laspy (ou pdal)
```

**Vérification :**

```bash
C:/Users/glemi/miniconda3/python.exe -c "
import numpy, sklearn, rasterio, shapely, geopandas
print('OK', sklearn.__version__, rasterio.__version__)
"
```

---

## 3. Modèle final — localisation et chargement

**Fichier :** `experiments/loto_v1/final_model/model_e_final.pkl` (786 Mo)

Le `.pkl` **n'est pas versionné dans git** (trop volumineux).
Il doit être présent localement sur le disque. Un modèle uniquement sur `E:`
n'est pas une sauvegarde distante — aucun stockage cloud n'est configuré.

**Identification par SHA-256 :**

```
48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5
```

Vérification :

```python
import hashlib, pathlib
sha = hashlib.sha256(
    pathlib.Path("experiments/loto_v1/final_model/model_e_final.pkl").read_bytes()
).hexdigest()
assert sha == "48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5"
```

**Contenu du pkl** :

```python
{"clf": RandomForestClassifier, "imputer": SimpleImputer, "n_features": 63}
```

**Chargement dans le pipeline** (`src/supervised_e.py`) :

```python
from src.supervised_e import load_model
payload = load_model()           # chemin par défaut : DEFAULT_MODEL_PATH
# ou
payload = load_model(model_path) # chemin explicite
```

La fonction vérifie la SHA-256 via `final_model/manifeste.json` avant de charger.

**Spécification figée** : `experiments/loto_v1/final_model/method_e_spec.yaml`

**Pour réentraîner** (si modèle perdu) :

```bash
cd e:/Vikazim/Ovector
C:/Users/glemi/miniconda3/python.exe experiments/loto_v1/train_final_e.py
```

---

## 4. Configuration et lancement

**Activer le mode supervised_e pour un terrain** (`config.yaml`) :

```yaml
terrains:
  bois_dupont:
    bbox: [425000, 6922000, 426000, 6923000]
    vegetation_source: supervised_e
```

**Mode d'export** (optionnel, global) :

```yaml
vegetation_export_mode: "faithful"    # défaut — 0 pixel perdu
# ou
vegetation_export_mode: "generalized" # archive — filtre composantes < 16 m²
```

**Lancement pipeline complet** :

```bash
cd e:/Vikazim/Ovector
C:/Users/glemi/miniconda3/python.exe main.py run bois_dupont \
  --tiles-dir /chemin/vers/laz/ \
  --from-step supervised_e
```

**Lancement assemblage seul** (raster existant, sans relancer LiDAR/inference) :

```bash
C:/Users/glemi/miniconda3/python.exe main.py run bois_dupont \
  --from-step assemble --skip-pdal
```

---

## 5. Mode faithful vs generalized

| | faithful (défaut) | generalized |
|---|---|---|
| Filtre composantes | aucun | < 16 m² supprimées (1 pixel 2×2 m) |
| Roundtrip raster→vecteur→raster | **0 pixel perdu** | ≤ 1,41% de perte |
| Nombre de polygones (Bois Dupont) | 4 288 | 2 674 |
| Taille .omap (Bois Dupont) | ~1,7 Mo | ~1,5 Mo |
| Nom fichier GPKG | `…_faithful.gpkg` | `…_generalized.gpkg` |
| Usage | production | archive v1 |

Les deux modes écrivent dans des fichiers distincts — aucun écrasement silencieux.

---

## 6. Sorties détaillées — Bois Dupont (500×500 px, 2 m/px)

**Surfaces par classe** (mode faithful) :

| Classe | Pixels | Surface | Statut |
|---|---|---|---|
| 0 — découvert (401) | 159 624 | 63,85 ha | vectorisé |
| 1 — blanc (fond) | 29 055 | 11,62 ha | fond implicite, pas de polygone |
| 2 — veg\_406 | 28 804 | 11,52 ha | vectorisé |
| 3 — veg\_408 | 15 121 | 6,05 ha | vectorisé |
| 4 — veg\_410 | 17 340 | 6,94 ha | vectorisé |
| — inconnus (support=0) | 56 | 0,022 ha | ni prédits, ni courables |
| **Total vectorisé** | **220 889** | **88,36 ha** | |

**Distinction blanc vs inconnu :**

- Classe 1 (blanc) = prédiction « végétation rase/pâture » → fond implicite du .omap, pas de polygone
- Support=0 (inconnus) = aucune donnée LiDAR → absent du .omap, non courable
- Les deux apparaissent en blanc à l'écran mais ont des origines différentes

**Masque de couverture** : `output/supervised_e_coverage.tif`
Bande 1 : `1` = pixel évalué (couvert LiDAR), `0` = hors couverture

---

## 7. Résultats LOTO E (RF_leaf5, 4-fold)

**Entraînement** : 1 134 385 pixels × 63 features, 4 terrains LOTO

| Fold | IoU macro veg | IoU veg présence | Précision veg | Rappel veg |
|---|---|---|---|---|
| Bois Dupont | 0,536 | 0,862 | 0,908 | 0,945 |
| Caen | 0,527 | 0,792 | 0,819 | 0,960 |
| Montmirel | 0,464 | 0,748 | 0,837 | 0,876 |
| Sainte-Anne | 0,405 | 0,767 | 0,797 | 0,953 |

**IoU par classe (meilleur fold = Bois Dupont)** :

| Classe | IoU | Précision | Rappel |
|---|---|---|---|
| découvert | 0,969 | 0,985 | 0,983 |
| blanc | 0,772 | 0,872 | 0,870 |
| veg\_406 | 0,558 | 0,637 | 0,818 |
| veg\_408 | 0,332 | 0,593 | 0,431 |
| veg\_410 | 0,717 | 0,889 | 0,787 |

**Limites connues :**

- veg\_408 est la classe la plus difficile (IoU 0,22–0,45 selon le terrain)
- Les performances reportées ci-dessus sont des scores LOTO (validation externe)
- Le modèle final utilise les 4 terrains en entraînement → les scores LOTO
  surestiment légèrement la performance en déploiement hors-terrains
- Aucune équivalence exacte avec les cartes OCAD de référence
- Résolution 2 m/px : les détails fins < 2 m sont perdus

---

## 8. Vérification roundtrip

**Méthode** : raster source → `vectorize_prediction` → `save_vegetation_gpkg`
→ `gpd.read_file` → `Layer` → `write_omap` → parse XML OOM → `rasterize` → comparaison

**Résultat Bois Dupont (mode faithful)** :

```
Pixels support    : 249 944
Pixels identiques : 249 944  (100.0000%)
Pixels modifiés   :       0  (0.0000%)
```

**Fichier de vérification** : `verify_raster_omap.py`

Le roundtrip est garanti par la propriété de `rasterio.features.shapes()` : les
sommets sont aux bords de pixels, et `rasterize()` utilise les centres — les
pixels sont donc strictement à l'intérieur de leurs polygones respectifs, sans
aucun filtrage.

---

## 9. Tests

**Lancement** :

```bash
cd e:/Vikazim/Ovector
C:/Users/glemi/miniconda3/python.exe -m pytest \
  experiments/loto_v1/tests/test_supervised_e_integration.py -v
```

**Couverture** : 47 tests, sections §A–§K

| Section | Objet |
|---|---|
| §A | Ordre et noms des 63 descripteurs (T puis E) |
| §B | Cohérence entraînement/inférence (imputer appris sur train) |
| §C | Invalidation du cache strates ext |
| §D | Déduplication géographique SA↔Caen |
| §E | Cellules inconnues et support |
| §F | Géoréférencement et centres des pixels |
| §G | Sauvegarde/rechargement du modèle |
| §H | Autonomie sans référence de carte à l'inférence |
| §I | Sélection du mode (pipeline_mode.py) |
| §J | Non-régression des modes kp et hag |
| §K | Vectorisation : pixel unique, all classes, blanc, inconnus, overlaps, roundtrip |

**Résultat attendu** : `47 passed` en < 5 s (aucun LAZ ni modèle requis).

---

## 10. Architecture du code

```
src/supervised_e.py           — pipeline principal + vectorisation + export
src/pipeline_mode.py          — résolution du mode (kp/hag/supervised_e)
main.py                       — step_supervised_e + step_assemble (veg_mode)

experiments/loto_v1/
  descriptors_ext.py          — 33 features étendues (bins E + ordres retour)
  loto_pipeline_e.py          — entraînement LOTO branche E
  train_final_e.py            — entraînement modèle final (4 terrains)
  final_model/
    manifeste.json            — SHA-256, config, stats d'entraînement
    method_e_spec.yaml        — spécification figée RF_leaf5
    model_e_final.pkl         — 786 Mo, non versionné (voir §3)
  tests/
    test_supervised_e_integration.py  — 47 tests §A–§K

experiments/bois_dupont/supervised_v1/
  descriptors.py              — 30 features strates T (importé par supervised_e)
```
