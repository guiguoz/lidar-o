# État de l'existant — Phase 0

> **Document à compléter par l'humain** après exécution de `scripts/phase0_recon.py`.
> Une fois rempli, ce document fige les décisions de la Phase 0 et déverrouille la Phase 1.
>
> ```
> python scripts/phase0_recon.py all <dossier_sortie_kp> <xmin> <ymin> <xmax> <ymax>
> ```

---

## Statut global

- [x] Phase 0 en cours
- [x] Phase 0 validée — Phase 1 déverrouillée (2026-06-24)

---

## 1. Karttapullautin

### Version

Version installée : **v2.12.1** (binaire `pullauta.exe`, confirmé 2026-06-24)

Action : ~~reporter dans `config.yaml → karttapullautin.version`~~ **FAIT** — épingler aussi dans `Dockerfile → KP_VERSION`.

### Sorties DXF et noms de calques

> Résultat de `inspect_kp_outputs()` — KP v2.12.1 sur dalle IGN LHD_FXX_0449_6889 :

| Fichier DXF | Calques présents |
|---|---|
| `out2.dxf` | `contour`, `contour_index`, `contour_intermed`, `depression`, `depression_intermed` |
| `c2g.dxf` | `cliff2` |
| `c3g.dxf` | `cliff3` |
| `dotknolls.dxf` | `dotknoll`, `udepression`, `uglydotknoll`, `uglyudepression` |
| `formlines.dxf` | `formline` |
| `out.dxf` | `cont` (courbes brutes, avant lissage) |
| `contours03.dxf` | `cont` (courbes 0.3 m — très lourd, 9.5 MB) |
| `detected.dxf` | `1010` (usage inconnu) |

**CRT principal → `out2.dxf`** (courbes lissées + dépressions séparées).

Action : ~~reporter dans `config.yaml → karttapullautin.expected_dxf_layers`~~ **FAIT**.

### Raster de densité végétation

> Le raster de densité de KP est-il un float continu réutilisable, ou seulement un PNG rendu ?

- [ ] **KP expose un raster de densité float continu** → `config.vegetation.source: "kp"` (défaut)
- [x] **KP ne produit que du PNG** → option `"kp"` continue **éliminée**

KP produit uniquement des PNG géoréférencés (`.pgw`) : `undergrowth.png`, `undergrowth_bit.png`, `vegetation.png`. Aucun raster float.

**Conséquence Phase 1 spike** : comparer `undergrowth.png` polygonisé vs PDAL vs MNH sur terrain connu.

Détail des rasters non-PNG trouvés :
```
Aucun — KP v2.12.1 ne produit pas de densité float réutilisable
```

### Audit PNG KP (`undergrowth.png` / `vegetation.png`)

> Résultat de `_audit_kp_png()` — hypothèses à confirmer (source : Orienteering BC, version Perl historique) :

| Fichier | Taille | Géoréf | bit-depth | N valeurs distinctes | Remarque |
|---|---|---|---|---|---|
| `undergrowth.png` | 11 kB | oui (`.pgw`) | ? (GDAL absent en local) | ? | Très petit → probablement quantifié |
| `undergrowth_bit.png` | 36 kB | non | ? | ? | Masque binaire ? |
| `vegetation.png` | 86 kB | oui (`.pgw`) | ? | ? | Plus riche que undergrowth |

**Audit GDAL impossible en local** (`osgeo` absent hors Docker). À compléter en Phase 1 spike dans le container.

Indice taille : `undergrowth.png` = 11 kB pour ~1 km² → fortement compressé/quantifié. Seuillabilité à confirmer.

- [x] **Fichiers attendus présents** : `undergrowth.png`, `vegetation.png` (+ version `_bit`)
- [ ] PNG seuillable proprement → **à vérifier au spike dans Docker**

---

## 2. BD TOPO / WFS Géoplateforme

### Typenames WFS confirmés

> Résultat de `test_wfs_capabilities()` :

