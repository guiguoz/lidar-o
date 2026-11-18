# V1 — Round-trip KP raster → vecteurs (Grimbosq)

Emprise d'analyse : (448000, 6886000, 450001, 6889000) EPSG:2154 — 2001 × 3000 px, 1 m/px.
Note : bbox terrain config = (…, 6889001) ; KP n'a pas de tuile pour la rangée nord +1 m
→ raster height = 3000 px (pas 3001). La rangée manquante est en dehors de toute tuile KP.

---

## V1.1 Bilan zéro — distribution des teintes

| Bit KP | ha | % emprise | ISOM effectif |
|-------:|---:|----------:|---------------|
| 0 | 293.68 | 48.92 | — (blanc, forêt courable) |
| 1 | 175.31 | 29.20 | — (jaune, ignoré BD TOPO) |
| 2 | 58.72 | 9.78 | → **0** (décision table) |
| 3 | 25.92 | 4.32 | 406 |
| 4 | 18.63 | 3.10 | 406 |
| 5 | 20.03 | 3.34 | 408 |
| 6 | 7.63 | 1.27 | 408 |
| 7 | 0.18 | 0.03 | 410 |
| 8 | 0.21 | 0.04 | 410 |

Total vert : 131.3 ha — dont 58.7 ha (bit 2) délibérément laissés blancs.

---

## V1.2 Classification et vectorisation

Table shade_to_isom appliquée (gelée config.yaml) :

```
  2 → 0     (décision calibration : greenshades[0]=0.2 pt/m², forêt courable)
  3 → 406   4 → 406
  5 → 408   6 → 408
  7 → 410   8 → 410
```

Sorties : source_classes.tif (2001 × 3000 px, uint8, DN 85/170/255),
vectorized_raw.gpkg (1 767 polygones après dissolve).

---

## V1.3A Round-trip complet

### Registre A — Décisions de table

Bits délibérément laissés à 0 : **[2]**
Pixels concernés : **587 194 px (58.72 ha)**

Ces pixels sont absents de source_classes.tif par choix de calibration.
Ils ne peuvent ni apparaître dans le round-trip, ni compter comme perte vectoriseur.

### Registre B — Pertes vectoriseur

| Classe | source px | identiques | différents | perdus | ajoutés |
|-------:|----------:|-----------:|-----------:|-------:|--------:|
| **406** | 445 434 | 445 434 | **0** | **0** | **0** |
| **408** | 276 623 | 276 623 | **0** | **0** | **0** |
| **410** | 3 896 | 3 896 | **0** | **0** | **0** |
| **Total vég.** | 725 953 | 725 953 | **0** | **0** | **0** |
| **Total raster** | 6 003 000 | 6 003 000 | **0** | **0** | **0** |

Round-trip **lossless** : 0 pixel différent, 0 perdu, 0 ajouté.
Attendu sans simplification ; confirme que polygonize + dissolve est une transformation
réversible sur source catégorielle.

---

## V1.3B Statistiques géométriques

### Définitions

- **Trous** : anneaux intérieurs (interior rings) d'un polygone — représentent des clairières
  enclavées dans un patch végété.
- **Isthmes potentiels** : polygones dont le rapport P/√A > 15 — forme très allongée ou étranglée
  (référence : disque = 3,54 ; isthme typique > 15). Ce sont des *candidats* à la coupure, pas
  des isthmes confirmés.
- **Slivers** : polygones avec area < 1 m² OU (area < 100 m² ET P/√A > 20) — artéfacts fins
  générés par la pixellisation.
- **Gaps** : surface non couverte entre polygones adjacents — 0 par construction sur source
  catégorielle (chaque pixel appartient exactement à une classe).

### Métriques par classe

| ISOM | Polys | Surface ha | Méd. m² | p95 m² | < 100 m² | Frontière tot. (m) | Sommets | Som./m | Trous | Slivers | Isthmes pot. |
|-----:|------:|-----------:|--------:|-------:|---------:|-------------------:|--------:|-------:|------:|--------:|-------------:|
| 406 | 1 340 | 44.54 | 6 | 1 173 | 938 | 135 474 | 83 178 | 0.614 | 320 | 0 | 32 |
| 408 | 409 | 27.66 | 140 | 2 202 | 180 | 45 138 | 27 600 | 0.612 | 29 | 0 | 1 |
| 410 | 18 | 0.39 | 133 | 679 | 8 | 1 158 | 732 | 0.632 | 0 | 0 | 0 |

**Gaps inter-classes** : 0 m² (union des polygones = pixels non nuls source, à 1 m² près).
**Chevauchements** : 0 (source catégorielle — impossible par construction).

Observation : 406 est massivement fragmenté (médiane 6 m², 70 % des polygones < 100 m²,
83 178 sommets pour 44,5 ha). Problème géométrique, pas de classification — origine : grille 1 m/px
qui produit des micro-patches au bord de chaque pixel classifié différemment.

---

## V1.4 Planche

Voir `v1_plate.png` — 4 panneaux à 1:10 000 :
- A : KP vegetation.png original (RGB)
- B : raster classifié 406/408/410
- C : vecteurs dissolve (sans simplification)
- D : vecteurs + fond KP α=50 %

---

## Verdict

```
V1.4 : ACCEPTÉE (tenant de porte, 2026-10-03)
Round-trip raster → vecteur : lossless (0 px différent, 0 perdu, 0 ajouté — toutes classes)
Table shade_to_isom : GELÉE (V1.6), identique tous terrains
V1.5 : CLOSE — aucune observation déclenchée sur la planche
```

L'exécuteur ne commite pas : ce rapport reste dans work/expe/ (gitignoré).
Le commit documentaire = l'amendement de plan côté repo (source de vérité).
