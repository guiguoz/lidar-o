# Consigne Claude Code — Intensité LiDAR sur le 406 léger (v2)

> Remplace la v1, trop longue et trop optimiste.
>
> **Ce test est probablement une réfutation.** Il est lancé pour clore proprement la dernière
> dimension du signal accessible, pas parce qu'un gain est attendu. Lire la section « pronostic »
> avant de commencer.

---

## Pronostic — pourquoi l'échec est probable

H3 a mesuré sur Grimbosq un delta d'intensité de ~200 unités entre terrain découvert (médiane
741) et 406 détecté (525) — **le 406 a une intensité plus basse que le terrain ouvert**.

Or les 50,3 ha de 406 non détectés ont, par définition, moins de végétation que le 406 détecté
(c'est pourquoi HAG les rate). Leur intensité devrait donc se rapprocher de celle du blanc, pas
s'en éloigner. **Le mécanisme qui a fait le succès de H3 prédit l'échec de ce test.**

Ce n'est pas une raison de ne pas le faire : c'est la dernière dimension accessible du signal,
et une réfutation mesurée vaut mieux qu'une piste laissée ouverte. Mais il faut le lancer en
sachant que le résultat attendu est négatif, et ne pas chercher à sauver la piste si elle tombe.

**Contexte chiffré** : 28 % de recall class-specific sur le 406 ; 50,3 ha manqués hors masque ;
**AUC HAG = 0,487** entre ces 50,3 ha et le blanc FFCO — indiscernable. Dix leviers déjà réfutés.

---

## Étape 1 — Rasters

Passe PDAL sur la bande végétation, dalles Grimbosq déjà en cache :

```json
{ "pipeline": [
  { "type": "readers.copc", "filename": "<dalle>" },
  { "type": "filters.hag_nn" },
  { "type": "filters.range", "limits": "HeightAboveGround[0.3:3.0]" },
  { "type": "writers.gdal", "filename": "output/intensity_veg.tif",
    "output_type": "mean", "dimension": "Intensity", "resolution": 1.0 }
]}
```

Produire aussi `intensity_count.tif` (`output_type: count`) et `scanangle_veg.tif`
(`dimension: ScanAngleRank`, `mean`).

**Garde-fous** : même résolution, même emprise et même geotransform que `density_hag.tif` —
vérifier, ne pas supposer. Cellules à `intensity_count < 3` → NoData (une moyenne sur 1–2
retours est du bruit).

## Étape 2 — Contrôle de dépendance angulaire — VERROU

Avec ~150 retours/m² et ~5 lignes de vol en recouvrement, une séparation observée peut refléter
la géométrie d'acquisition. **Enterrer une piste pour un artefact serait la pire issue.**

- Corrélation `intensity_veg` × `scanangle_veg` sur l'emprise
- Variance inter-lignes de vol sur une même zone vs variance inter-classes FFCO

Repère : H3 avait mesuré r = 0,034 sur Grimbosq, donc le résultat attendu est favorable — mais
il doit être re-mesuré sur cette bande. Si la dépendance est forte, normaliser et le documenter.

## Étape 3 — Le test, et il est unique

Reproduire **exactement** le protocole qui a donné l'AUC de 0,487 sur HAG, en remplaçant HAG
par l'intensité. Une seule variable change.

Deux populations de pixels, sur le **hull FFCO clippé** :
- **A** : les 50,3 ha de FN_406 (FFCO dit 406, pipeline ne produit rien, hors masque)
- **B** : le blanc FFCO (hull, hors toute végétation cartographiée)

Sortir : n, médiane, p25, p75, histogrammes superposés, et **AUC Mann-Whitney**.

**Contrôle de cohérence obligatoire, dans le même run** : AUC entre 406 **détecté** et blanc
FFCO. H3 y a mesuré un delta de ~200 unités, donc cette AUC doit être nettement différente de
0,5. Si elle ne l'est pas, les populations sont mal construites — c'est une erreur de méthode,
pas un résultat.

### Lecture du résultat

**Pas de seuil arbitraire.** Le point de comparaison est HAG : **0,487**. La question n'est pas
« l'AUC dépasse-t-elle un chiffre rond », mais **l'intensité fait-elle nettement mieux que
HAG sur exactement ces populations**.

- **AUC proche de 0,5** (disons 0,45–0,55) → réfuté. Onzième réfutation, piste close, on
  documente et on s'arrête. **C'est le résultat attendu.**
- **AUC nettement au-dessus** → il y a une information que le pipeline n'exploite pas. Ne pas
  se précipiter : mesurer d'abord ce qu'un critère fondé dessus produirait comme **hectares
  correctement classés en plus, et comme faux positifs créés dans le blanc**. Un gain de recall
  qui coûte autant de FP n'est pas un gain (leçon T_408/T_410 : +3,4 points de recall,
  −0,4 ha en bilan réel).

## Étape 4 — Uniquement si l'étape 3 est nettement positive

Ne rien implémenter avant. Le seul usage à évaluer : **critère de second niveau** — là où HAG
est sous T_406 mais où l'intensité indique de la végétation, classer en 406.

Mesurer, en hectares et non en pourcentages : recall class-specific 406 (baseline 28 %),
faux positifs créés dans le blanc, effet sur la compacité (baseline 0,474).

*(La v1 proposait aussi un « canal combiné avec pondération à calibrer ». Retiré : trop vague
pour être actionnable, et ça réintroduirait un paramètre libre dans un projet qui vient de
passer des semaines à en éliminer.)*

---

## Livrables

- `docs/test_intensite.md` : contrôle angulaire, AUC mesurées, histogrammes, verdict
- Mise à jour de `docs/bilan_v0.md`, **que le résultat soit positif ou négatif**
- Rasters produits, conservés pour référence

## Ce qu'il ne faut pas faire

- **Ne pas sauter l'étape 2.**
- **Ne pas chercher à sauver la piste si l'AUC est proche de 0,5.** Dix réfutations convergent
  vers une conclusion — le proxy LiDAR ne distingue pas le sous-bois léger du terrain courable.
  Une onzième qui confirme n'est pas un échec, c'est une borne établie.
- Ne pas comparer sur des emprises différentes (hull clippé, toujours).
- Ne pas conclure sur des recalls non pondérés par les surfaces.
- Ne pas étendre aux terrains estoniens : intensité brute non comparable entre acquisitions
  (médianes ~30 contre ~700).

---

## Après ce test, quel qu'en soit le résultat

Le projet aura épuisé les dimensions accessibles du signal. La question qui restera n'est plus
« peut-on faire mieux » mais **« est-ce que ce qui existe sert »** — et elle ne se tranche pas
par une mesure interne.

Un test chronométré sur une zone (temps pour cartographier depuis zéro vs depuis la base
générée) est une mesure, pas un avis. C'est la seule qui n'a jamais été faite, et elle décide
de tout le reste.
