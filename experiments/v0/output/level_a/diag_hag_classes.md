# Diagnostic HAG par classe LAS — Grimbosq V0

**Classe LAS 2 : 0.80 % des points ont HAG ≥ 0,2 m**

---

## Métadonnées

- Tuiles analysées : 6 (LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz, LHD_FXX_0448_6888_PTS_LAMB93_IGN69.copc.laz, LHD_FXX_0448_6889_PTS_LAMB93_IGN69.copc.laz, LHD_FXX_0449_6887_PTS_LAMB93_IGN69.copc.laz, LHD_FXX_0449_6888_PTS_LAMB93_IGN69.copc.laz, LHD_FXX_0449_6889_PTS_LAMB93_IGN69.copc.laz)
- Emprise (EPSG:2154) : (448000, 6886000) — (450001, 6889001)
- Total points : 161,851,931
- DTM utilisé : `trier_dtm.tif` (0.5 m, class 2, min/cell + NN fill)
- Méthode HAG : `Z − DTM[cellule_la_plus_proche]`  (identique à trier_ref.py)
- Intervalles : 20 × 0.15 m de 0 à 3.0 m

---

## Résultats par classe

### Classe 1 — unclassified (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 370,442 |
| HAG non calculable (hors grille DTM) | 1 |
| HAG < 0 m | 8,774 |
| HAG ∈ [0, 0.2) m | 253,727 |
| HAG ∈ [0.2, 3.0) m | 98,666 |
| HAG ≥ 0.2 m (toutes haut.) | 107,940 |
| HAG ≥ 3.0 m | 9,274 |
| **Fraction HAG ≥ 0.2 m** | **29.14 %** |

### Classe 2 — ground (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 82,888,807 |
| HAG non calculable (hors grille DTM) | 113 |
| HAG < 0 m | 12,367,631 |
| HAG ∈ [0, 0.2) m | 69,860,006 |
| HAG ∈ [0.2, 3.0) m | 661,054 |
| HAG ≥ 0.2 m (toutes haut.) | 661,057 |
| HAG ≥ 3.0 m | 3 |
| **Fraction HAG ≥ 0.2 m** | **0.80 %** |

### Classe 3 — low_veg (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 2,573,747 |
| HAG non calculable (hors grille DTM) | 3 |
| HAG < 0 m | 90,362 |
| HAG ∈ [0, 0.2) m | 1,675,139 |
| HAG ∈ [0.2, 3.0) m | 808,242 |
| HAG ≥ 0.2 m (toutes haut.) | 808,243 |
| HAG ≥ 3.0 m | 1 |
| **Fraction HAG ≥ 0.2 m** | **31.40 %** |

### Classe 4 — med_veg (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 2,661,273 |
| HAG non calculable (hors grille DTM) | 1 |
| HAG < 0 m | 2,384 |
| HAG ∈ [0, 0.2) m | 3,558 |
| HAG ∈ [0.2, 3.0) m | 2,655,252 |
| HAG ≥ 0.2 m (toutes haut.) | 2,655,330 |
| HAG ≥ 3.0 m | 78 |
| **Fraction HAG ≥ 0.2 m** | **99.78 %** |

### Classe 5 — high_veg (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 72,936,955 |
| HAG non calculable (hors grille DTM) | 40 |
| HAG < 0 m | 747 |
| HAG ∈ [0, 0.2) m | 822 |
| HAG ∈ [0.2, 3.0) m | 5,321,721 |
| HAG ≥ 0.2 m (toutes haut.) | 72,935,346 |
| HAG ≥ 3.0 m | 67,613,625 |
| **Fraction HAG ≥ 0.2 m** | **100.00 %** |

### Classe 6 — building (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 418,520 |
| HAG non calculable (hors grille DTM) | 0 |
| HAG < 0 m | 19 |
| HAG ∈ [0, 0.2) m | 376 |
| HAG ∈ [0.2, 3.0) m | 82,997 |
| HAG ≥ 0.2 m (toutes haut.) | 418,125 |
| HAG ≥ 3.0 m | 335,128 |
| **Fraction HAG ≥ 0.2 m** | **99.91 %** |

### Classe 9 — water (demandée)

| Métrique | Valeur |
|---|---|
| Total points | 280 |
| HAG non calculable (hors grille DTM) | 0 |
| HAG < 0 m | 91 |
| HAG ∈ [0, 0.2) m | 189 |
| HAG ∈ [0.2, 3.0) m | 0 |
| HAG ≥ 0.2 m (toutes haut.) | 0 |
| HAG ≥ 3.0 m | 0 |
| **Fraction HAG ≥ 0.2 m** | **0.00 %** |

### Classe 17 — class_17 (non demandée)

| Métrique | Valeur |
|---|---|
| Total points | 1,252 |
| HAG non calculable (hors grille DTM) | 0 |
| HAG < 0 m | 223 |
| HAG ∈ [0, 0.2) m | 510 |
| HAG ∈ [0.2, 3.0) m | 519 |
| HAG ≥ 0.2 m (toutes haut.) | 519 |
| HAG ≥ 3.0 m | 0 |
| **Fraction HAG ≥ 0.2 m** | **41.45 %** |

### Classe 66 — class_66 (non demandée)

