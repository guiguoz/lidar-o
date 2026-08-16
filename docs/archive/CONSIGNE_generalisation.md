# Consigne Claude Code — Généralisation : de la texture aux masses

> Fait suite au contrôle visuel Grimbosq (`v3_vegetation_fd`, σ=1.0, fd=2).
> **Le contrôle est concluant sur la détection et négatif sur la généralisation.**
> Cette consigne traite le seul écart identifié.

---

## Résultat du contrôle visuel — à intégrer au plan v3

Comparaison pipeline vs carte FFCO Grimbosq, **sur emprise commune** (hull FFCO = 326 ha,
et non les 600 ha de l'emprise pipeline — le clip est indispensable, c'est la troisième fois
qu'un dénominateur erroné fausse une conclusion dans ce projet) :

| classe | FFCO | pipeline |
|---|---|---|
| 406 | 19,1 % / 463 poly / **médiane 5,17 mm²** / 3,7 % < 1 mm² | 21,7 % / 700 / **2,01 mm²** / 11,1 % |
| 408 | 6,8 % / 432 / **2,31 mm²** / 13,4 % | 10,6 % / 621 / **1,22 mm²** / 40,9 % |
| 410 | 8,0 % / 363 / **1,39 mm²** / 32,0 % | 6,3 % / 505 / **0,66 mm²** / 63,4 % |
| **total** | **154,0 ha / 1516 poly** | **125,9 ha / 1826 poly** |

*(mm² = surface à l'échelle d'impression 1:10 000, où 1 mm² carte = 100 m² terrain)*

**Conclusions :**
1. **La détection est bonne.** Surface ×0,82, nombre de polygones ×1,20. Le pipeline ne
   sur-détecte pas — il produit même *moins* de végétation que la carte. Le verdict initial
   « confetti / lichen » était faux, tiré d'une comparaison contre une norme abstraite au lieu
   de la carte réelle.
2. **Les petites taches sont normales.** 32 % du 410 de la carte FFCO fait moins de 1 mm².
   Ne pas chercher à les éliminer par principe.
3. **L'écart réel est la granularité.** Le cartographe produit des taches **2,5× plus grosses
   en médiane**, avec des contours francs et peu de trous internes. Le pipeline couvre les
   mêmes surfaces mais en formes filandreuses criblées de lucarnes.
4. **Le 410 est sous-détecté** (6,3 % contre 8,0 %) *et* le plus fragmenté. La végétation dense
   existe mais est éparpillée au lieu d'être massée.

**C'est un problème de généralisation cartographique, pas de signal.** Bonne nouvelle : ça se
traite avec des paramètres qui existent déjà.

---

## Nouvelle métrique de suivi — obligatoire à partir de maintenant

Aux deux métriques existantes (couverture %, concentration du plus gros polygone), **ajouter la
taille médiane des taches en mm² à 1:10 000**. C'est elle qui mesure l'écart restant.

Cibles FFCO Grimbosq sur emprise hull : **406 → 5,17 mm² | 408 → 2,31 | 410 → 1,39**

Le quadruplet à sortir à chaque run, par classe : `couverture %`, `n polygones`,
`médiane mm²`, `% < 1 mm²`. Plus la concentration du plus gros polygone en garde-fou
anti-percolation (plancher connu : 7,4 %).

---

## Étape 1 — `remove_holes` (levier principal présumé, coût nul)

Le FFCO n'a quasiment pas de lucarnes internes ; le pipeline en est criblé. Ces trous sont la
cause directe de l'aspect dentelle **et** de la médiane trop basse.

- Sweep du seuil de `remove_holes` sur au moins 4 valeurs, en partant de la valeur actuelle
  vers des valeurs nettement plus élevées.
- Effet attendu si l'hypothèse est juste : surface **en hausse** (les trous se comblent),
  nombre de polygones **en baisse**, médiane **en hausse** vers 5,17 mm².
- Garde-fou : la concentration du plus gros polygone ne doit pas repartir vers la percolation.

## Étape 2 — `min_area` sur 408 et 410

Aujourd'hui seul le 406 est filtré (100 m² = 1 mm², visible dans les données : son p10 est à
1,02 mm², le filtre coupe net). 408 et 410 n'ont pas d'équivalent, d'où leurs 40,9 % et 63,4 %
sous le seuil de lisibilité.

- Calibrer pour approcher les taux FFCO (13,4 % et 32,0 %), **pas pour les annuler**.
- **Surveiller la surface du 410 en priorité** : il est déjà sous-détecté à 6,3 % contre 8,0 %.
  Si le filtrage la fait chuter nettement, c'est que le problème n'est pas la taille des taches
  mais leur dispersion → passer à l'étape 3 et revenir en arrière sur `min_area[410]`.

## Étape 3 — Fermeture morphologique (seulement si 1 et 2 ne suffisent pas)

Si la médiane reste loin de la cible après les deux premières étapes, il manque une opération
d'agrégation : une **fermeture** (dilatation puis érosion) en espace raster, avant polygonize,
pour combler les micro-espaces entre taches voisines.

⚠️ **Prudence absolue** : c'est le même mécanisme qui a produit la nappe de 75 ha avec σ=3.0.
Doser par petits incréments, noyau lié à l'échelle (3×3 ou 5×5 maximum), et lire le quadruplet
à chaque pas. Toute remontée de la concentration au-dessus de ~10 % est un signal d'arrêt.

Ne pas confondre avec l'**ouverture** décrite dans l'ancien plan v2 (qui retire les bandes trop
fines) — ici on veut l'opération inverse.

---

## Ce qu'il ne faut pas faire

- **Ne pas toucher à σ (1.0) ni à fd (2)** : validés, tagués, et hors sujet ici — le problème
  est en aval de la classification.
- **Ne pas chercher à éliminer toutes les petites taches** : le cartographe en met beaucoup
  (32 % du 410 FFCO sous 1 mm²). La cible est la distribution FFCO, pas zéro.
- **Ne pas comparer sur des emprises différentes.** Toute comparaison FFCO/pipeline se fait sur
  le hull FFCO clippé, jamais sur la bbox du pipeline.
- **Ne pas conclure sur la seule couverture** : c'est la médiane qui porte l'écart restant.

## Livrable

- Tableau de sweep par étape, avec le quadruplet complet par classe.
- Un run de production avec les valeurs retenues, `run_metadata.json`, nom explicite, tag.
- Mise à jour du plan v3 §6 : résultat du contrôle visuel, nouvelle métrique de suivi, et
  correction du diagnostic (détection bonne, généralisation insuffisante).
- 🧑 **Nouveau contrôle visuel** sur le run retenu — comparaison côte à côte avec le FFCO sur
  la même fenêtre de 500 m, à 1:10 000.
