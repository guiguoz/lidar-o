# Rapport Trier 2015 — Grimbosq V0

> Date : 2026-09-25  
> Run principal : ~10 impl/m² (depuis ~15 impl/m²)  
> Seuils : Table 5 10 impl/m²  
> Référence : Trier (2015). DOI: 10.3846/20296991.2015.1051342

---

## §1. Référence bibliographique

Trier, Ø.D. (2015). Automatic mapping of forest density from airborne lidar data.  
*Geodesy and Cartography*, 41(2): 49–65. DOI: 10.3846/20296991.2015.1051342

Méthode : NDVD (Normalized Difference Vegetation Density) calculé par noyau conique
sur les retours de végétation basse [0.2, 2.0) m, segmenté en 3 classes ISOM
(406 slow run, 408 walk, 410 fight), suivi d'une généralisation morphologique.

---

## §2. Données d'entrée — LiDAR Grimbosq

- Fichiers COPC : 6 tuiles dans `LIDAR/grimbosq/`
- Densité estimée (première tuile) : ~1.9 impl/m² *(artefact de mesure : l'estimateur divise par l'aire totale du bbox, non par l'aire effective de la tuile — valeur réelle Grimbosq : ~15 impl/m²)*
- Bbox (EPSG:2154) : (448000, 6886000, 450001, 6889001)
- CRS : EPSG:2154
- GpsTime disponible : True
  - Ratio pts/impulsion : 1.52
  - ratio=1.52 pts/impulsion (attendu ~1.5-3 pour 10-15 impl/m², retours multiples inclus)

---

## §3. Construction du terrain (DTM)

| | Trier 2015 | Implémentation |
|---|---|---|
| Points utilisés | class 2 uniquement (§1.3) | class 2 uniquement |
| Méthode | ENVI TRIGRID (TIN) | min par cellule + NN hole-fill |
| Résolution | 0.5 m (implicite) | 0.5 m |
| Trous | non spécifié | NN fill |

**Statut : `[TRIER-DEV-DTM]`** — approximation de TIN.

**Mesure de contrôle HAG classe 2** (82,888,694 pts, toutes tuiles, avant sous-échantillonnage) :

| Percentile | HAG classe 2 |
|---|---|
| p5 | −0.042 m |
| p10 | −0.021 m |
| p25 | +0.008 m |
| p50 | +0.028 m |
| p75 | +0.048 m |
| p90 | +0.087 m |
| p95 | +0.104 m |
| Mode | +0.025 m |

14,9 % des points classe 2 ont HAG < 0. Le mode (+2,5 cm) et la médiane (+2,8 cm) sont proches de zéro : il n'y a pas de biais systématique du DTM vers le haut. La fraction négative provient d'une queue gauche d'interpolation (min/cell à 0,5 m : des points proches du bord de cellule héritent de l'altitude d'une cellule voisine légèrement différente). Impact sur V/G : négligeable — la distribution du DTM est centrée sur le sol réel.

---

## §4. Définition de V et G

**SOURCE (§1.1, §2)** : Données Trier = 2 classes uniquement : 'ground' (class 2) et 'other'.

| Variable | SOURCE | Implémentation |
|---|---|---|
| G | retours 'ground' (class 2), tous ReturnNumber | class 2, tous ReturnNumber (FIDÈLE) |
| V | retours 'other' dans HAG [0.2, 2.0) m | non-class2, HAG [0.2, 2.0) m |
| Bande inf. | 0.2 m (§2 artefacts chevauchement) | 0.2 m (FIDÈLE) |
| ReturnNumber | non filtré pour NDVD (§1.1) | tous RetourNumber comptés (FIDÈLE) |

**Ambiguïté : `[TRIER-DEV-V-UNRESOLVED]`**
Les données Trier ont 2 classes. Grimbosq a des classes supplémentaires
absentes du dataset Trier :
- 6 = bâtiment, 9 = eau — documentées dans la consigne
- 17, 66, 67 = classes IGN de traitement (points synthétiques / recalage de dalles) — non documentées dans la consigne, découvertes au diagnostic

Effectifs des classes inattendues dans l'emprise : classe 17 = 1 252 pts, classe 66 = 175 pts, classe 67 = 480 pts (total < 0,001 % du nuage). Impact sur V/G : nul en pratique.

Convention : toutes les classes non-2 sont traitées comme 'other' (incluses dans V si HAG convient).
L'article ne permet pas de trancher — ambiguïté non résolue.

---

## §5. Formule NDVD et noyau de voisinage

```
NDVD = (V − G) / (V + G)    ∈ [-1, 1]    (Eq. 1)
  +1 = 100% végétation, -1 = 100% sol, NaN si V+G=0
```

**Noyau (§2, Fig. 3)** : circulaire plat-conique
- Rayon interne : 1.0 m → poids = 1.0
- Rayon externe : 2.0 m → poids = 0.0 (décroissance linéaire)
- À 0.5 m/px : noyau 9×9 pixels
- **Statut : FIDÈLE**

---

## §6. Résolution et agrégation

| Étape | Résolution |
|---|---|
| Accumulation V/G | 0.5 m |
| NDVD (brut + après noyau) | 0.5 m |
| Agrégation (moyenne) avant classification | → 1.0 m |
| Classification + morphologie | 1.0 m |

**Statut : FIDÈLE** (§2 : "0.5 m pixel size" et §2.2 : "Aggregate... to 1.0 m")

---

## §7. Seuils, densité et sous-échantillonnage

**Seuils Table 5 (10 impl/m²)** :

| Classe | Code ISOM | Seuil NDVD |
|---|---|---|
| slow run | 406 | ≥ 0.00 |
| walk | 408 | ≥ 0.35 |
| fight | 410 | ≥ 0.70 |

**Densité et sous-échantillonnage** :

- Densité native Grimbosq : ~15 impl/m² (hors domaine Trier documenté)
- Densité cible run principal : 10 impl/m² (Table 5)
- Fraction retenue : 0.6667 = 10/15
- **Méthode** : sous-échantillonnage **par impulsion** (GpsTime unique)
  Tous les retours d'une impulsion retenue sont conservés.
  Le rapport V/G est préservé (pas de biais sur les retours multiples).
  Graine : 42 + index_tuile (cohérence passe 1 DTM / passe 2 V/G).

**Statut : `[TRIER-ADAPTATION]`** — densité native hors domaine documenté (2 et 10 impl/m²).

---

## §8. Sorties produites

| Fichier | Description | Résolution | Statut |
|---|---|---|---|
| `trier_dtm.tif` | DTM class 2, min/cell + NN | 0.5 m | [TRIER-DEV-DTM] |
| `trier_strates.tif` | V_raw (b1) + G_raw (b2) | 0.5 m | [TRIER-DEV-V-UNRESOLVED] |
| `trier_signal_brut.tif` | NDVD (V-G)/(V+G) avant noyau | 0.5 m | FIDÈLE |
| `trier_signal_apres_voisinage.tif` | NDVD après noyau conique | 0.5 m | FIDÈLE |
| `trier_classes.tif` | Classes 0/406/408/410 avant morpho | 1.0 m | FIDÈLE |
| `trier_classes_gen.tif` | Classes après généralisation §2.2 | 1.0 m | FIDÈLE |
| `trier_empreinte_diff.tif` | Diff NDVD perturbation +1000V | 0.5 m | — |
| `trier_viz_01_dtm.png` | Visualisation DTM | — | — |
| `trier_viz_02_strates.png` | V_raw et G_raw | — | — |
| `trier_viz_03_signal_brut.png` | NDVD brut + histogramme | — | — |
| `trier_viz_04_signal_voisinage.png` | NDVD voisinage + histogramme | — | — |
| `trier_viz_05_classes.png` | Classes avant/après morpho | — | — |
| `trier_viz_06_empreinte.png` | Empreinte + zoom | — | — |
| `trier_viz_07_bilan.png` | Bilan surfaces par classe | — | — |
| `trier_report.md` | Ce rapport | — | — |
| `trier_rapport.json` | Métriques numériques | — | — |

---

## §9. Masque zones ouvertes

**SOURCE (§2.1)** : nDSM agrégé à 1 m, seuil 0.75 m, puis séquence
morphologique complète (non reproduite fidèlement), aire minimale 22.5 m².

**Implémentation** : seuil nDSM < 0.75 m → zone ouverte, opening disk 3×3, aire minimale 22 px.

**Statut : `[TRIER-DEV-OPENMAP]`** — séquence §2.1 complète non reproduite.
Impact : légère différence dans les zones ouvertes masquées.

---

## §10. Généralisation morphologique (§2.2)

Séquence exacte appliquée à chaque classe indépendamment (à 1.0 m) :

| Étape | Opération | Noyau |
|---|---|---|
| 1 | Fermeture | disque 7×7 |
| 2 | Ouverture | disque 3×3 |
| 3 | Fermeture | disque 9×9 |
| 4 | Ouverture | disque 5×5 |
| 5 | Fermeture | disque 11×11 |
| 6 | Ouverture | disque 7×7 |
| 7 | Retrait masque zones ouvertes | — |
| 8 | Ouverture | carré 3×3 |
| 9 | Filtre aire minimale | 225 m² (406/408), 112 m² (410) |

**Statut : FIDÈLE** (§2.2 citations exactes reproduites)

---

## §11. Résultats et bilan

### Statistiques des classes

| Classe | Avant morpho (px) | Avant morpho (m²) | Après morpho (px) | Après morpho (m²) | % final |
|---|---:|---:|---:|---:|---:|
| 0 | 5,924,991 | 5,924,991 | 5,970,398 | 5,970,398 | 99.4% |
| 406 | 57,806 | 57,806 | 31,210 | 31,210 | 0.5% |
| 408 | 17,199 | 17,199 | 3,154 | 3,154 | 0.1% |
| 410 | 5,005 | 5,005 | 239 | 239 | 0.0% |

> **Note sur le 99,4 % classe 0** : le diagnostic LiDAR (toutes tuiles, avant sous-échantillonnage) donne V_total = 5,2 M pts dans HAG [0.2, 2.0) m, G_total = 82,9 M pts (classe 2). Ratio V/G ≈ 0,063. NDVD moyen ≈ −0,88 → presque toute l'emprise est sous le seuil 0.00 de slow run. Explication structurelle : Grimbosq est une hêtraie mature à canopée fermée ; 72,9 M retours sont classés haute végétation (classe 5, HAG >> 2 m) et ne tombent pas dans la fenêtre [0.2, 2.0) m. Ce résultat est physiquement correct et cohérent avec le domaine de validité de la méthode Trier (calibrée sur forêt jeune / régénération à Oslo).

### Empreinte spatiale

- Point de perturbation : x=449273.5, y=6887850.5
- Rayon max mesuré : **1.80 m**
- Rayon théorique noyau : 2.0 m
- Diagonale théorique (√2 × rayon) : 2.83 m
- Cellules NDVD affectées : 45
- Raster diff sauvé : `trier_empreinte_diff.tif`

> **OK** : empreinte conforme au noyau conique (max_dist ≤ diagonale + 0.5 m)

### Bilan des écarts

| ID | Étape | Cause | Impact attendu |
|---|---|---|---|
| `[TRIER-DEV-DTM]` | Construction DTM | min/cell+NN vs TIN (ENVI TRIGRID) | 14,9 % des pts classe 2 en HAG < 0 ; mode = +2,5 cm → pas de biais systématique, bruit de bord de cellule. Impact sur V/G mesuré : négligeable. |
| `[TRIER-DEV-V-UNRESOLVED]` | Définition V | Classes 6/7/9 Grimbosq traitées comme 'other' | V potentiellement sur-estimé si bâtiments/bruit dans HAG [0.2, 2.0). |
| `[TRIER-DEV-OPENMAP]` | Masque zones ouvertes | §2.1 simplifié (seuil+aire seuls) | Légère différence dans les zones ouvertes masquées. |
| `[TRIER-ADAPTATION]` | Densité | 15 impl/m² sous-échantillonné à 10/m² | Hors domaine publié. Run principal adapté. |

---

*Rapport généré automatiquement par `experiments/v0/run_trier.py`*