| Rôle | Typename WFS réel |
|---|---|
| Routes | `BDTOPO_V3:troncon_de_route` |
| Bâtiments | `BDTOPO_V3:batiment` |
| Voies ferrées | `BDTOPO_V3:troncon_de_voie_ferree` |
| Lignes électriques | `BDTOPO_V3:ligne_electrique` |
| Cours d'eau linéaires | `BDTOPO_V3:troncon_hydrographique` |
| Surfaces en eau | `BDTOPO_V3:surface_hydrographique` |
| Zones de végétation | `BDTOPO_V3:zone_de_vegetation` |
| Haies | `BDTOPO_V3:haie` |

Confirmé le 2026-06-23 via `test_wfs_capabilities()` sur `data.geopf.fr/wfs` (714 couches totales).

Action : ~~remplacer les `PLACEHOLDER_*` dans `config.yaml → bd_topo.layers` et `symbols_isom.yaml → bd_topo_mapping`~~ **FAIT**.

### Index LIDAR HD

- Dalle trouvée sur emprise de test : **16 dalles** sur bbox `406000,6877000,408000,6879000` (Forêt de Grimbosq, Calvados)
- Typename LIDAR confirmé : `IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle` ✓ (présent dans GetCapabilities)
- MNH disponible : `IGNF_MNH-LIDAR-HD:dalle` (option source `"mnh"` si retenu au spike)

---

## 3. Terje Mathisen / cove

> Évaluation externe à faire manuellement (hors script recon).

### Pipeline Terje Mathisen (tmsw.no)

- [ ] Évalué
- Produit du vecteur pour la végétation ? `TODO`
- Réutilisable comme dépendance ? `TODO`

### cove (vectoriseur raster, GPLv3)

