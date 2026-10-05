# Pipeline végétation KP — architecture et paramètres

> Ce document décrit la chaîne `step_vegetation_kp` introduite par PLAN 3 (2026-10).
> Source : PNG de rendu Karttapullautin → couches vectorielles 406/408/410 dans le `.omap`.

---

## 1. Position dans le pipeline global

```
relief         → out_kp_{terrain}/*.dxf  +  *_vege*.png
vegetation_kp  → output/vegetation_kp.gpkg  (couches veg_406 / veg_408 / veg_410)
vegetation     → output/vegetation.gpkg      (branche HAG — fallback QA uniquement)
mask           → output/vegetation_masked.gpkg
assemble       → output/{terrain}.omap       (injections : couches KP + relief + BD TOPO)
```

`vegetation_kp` dépend des PNG produits par `step_relief`. Si `out_kp_{terrain}/` est absent,
l'étape est ignorée silencieusement. Si le répertoire existe mais ne contient aucun `*_vege*.png`,
une `RuntimeError` est levée (état anormal — vérifier `vege_bitmode` dans `pullauta.ini`).

---

## 2. Chaîne de traitement

```
*_vege*.png (N dalles)
  ↓  kp_raster.mosaic()
source_kp_classified.tif   (mosaïque reclassifiée : 0=fond 85=406 170=408 255=410)
  ↓  rasterio.features.shapes()  — polygonisation par valeur DN
polygones RAW (un polygone par région connexe)
  ↓  shapely.coverage_is_valid()  — VALIDATION avant simplification
  ↓  shapely.coverage_simplify(tolerance=coverage_simplify_m)
polygones simplifiés (topologie préservée, couverture sans recouvrement)
  ↓  clip à la bbox du terrain
  ↓  coverage_is_valid() après clip — alerte si arêtes invalides
vegetation_kp.gpkg  (couches : veg_406 / veg_408 / veg_410)
```

**Propriété V1 (round-trip)** : avant simplification, la rasterisation des polygones RAW
reproduit le raster source à 0 pixel près (vérifiée par `test_roundtrip_lossless_before_simplify`).

**Propriété V6 (couverture valide)** : `coverage_is_valid` est appelé AVANT `coverage_simplify`.
Si la couverture est invalide (recouvrement entre polygones), une `ValueError` est levée — jamais
un appel silencieux sur une entrée invalide.

---

## 3. Paramètres de configuration

Tous dans `config.yaml`, section `karttapullautin`:

```yaml
karttapullautin:
  rendering:
    lightgreentone: 160          # ton vert clair (0–255) — doit correspondre au pullauta.ini
    medianboxsize2: 16           # paramètre KP utilisé pour le rendu
    template_opacity_pct: 50     # opacité du fond PNG dans le .omap (si keep_template: true)

  vectorization:
    shade_to_isom:               # table teinte KP → code ISOM (gelée pour KP v2.12.1)
      2: 0                       #   teinte 2 → ignorée (fond blanc)
      3: 406
      4: 406
      5: 408
      6: 408
      7: 410
      8: 410
    coverage_simplify_m: 2.0    # tolérance Visvalingam-Whyatt avec préservation topologique
    keep_template: true          # inclure le fond PNG KP comme template dans le .omap
```

### Paramètre critique : `shade_to_isom`

La table `shade_to_isom` est **gelée** pour KP v2.12.1, `lightgreentone=160`, 11 niveaux de vert
(dont 4 à `99` dans `greenshades`). Un changement de `lightgreentone` ou de `greenshades` invalide
cette table — le garde-fou `check_config_snapshot` signale tout écart.

La valeur `0` pour la teinte 2 est intentionnelle (fond blanc ignoré) : elle ne déclenche pas de
fausse alerte de dérive de config grâce au test `test_shade_to_isom_zero_no_false_drift`.

### Paramètre `coverage_simplify_m`

Validé à **2,0 m** sur le terrain Grimbosq (bras C, V3). Cette valeur préserve les contours
utiles tout en éliminant les artefacts de pixellisation à 1 m de résolution. Modifier ce
paramètre invalide les résultats reproductibles — le snapshot de config le détecte.

