# Consigne Claude Code — Kuti : quatrième terrain, premier test « dans le domaine » hors France

> Fait suite à Kilemäed (portabilité technique validée, terrain classé hors domaine).
> **Objectif principal** : obtenir un **second terrain forestier fermé**, comparable à Grimbosq,
> pour que le futur critère de fiabilité n'apprenne pas simplement à reconnaître Grimbosq.

---

## Pourquoi Kuti

Le domaine de validité repose aujourd'hui sur trois terrains : **un dedans** (Grimbosq, feuillus
fermés) et **deux dehors** (Airelles, lande d'altitude ; Kilemäed, landes et marais).

Avec un seul terrain dans le domaine, tout critère de séparation serait dégénéré — n'importe
quel seuil isolant Grimbosq marcherait, sans qu'on sache s'il généralise.

Kuti est le candidat : **108 polygones `Forest`** dans sa carte de référence (contre 4 pour
Kilemäed), 1427 × `veg_406`, 1565 × `veg_408`, 295 × `veg_410`, 680 × `open_terrain`. C'est un
terrain lourd et boisé, avec une distribution équilibrée — le profil qui manque.

**Prédiction à poser avant de mesurer** : si le domaine de validité est bien « forêt tempérée à
couvert structuré » et non « Grimbosq en particulier », alors Kuti doit produire des écarts
comparables à Grimbosq (Δcov de quelques points, pas de facteur ×18) et **utiliser réellement le
410**, contrairement à Kilemäed où le cartographe n'en pose aucun.

Si Kuti échoue comme Kilemäed, l'hypothèse « forêt fermée = domaine valide » est fausse et il
faut la revoir.

---

## Étape 0 — Données et emprise

1. **Emprise Kuti** : relevée précédemment à X 598117–601925, Y 6436581–6440937 (L-EST97,
   EPSG:3301), soit ~3,8 × 4,4 km ≈ 1670 ha. **À vérifier contre le GPKG réel** — le fichier
   fait 22 Mo, nettement plus que Kilemäed (3,7 Mo), donc l'emprise est peut-être plus large.
   Lire les bounds du GPKG plutôt que de reprendre le chiffre de mémoire.

2. **Dalles LiDAR** : à télécharger sur le portail Maa-amet, repérage par le grid `epk2T.shp`
   comme pour Kilemäed. Une vingtaine de feuilles kilométriques attendues.
   Format `.laz` simple → `reader: readers.las`.

3. **Encodage du GPKG** : Kilemäed avait ses noms de tables en latin-1, ce qui cassait GDAL et
   geopandas. `Kuti.gpkg` n'a pas de caractère accentué dans son nom, mais **vérifier quand
   même** les noms de tables internes avant de supposer que ça passe. Le correctif H8
   (`_load_hull_from_sqlite` via OGR par index) devrait couvrir les deux cas.

## Étape 1 — Configuration

Dans `config.yaml`, section `terrains` :

```yaml
kuti:
  bbox: [<lu depuis le GPKG>]
  crs: EPSG:3301
  mapping: isom_en
  reader: readers.las
```

**Mapping** : compléter `isom_en.yaml` avec les entrées `skip` relevées à l'inventaire de Kuti —
`Building`, `Uncrossable body of water`, `OOB`, `Paved area`. Ne pas les laisser tomber dans un
symbole par défaut.

## Étape 2 — Géoréférencement

Créer `assets/georef_kuti.xml` sur le modèle de `georef_kilemaed.xml` :
- `projected_crs` : EPSG **3301**
- `ref_point` : point rond au centre de l'emprise
- `declination` : **recalculer**. C'est la convergence des méridiens, formule
  `(λ − 24°) × sin(φ)` avec λ la longitude du centre et φ sa latitude. Kuti est plus à l'ouest
  que Kilemäed (X 598000 contre 413000), donc la valeur **ne sera pas −1,27°**.
  Ne pas recopier celle de Kilemäed — c'était précisément le piège H7.

## Étape 3 — Run

```
python main.py kuti
```

Relief absent (Karttapullautin n'a pas tourné sur l'Estonie) → skip attendu.
BD TOPO absente → masque OSM seul.

**Noter toute nouvelle hypothèse française ou « grimbosquienne »** dans `docs/portabilite.md`,
comme pour Kilemäed. Kilemäed en a révélé deux (H3 relief, H7 déclinaison) ; un quatrième
terrain peut en révéler d'autres, notamment côté OSM et côté QA.

## Étape 4 — Mesure contre la référence — le cœur de l'exercice

Comparaison sur **hull de la carte de référence**, clippé — jamais sur la bbox du pipeline
(le facteur ×7 fantôme d'Airelles venait de là).

Sortir par classe :
- nombre de polygones, référence vs pipeline
- surface (ha) et couverture (% du hull)
- médiane des taches en mm² à 1:10 000
- % sous 1 mm²

**Points de comparaison établis** :

| terrain | statut | 406 | 408 | 410 |
|---|---|---|---|---|
| Grimbosq | **dans le domaine** | Δcov +1,6 pt, med 1,90 vs 5,17 | — | med 1,43 vs 1,39 ✓ |
| Kilemäed | hors domaine | ×18 | ×73 | **∞** (référence = 0) |
| Kuti | à mesurer | ? | ? | ? |

**Le chiffre décisif est le 410** : Kilemäed en a zéro dans sa référence, Kuti en a 295. Si le
pipeline s'en approche, le terrain est dans le domaine ; s'il produit un facteur à deux
chiffres, il n'y est pas.

## Étape 5 — Intersection avec la légende de référence

Reprendre le test qui a servi sur Airelles et Kilemäed : intersecter le 406 du pipeline avec la
légende de la carte de référence, et sortir la répartition.

Rappel des résultats précédents :
- Airelles : 53,7 % du 406 pipeline tombe en **terrain découvert** → hors domaine
- Kilemäed : 55,9 % en terrain ouvert → hors domaine
- Grimbosq : majorité sur des classes couvertes → dans le domaine

Kuti doit montrer une majorité sur classes couvertes (405/406/408/410) si l'hypothèse tient.

## Étape 6 — Contrôle humain 🧑

Produire le `.omap` et s'arrêter. Vérifier :
1. Ouverture, géoréférencement (les polygones tombent-ils sur le terrain réel ?)
2. Symboles corrects (86/89/93)
3. Banding : le rapport σ_lignes / σ_colonnes de `density_hag.tif` est-il comparable aux 1,86
   de Kilemäed, ou meilleur ? (même source Maa-amet, donc probablement présent)
4. Plausibilité générale à 1:10 000

---

## Livrables

- `output_kuti/kuti.omap`
- Tableau comparatif référence vs pipeline, par classe, sur hull
- Répartition du 406 dans la légende de référence
- `docs/portabilite.md` mis à jour
- **Verdict explicite** : Kuti est-il dans le domaine de validité, oui ou non, avec les chiffres
  qui le justifient. Le plan v3 §6.3 est à mettre à jour en conséquence.

## Ce qu'il ne faut pas faire

- **Ne rien recalibrer** — σ=1.0, `min_area` 100/100/75, seuils : validés sur Grimbosq contre le
  corpus FFCO. Les ajuster pour Kuti détruirait la comparabilité entre terrains, qui est
  précisément ce qu'on mesure.
- Ne pas recopier la déclinaison de Kilemäed (piège H7).
- Ne pas comparer sur des emprises différentes (piège du ×7 fantôme).
- Ne pas conclure avant l'étape 5 : la couverture seule ne suffit pas, c'est la répartition dans
  la légende qui dit si le pipeline classe au bon endroit.