- [ ] Évalué (issue OOM #833)
- Utilisable pour la végétation ? `TODO`

---

## 4. CRT Karttapullautin existant

- [x] Récupéré depuis **Blaze** (Trailblaze Software, Apache 2.0) — `src/lib/crt/crt.hpp`, `write_to_crt()` — 2026-08-06
- Chemin : `assets/kp_crt.crt` (25 entrées)

### Correspondance calques DXF KP v2.12.1 ↔ codes CRT

> Calques DXF réels (Phase 0) vs noms CRT (Blaze). Les décalages silencieux sont signalés.

| Calque DXF KP | Fichier DXF | Code CRT | Nom CRT | Statut |
|---|---|---|---|---|
| `contour` | `out2.dxf` | 101 | `101_Contour` | ✓ match |
| `contour_index` | `out2.dxf` | 102 | `102_Index_Contour` | ✓ match |
| `contour_intermed` | `out2.dxf` | 103 | `103_Form_Line` | ⚠ ambigu — intermed ≠ formline strictement |
| `depression` | `out2.dxf` | — | — | ✗ pas de code CRT depression standard (106 absent du CRT) |
| `depression_intermed` | `out2.dxf` | — | — | ✗ sans correspondance |
| `cliff2` | `c2g.dxf` | 202 | `202_Cliff` | ✓ match |
| `cliff3` | `c3g.dxf` | 201 | `201_Impassable_Cliff` | ✓ match |
| `dotknoll` | `dotknolls.dxf` | 109 | `109_Small_Knoll` | ✓ match |
| `udepression` | `dotknolls.dxf` | 111 | `111_Small_Depression` | ✓ match |
| `formline` | `formlines.dxf` | 103 | `103_Form_Line` | ✓ match |
| `uglydotknoll` | `dotknolls.dxf` | — | — | ✗ sans correspondance (calque auxiliaire KP) |
| `uglyudepression` | `dotknolls.dxf` | — | — | ✗ sans correspondance (calque auxiliaire KP) |
| `cont` | `out.dxf` | — | — | ✗ brut pré-lissage, non utilisé en production |
| `cont` | `contours03.dxf` | — | — | ✗ 0,3 m (9,5 MB), non utilisé |
| `1010` | `detected.dxf` | — | — | ✗ usage inconnu |

**Codes CRT sans calque DXF KP** (fournis par d'autres sources) :

| Code CRT | Nom CRT | Source attendue |
|---|---|---|
| 115 | `115_Prominent_Landform_Feature` | Manuel |
| 204–206 | Rochers/blocs | Manuel |
| 301–304, 313 | Eau | BD TOPO (troncon/surface_hydrographique) |
| 401, 403, 405 | Terrain ouvert / forêt | BD TOPO (zone_de_vegetation) |
| 406, 408, 410 | Végétation franchissabilité | Pipeline HAG (`vegetation_t8.gpkg`) |
| 407, 409 | Végétation bonne visibilité | Pipeline HAG (non généré à ce stade) |
| 419 | Élément végétation proéminent | Manuel |
| 531 | Élément anthropique proéminent | BD TOPO / Manuel |

**À retenir** : `depression` (dépression standard ISOM 106) est produite par KP mais **absente du CRT Blaze**. À surveiller lors du mapping CRT → OOM.

---

## 5. Décisions figées

> À remplir à la fin de la Phase 0. Ces décisions ne changent plus après.

| Brique | Décision | Justification |
|---|---|---|
| Courbes/falaises/buttes | Réutiliser tel quel (KP → CRT existant) | Existant éprouvé depuis 2014 |
| **Végétation** | `TODO : "kp"` ou `"pdal"` ou `"mnh"` | TODO — décidé au spike Phase 1 |
| Anthropique | Réutiliser BD TOPO → mapping YAML | Existant, pas d'algo |
| CRT Karttapullautin | Réutiliser et adapter | Orienteering BC |
| cove / Terje Mathisen | `TODO : réutiliser / ignorer` | TODO |

---

## 6. Mises à jour config.yaml à faire

- [x] `karttapullautin.version` (v2.12.1)
- [x] `karttapullautin.expected_dxf_layers`
- [x] `vegetation.source` → `"pdal"` (fixé spike Phase 1)
- [x] `bd_topo.layers` (confirmés 2026-06-23)
- [x] `symbols_isom.yaml → bd_topo_mapping` (confirmés 2026-06-23)

---

## 7. Décisions du spike Phase 1 (Grimbosq, 2026-06-24)

### Sources éliminées

| Source | Raison |
|---|---|
| `undergrowth.png` KP | Fichier quasi-vide dans KP v2.12.1 Rust |
| `undergrowth_bit.png` KP | Masque binaire tout noir — inutilisable |
| Classes LAS 3-5 | Mal renseignées / variables selon producteur |
| MNH | Non testé — dégradé attendu (capture hauteur, pas franchissabilité) |

### Source retenue

**`pdal` avec pipeline HAG 0.3–3 m** — meilleure variable physique disponible pour la franchissabilité.

> Nuance importante : HAG = meilleure **entrée** disponible, pas meilleure **sortie** garantie. La qualité finale dépend à 80 % de la vectorisation/généralisation (Phase 6), pas du raster brut.

`vegetation.png` KP conservé comme **couche auxiliaire potentielle** (Pipeline B : score = α·HAG + β·canopée).

### Ce que le spike a démontré

- Le raster HAG contient une information exploitable sur la franchissabilité ✓
- Raster brut ≠ carte CO (deux objets avec des buts différents) — le vrai levier est Phase 6
- Passer des semaines sur les paramètres HAG = gain marginal (~5%) vs. vectorisation/généralisation (~50%)

### Pipeline Phase 6 (mis à jour)

```
Raster HAG 0.3–3 m
    ↓ gaussian léger + médian
Classification 4 niveaux avec hystérésis (évite alternance vert1/vert2/vert1)
    ↓
GDAL Polygonize
    ↓
Dissolve par classe          ← opération critique
    ↓
CO Generalization Engine     ← voir docs/iof_generalization_rules.md
  - suppression petits polygones (seuils IOF)
  - suppression petits trous
  - fermeture corridors trop étroits
  - fusion îlots proches (distance configurable)
  - agrandissement symbolique
    ↓
Simplification Douglas-Peucker (tolérance ~2 m)
    ↓
Lissage Chaikin ×1            ← pas plus
    ↓
Export GeoJSON → import OOM  ← vérification visuelle avant tout writer natif
```

**Priorité Phase 6 :** Dissolve + CO Generalization Engine = 80 % de la qualité finale. Smoothing = secondaire.

### Config fixée

- `config.vegetation.source: "pdal"` ✓
- Prochaine priorité : Phase 6 vectorisation — pas les paramètres raster
