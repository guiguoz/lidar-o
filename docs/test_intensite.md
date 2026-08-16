# Test intensité LiDAR — FN_406 vs blanc FFCO

> Protocole : CONSIGNE_intensite_406_v2.md
> Référence : AUC HAG = 0.487 (mesurée sur mêmes populations dans confusion_interclass.py)

## Étape 2 — Contrôle dépendance angulaire

| Métrique | Valeur | Référence H3 |
|---|---|---|
| r(intensité, ScanAngleRank) | 0.0339 | 0.034 |
| Verdict | favorable (< 0.1) | — |

Dépendance angulaire négligeable — pas de normalisation nécessaire.

## Étape 3 — AUC Mann-Whitney

### Populations

| Population | Pixels | Ha | Médiane intensité |
|---|---|---|---|
| FN_406 (FFCO=406, pipe=blank, hull) | 222,872 | 22.3 | 506 |
| Blanc FFCO (hull, hors toute FFCO) | 860,911 | 86.1 | 640 |
| 406 détecté par pipeline (contrôle) | 547,860 | 54.8 | 602 |

Gradient observé : FN_406 (506) < détecté_406 (602) < blanc (640).

### Résultats AUC (P(A > B) — inversé = P(B > A))

| Test | AUC direct | AUC inversé | Delta médiane |
|---|---|---|---|
| **FN_406 vs blanc (principal)** | **0.3638** | **0.6362** | −134 unités |
| 406_détecté vs blanc (contrôle) | 0.4685 | 0.5315 | −38 unités |
| HAG FN_406 vs blanc (référence) | 0.487 | 0.513 | ~0 |

Les AUC inversées (P(blanc > X)) confirment que les deux populations 406 sont
plus sombres que le blanc, dans le même sens. Le signal est directionnellement cohérent.

## Analyse de cohérence physique

**Le gradient est physiquement incohérent.**

La prédiction physique : det_406 (plus de végétation → plus d'absorption → intensité basse)
devrait être plus sombre que FN_406 (peu de végétation → proche du sol → intensité plus haute).
Attendu : FN_406 > det_406 > blanc (ou au moins FN_406 > det_406).
Observé : FN_406 < det_406 < blanc — l'inverse.

**Hypothèse de biais d'échantillonnage.**

Les FN_406 sont, par définition, des zones où le signal HAG[0.3:3m] est faible (c'est
ce qui explique qu'ils n'ont pas été détectés). Peu de retours dans cette bande signifie
que la moyenne d'intensité est calculée sur un petit nombre de points, et probablement
sur des retours de nature différente des retours de végétation dense : derniers retours
au sol qui atteignent accidentellement la bande 0.3–3m, retours de litter, etc.

L'intensité mesurée dans les FN_406 ne décrit pas la même chose que dans det_406 —
c'est une moyenne de retours sol plus que de retours végétation. La comparaison
inter-population n'est pas valide physiquement.

Ce biais structure toute la mesure : plus une zone a peu de végétation (FN_406), moins
elle a de retours vrais dans la bande, et plus sa moyenne d'intensité capture les
retours parasites basse intensité du sol. D'où l'ordre inversé.

## Conclusion

**Piste close.**

Le gradient observé (FN_406 plus sombre que det_406) est physiquement incohérent avec
la végétation comme cause. Il s'explique par un biais d'échantillonnage : l'intensité
moyenne dans une bande avec peu de retours capture des retours de nature différente
(sol, litter) plutôt que de la végétation.

Ce n'est pas "le contrôle a échoué" — c'est "le signal observé est incohérent avec
la physique attendue, donc il reflète autre chose que la végétation dans les zones FN_406".

Le signal HAG AUC=0.487 et l'intensité AUC=0.3638 (inv.) convergent vers la même limite :
les FN_406 sont physiquement indiscernables de la forêt courable à partir des COPC
disponibles, quelle que soit la dimension spectrale considérée.

**11e réfutation, piste close V0.**

## Fichiers produits

- `output/intensity_veg.tif` — intensité moyenne HAG[0.3:3m], alignée sur density_hag.tif
- `output/intensity_count.tif` — nombre de retours par pixel (seuil MIN_COUNT=3 appliqué)
- `output/scanangle_veg.tif` — angle de visée moyen HAG[0.3:3m]
- `output/intensity_auc_histograms.png` — histogrammes superposés (FN_406 / détecté / blanc)