### Paramètre `keep_template`

- `true` : le fond PNG végétation (mosaïque des `*_vege.png`) est inclus dans le `.omap`
  comme template à l'opacité `template_opacity_pct`. Utile pour la phase d'édition.
- `false` : seules les couches vectorielles 406/408/410 sont dans le `.omap`, sans fond PNG.

---

## 4. Source des couches 406/408/410

Les couches injectées dans le `.omap` sont issues du **rendu KP** (Karttapullautin), pas d'une
classification LiDAR indépendante. Conséquences importantes :

- La qualité dépend de la calibration KP (`medianboxsize2`, `lightgreentone`, seuils internes).
- Les aplats correspondent aux zones rendues comme « végétation verte » par KP, qui peut
  inclure ou exclure des zones selon ses propres règles (HAG, densité, filtres morphologiques).
- La distinction 406 / 408 / 410 est portée par l'intensité du vert dans le rendu (table
  `shade_to_isom`) — elle n'est pas une classification LiDAR à part entière.

**Ce n'est pas une alternative à une classification LiDAR** : c'est une vectorisation du rendu
KP, qui encode les choix cartographiques de Karttapullautin.

---

## 5. Limites connues sur Grimbosq

Mesures issues de V4 (validation OOM, 2026-10-04) :

| Classe | Polygones livrables (sans clip hull) |
|--------|--------------------------------------|
| 406    | 1 340 |
| 408    |   409 |
| 410    |    18 |

- Le 410 est très fragmenté (18 polygones) — le rendu KP sur Grimbosq produit peu de végétation
  dense correspondant à l'aplat 410.
- Le 408 est plausible géographiquement mais non évalué contre le référentiel FFCO sur cette
  métrique (l'évaluation exp2 portait sur les frontières raster, pas sur les polygones finaux).
- La résolution du raster source est 1 m/px — les polygones simplifiés à 2 m peuvent présenter
  des escaliers résiduels sur les contours courbes.

---

## 6. Garde-fous et reproductibilité

| Garde-fou | Déclencheur | Comportement |
|-----------|-------------|--------------|
| `check_config_snapshot` | Écart dans `shade_to_isom`, `coverage_simplify_m`, `keep_template`, `lightgreentone`, `medianboxsize2` | Avertissement non bloquant au démarrage du run |
| `coverage_is_valid` avant simplify | Recouvrement entre polygones après polygonisation | `ValueError` bloquante |
| `coverage_is_valid` après clip | Arêtes invalides après clip bbox | `ValueError` bloquante |
| `out_kp/` présent sans PNG | `vege_bitmode` désactivé ou `step_relief` non lancé | `RuntimeError` bloquante dans `step_vegetation_kp` |
| `vegetation_kp.gpkg` absent avec `out_kp/` présent | `step_vegetation_kp` non lancé après KP | `RuntimeError` bloquante dans `step_assemble` |
| `ctrl_omap.count_objects` | Chaque run QA | `declared != actual` → warning dans les logs |

---

## 7. Fichiers concernés

| Fichier | Rôle |
|---------|------|
| `main.py` : `step_vegetation_kp` | Orchestration de la chaîne |
| `main.py` : `_build_img_templates` | Gestion `keep_template` |
| `main.py` : `step_assemble` | Injection des couches + contrôle topologique |
| `main.py` : `step_qa` | QA KP en priorité, HAG en fallback, `ctrl_omap` |
| `src/kp_raster.py` | Mosaïque, décodage palette, `build_class_raster`, `ISOM_TO_DN` |
| `src/guards.py` | Comparaison snapshot — paramètres KP vectorisation |
| `src/qa.py` | `write_config_snapshot` avec `extra={}` |
| `config.yaml` : section `karttapullautin.vectorization` | Paramètres utilisateur |
| `tests/test_vegetation_kp.py` | Round-trip, coverage_is_valid, overlaps, keep_template |
| `tests/test_config_snapshot.py` | Dérive shade_to_isom, coverage_simplify_m, keep_template |