| Métrique | Valeur |
|---|---|
| Total points | 175 |
| HAG non calculable (hors grille DTM) | 0 |
| HAG < 0 m | 174 |
| HAG ∈ [0, 0.2) m | 1 |
| HAG ∈ [0.2, 3.0) m | 0 |
| HAG ≥ 0.2 m (toutes haut.) | 0 |
| HAG ≥ 3.0 m | 0 |
| **Fraction HAG ≥ 0.2 m** | **0.00 %** |

### Classe 67 — class_67 (non demandée)

| Métrique | Valeur |
|---|---|
| Total points | 480 |
| HAG non calculable (hors grille DTM) | 0 |
| HAG < 0 m | 0 |
| HAG ∈ [0, 0.2) m | 0 |
| HAG ∈ [0.2, 3.0) m | 480 |
| HAG ≥ 0.2 m (toutes haut.) | 480 |
| HAG ≥ 3.0 m | 0 |
| **Fraction HAG ≥ 0.2 m** | **100.00 %** |

---

## Classes absentes

Classes demandées non présentes : [0, 7]

---

## Tableau histogramme — 20 intervalles × classes

| Intervalle | cls1 (%) | cls2 (%) | cls3 (%) | cls4 (%) | cls5 (%) | cls6 (%) | cls9 (%) | cls17 (%) | cls66 (%) | cls67 (%) |
|---|---|---|---|---|---|---|---|---|---|---|
| [0.00,0.15) | 59.58 | 83.12 | 50.21 | 0.09 | 0.00 | 0.06 | 67.50 | 38.50 | 0.57 | 0.00 |
| [0.15,0.30) | 15.16 | 1.73 | 29.63 | 0.17 | 0.00 | 0.08 | 0.00 | 4.87 | 0.00 | 0.00 |
| [0.30,0.45) | 2.53 | 0.17 | 10.69 | 0.53 | 0.00 | 0.06 | 0.00 | 3.19 | 0.00 | 0.00 |
| [0.45,0.60) | 1.02 | 0.03 | 4.44 | 2.72 | 0.00 | 0.05 | 0.00 | 2.40 | 0.00 | 0.00 |
| [0.60,0.75) | 1.10 | 0.01 | 1.02 | 5.75 | 0.00 | 0.06 | 0.00 | 4.95 | 0.00 | 0.00 |
| [0.75,0.90) | 1.35 | 0.00 | 0.31 | 9.06 | 0.00 | 0.08 | 0.00 | 5.51 | 0.00 | 0.00 |
| [0.90,1.05) | 1.67 | 0.00 | 0.11 | 13.64 | 0.00 | 0.11 | 0.00 | 7.51 | 0.00 | 0.00 |
| [1.05,1.20) | 1.94 | 0.00 | 0.05 | 20.34 | 0.00 | 0.18 | 0.00 | 0.56 | 0.00 | 0.00 |
| [1.20,1.35) | 1.63 | 0.00 | 0.02 | 21.20 | 0.01 | 0.23 | 0.00 | 1.28 | 0.00 | 0.21 |
| [1.35,1.50) | 1.47 | 0.00 | 0.01 | 18.98 | 0.05 | 0.30 | 0.00 | 1.68 | 0.00 | 6.67 |
| [1.50,1.65) | 1.31 | 0.00 | 0.01 | 6.68 | 0.56 | 0.39 | 0.00 | 5.19 | 0.00 | 42.08 |
| [1.65,1.80) | 1.07 | 0.00 | 0.00 | 0.54 | 0.75 | 0.58 | 0.00 | 1.84 | 0.00 | 31.04 |
| [1.80,1.95) | 1.06 | 0.00 | 0.00 | 0.12 | 0.78 | 1.04 | 0.00 | 3.04 | 0.00 | 19.38 |
| [1.95,2.10) | 0.87 | 0.00 | 0.00 | 0.04 | 0.76 | 1.49 | 0.00 | 0.88 | 0.00 | 0.62 |
| [2.10,2.25) | 0.79 | 0.00 | 0.00 | 0.02 | 0.73 | 2.04 | 0.00 | 0.40 | 0.00 | 0.00 |
| [2.25,2.40) | 0.76 | 0.00 | 0.00 | 0.01 | 0.77 | 2.27 | 0.00 | 0.24 | 0.00 | 0.00 |
| [2.40,2.55) | 0.71 | 0.00 | 0.00 | 0.01 | 0.74 | 2.52 | 0.00 | 0.08 | 0.00 | 0.00 |
| [2.55,2.70) | 0.50 | 0.00 | 0.00 | 0.00 | 0.74 | 2.76 | 0.00 | 0.08 | 0.00 | 0.00 |
| [2.70,2.85) | 0.35 | 0.00 | 0.00 | 0.00 | 0.72 | 2.78 | 0.00 | 0.00 | 0.00 | 0.00 |
| [2.85,3.00) | 0.26 | 0.00 | 0.00 | 0.00 | 0.68 | 2.85 | 0.00 | 0.00 | 0.00 | 0.00 |

---

## Question interprétative unique

La classe LAS 2 ne contient que 0.80 % de points avec HAG ≥ 0,2 m (661,057 points). Cette fraction est **trop faible pour expliquer seule la faiblesse de V**.