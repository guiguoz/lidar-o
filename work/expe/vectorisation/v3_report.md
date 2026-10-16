# V3 — Généralisation géométrique KP raster (Grimbosq)

Paramètres : DP_TOL=2.0 m, Chaikin×2, coverage_simplify=2.0 m.
Zoom bbox plate 2 : (448970.6, 6887001.1, 449370.6, 6887401.1)

---

## Bras A — RAW (baseline)

Overlaps : 0 — Gaps couverture : 0.0 m²

| ISOM | Polys | ha | Méd m² | p95 m² | <100m² | Périm m | Sommets | Som/m | Trous | Slivers | Hausdorff p95/max m | RT ident/perdu/ajouté |
|-----:|------:|---:|-------:|-------:|-------:|--------:|--------:|-----:|------:|--------:|--------------------:|---------------------:|
| 406 | 1340 | 44.543 | 6.5 | 1173 | 938 | 135 474 | 83 178 | 0.614 | 320 | 0 | — | 445 434 / 0 / 0 |
| 408 | 409 | 27.662 | 140 | 2202 | 180 | 45 138 | 27 600 | 0.612 | 29 | 0 | — | 276 623 / 0 / 0 |
| 410 | 18 | 0.390 | 133 | 679 | 8 | 1 158 | 732 | 0.632 | 0 | 0 | — | 3 896 / 0 / 0 |

---

## Bras B — DP + Chaikin par polygone

Overlaps : 623 — Gaps couverture : 23 166 m²

| ISOM | Polys | ha | Méd m² | p95 m² | <100m² | Périm m | Sommets | Som/m | Trous | Slivers | Hausdorff p95/max m | RT ident/perdu/ajouté |
|-----:|------:|---:|-------:|-------:|-------:|--------:|--------:|-----:|------:|--------:|--------------------:|---------------------:|
| 406 | 1340 | 43.720 | 2.9 | 1143 | 978 | 96 555 | 48 623 | 0.504 | 320 | 564 | 3.51 / 10.9 | 408 794 / 36 640 / 23 537 |
| 408 | 409 | 26.734 | 110 | 2161 | 196 | 32 485 | 14 022 | 0.432 | 29 | 36 | 3.42 / 5.98 | 261 217 / 15 406 / 6 113 |
| 410 | 18 | 0.329 | 111 | 601 | 9 | 798 | 394 | 0.494 | 0 | 0 | 3.21 / 3.29 | 3 266 / 630 / 23 |

---

## Bras C — coverage_simplify combiné (3 classes)

Overlaps : 0 — Gaps couverture (porte de registre telle qu'écrite) : **1 320 m²** → **FAIL**

```
Topologie inter-classes : PASS (0 vide inter-classes, 0 overlaps,
                           arêtes partagées conservées)
Fidélité d'aire : INFORMATIVE (perte nette 1 320 m² = 1,82 % — décomposée ci-dessous)
Simplification : RETENUE (sous confirmation du tenant de porte)
Tolérance : 2 m
Réserve documentaire : la méthode n'est pas lossless en aire, contrairement
au RAW ; elle est topologiquement cohérente et géométriquement simplifiée.
```

| ISOM | Polys | ha | Méd m² | p95 m² | <100m² | Périm m | Sommets | Som/m | Trous | Slivers | Hausdorff p95/max m | RT ident/perdu/ajouté |
|-----:|------:|---:|-------:|-------:|-------:|--------:|--------:|-----:|------:|--------:|--------------------:|---------------------:|
| 406 | 1340 | 44.441 | 3.2 | 1166 | 940 | 108 708 | 19 385 | 0.178 | 320 | 395 | 1.79 / 5.10 | 433 353 / 12 081 / 11 152 |
| 408 | 409 | 27.633 | 138 | 2197 | 180 | 36 453 | 6 778 | 0.186 | 29 | 17 | 1.70 / 3.33 | 272 705 / 3 918 / 3 643 |
| 410 | 18 | 0.390 | 130 | 687 | 9 | 937 | 204 | 0.218 | 0 | 0 | 1.46 / 1.59 | 3 791 / 105 / 110 |

### Décomposition des 1 320 m² (depuis fichiers existants)

**Par classe :**

| Classe | RAW ha | C ha | Perte vect. m² | Perte % | Px perdu | Px ajouté | Polys supprimés |
|-------:|-------:|-----:|---------------:|--------:|---------:|----------:|----------------:|
| 406 | 44.543 | 44.441 | 1 025.5 | 0.23 % | 12 081 | 11 152 | **0** |
| 408 | 27.662 | 27.633 | 293.5 | 0.11 % | 3 918 | 3 643 | **0** |
| 410 | 0.390 | 0.390 | 1.0 | 0.03 % | 105 | 110 | **0** |
| **Total** | 72.595 | 72.463 | **1 320.0** | **0.18 %** | 16 104 | 14 905 | **0** |

**Slivers créés par C (présents dans C, absents de A) :**

| Classe | A slivers | C slivers | Créés | Surface créée m² |
|-------:|----------:|----------:|------:|-----------------:|
| 406 | 0 | 395 | +395 | 197.5 |
| 408 | 0 | 17 | +17 | 8.5 |
| 410 | 0 | 0 | 0 | 0 |

Les 412 slivers sont des polygones pré-existants (petits) devenus plus allongés après
coverage_simplify — leur aire est comptée dans C, pas une source de perte d'aire.

**Réconciliation :**

```
perte nette (vecteur) = 1 320 m²

= features entièrement supprimées              0 m²    (aucun polygon count réduit)
+ contraction frontière extérieure          1 856 m²   (ext_contr = perte + réduction_trous)
- réduction trous intérieurs                  536 m²   (trous_raw=94 255, trous_C=93 720)
                                          ────────
                                           1 320 m²  ✓

Mesure via round-trip raster (même grille V1) :
  recul frontière (px perdus)            16 104 m²
  avance frontière (px ajoutés)          14 905 m²
  net raster                              1 199 m²
  résidu de discrétisation (vect − rast)    121 m²    (≈ 9 % de 1 320)
```

**Réponse à quatre branches :**

> **(2) Déplacement de frontières uniquement.**
>
> Les 1 320 m² viennent exclusivement du déplacement des frontières par coverage_simplify
> (contraction extérieure 1 856 m² compensée par réduction des trous intérieurs 536 m²).
> Aucun polygone supprimé (comptes inchangés, aucune aire tombée à 0).
> Résidu vect-raster de 121 m² = artéfact de discrétisation, pas une source distincte.
> Slivers créés (206 m²) : artéfacts angulaires comptés dans l'aire de C, sans contribution à la perte.

---

## Bras D — coverage_simplify + Chaikin par polygone

> ABANDONNÉ — Chaikin par polygone brise les arêtes partagées : gap_combiné=6 050 m² après
> lissage. Edge-graph coverage-wide non implémenté (variante S1 abandonnée).

---

## Portes dures

| Bras | Overlaps | Gap m² | Status (porte de registre) |
|------|--------:|-------:|---------------------------|
| A RAW | 0 | 0 | **PASS** |
| B DP+Ch | 623 | 23 166 | **FAIL** |
| C cov_simp | 0 | 1 320 | **FAIL** (porte conservée telle qu'écrite) |
| D cov+Ch | — | — | non produit |

La porte telle qu'écrite exigeait implicitement RAW : aucune simplification géométrique
ne conserve l'aire exactement. Documenté — la porte mélangeait topologie inter-classes
et conservation d'aire et n'était pas suffisamment discriminante pour une simplification
de couverture.

---

⛔ STOP — relecture planche + choix méthode par le tenant de porte.
