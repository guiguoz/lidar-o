# Consigne Claude Code — Routage jaune/vert par la canopée

> Teste l'hypothèse la plus prometteuse restante pour élargir le domaine de validité.
> Chantier court, données déjà en place, mesurable immédiatement contre les cartes de référence.

---

## Le problème, tel que quatre terrains l'ont établi

Le pipeline classe **tout** signal HAG dans la bande 0,3–3 m en végétation verte (406/408/410).
ISOM ne fait pas ça : il code la **praticabilité du sol**, et réserve le vert au sous-bois
**sous couvert forestier**. En terrain ouvert, la même végétation basse s'exprime en **jaune**
(401/403/404).

Conséquences mesurées :

| terrain | échec | mécanisme |
|---|---|---|
| Airelles | ×4,8 couverture | 53,7 % du 406 pipeline tombe en **terrain découvert** FFCO |
| Kilemäed | ×18/×73/∞ | 55,9 % en terrain ouvert ; référence n'utilise **aucun** 410 |
| Kuti | ×5,45 sur 408 | sous-bois uniforme, signal peu différencié |
| Sandringham (non traité) | attendu | 35,7 % de lande ouverte, 6,6 % de vert seulement |

Trois de ces quatre échecs ont la même racine : **le pipeline ne teste jamais la présence d'une
canopée au-dessus**.

## L'hypothèse à tester

**Router la classe selon la canopée, au lieu de tout envoyer en vert :**

```
végétation basse détectée
├─ canopée présente au-dessus  → 406 / 408 / 410  (vert, sous-bois)
└─ pas de canopée              → 403 / 404        (jaune, terrain découvert)
```

**Ce n'est pas le masque canopée réfuté précédemment.** H2 testait `count_high/total > seuil`
comme **filtre binaire** — garder ou jeter — et les distributions ne séparaient pas
(Airelles : open 0,441 vs veg_406 0,438). Ici la canopée sert de **règle de routage entre deux
classes**, ce qui est la convention ISOM elle-même. Une distribution qui ne sépare pas
franchement peut malgré tout router correctement la majorité des cas.

**Réserve honnête à garder** : H2 a montré que `count_high` ne discrimine pas les zones FFCO
sur Airelles. Si le routage échoue, c'est cohérent avec ce résultat et la piste est close.

---

## Étape 1 — Données

`count_high.tif` existe déjà pour Grimbosq et Airelles (produit par `run_count_high.py`,
bande HAG > 3 m). Vérifier sa présence ; le régénérer sur Kilemäed et Kuti si absent.

## Étape 2 — Calibrer le seuil de canopée contre la référence

**Ne pas choisir un seuil a priori.** Le calibrer sur Airelles, terrain où le désaccord est le
mieux caractérisé :

1. Pour chaque cellule classée en végétation par le pipeline, relever la valeur de canopée
   (`count_high / total`, ou `count_high` brut — tester les deux).
2. Croiser avec la classe FFCO réelle de la cellule : terrain découvert (401/403/404) vs
   végétation (406/408/410).
3. Sortir la courbe : pour chaque seuil candidat, quel taux de cellules correctement routées ?

Le seuil retenu est celui qui maximise l'accord. **S'il n'existe aucun seuil donnant un accord
nettement supérieur au hasard, l'hypothèse est réfutée** — le dire et s'arrêter là.

Rappel du contexte : H2 a mesuré des médianes de 0,441 (terrain ouvert) contre 0,438 (veg_406)
sur Airelles. Un routage utile suppose que la séparation existe malgré ces médianes proches —
par exemple dans les queues de distribution. À vérifier, pas à espérer.

## Étape 3 — Implémentation

Si le seuil existe, l'appliquer dans la classification (`process_hag.py` ou en aval) :
- Cellule au-dessus du seuil de canopée → classes vertes selon les seuils actuels
- Cellule en dessous → 403 (terrain découvert rugueux) ou 404 selon la densité

**Le 404** (« terrain découvert avec arbres dispersés ») est le cas intermédiaire naturel :
canopée faible mais non nulle. À envisager seulement si le routage binaire fonctionne d'abord.

Ne pas toucher aux seuils de densité existants (σ=1.0, T_406/408/410, `min_area`) — c'est le
routage qu'on teste, pas la calibration.

## Étape 4 — Mesure sur les quatre terrains

Pour chacun, avant / après routage, sur **hull de la carte de référence clippé** :

- couverture par classe, référence vs pipeline
- répartition du 406 pipeline dans la légende de référence (le test qui a tranché Airelles,
  Kilemäed et Kuti)
- nouvelle métrique : couverture 403/404 produite vs référence

**Critère de succès** : le surplus de vert en terrain ouvert doit chuter nettement, sans
dégrader Grimbosq. Sur Airelles, les 53,7 % de 406 en terrain découvert devraient tomber ;
sur Grimbosq, la couverture 406 doit rester proche de 16,6 % (référence figée 942/611/465).

**Contrôle de non-régression Grimbosq obligatoire** : c'est le seul terrain dans le domaine,
le dégrader pour gagner ailleurs serait une mauvaise affaire.

## Étape 5 — Verdict

Trois issues, toutes documentables :

1. **Le routage fonctionne** → plusieurs terrains rentrent potentiellement dans le domaine.
   Mettre à jour le plan v3 §6.3 et relancer les quatre terrains.
2. **Il fonctionne partiellement** (améliore Airelles, pas Kuti) → domaine élargi mais pas
   universel ; documenter quels modes d'échec il traite.
3. **Il ne fonctionne pas** → dernière piste simple éliminée. Le plafond sémantique est
   confirmé comme structurel, et la suite est Broadland (test de faux positif) ou la
   consolidation de ce qui marche sur Grimbosq.

---

## Ce qu'il ne faut pas faire

- Ne pas recalibrer σ, les seuils de densité ou `min_area` : on teste le routage seul.
- Ne pas conclure sur un seul terrain — Airelles sert à calibrer, les quatre servent à valider.
- Ne pas comparer sur des emprises différentes (hull clippé, toujours).
- Ne pas présenter un résultat partiel comme un succès : si Grimbosq se dégrade, c'est un échec
  quel que soit le gain ailleurs.
