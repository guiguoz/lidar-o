# Consigne Claude Code — Kilemäed : premier terrain hors France (version minimale)

> Premier test du pipeline sur un terrain non français. Objectif : produire un `.omap` de
> Kilemäed avec `python main.py kilemaed`, et **découvrir les hypothèses françaises enfouies
> dans le code**.
>
> Ce n'est pas un chantier de production — c'est un test de généralité. Un échec propre à
> l'étape N est un résultat utile.

---

## Périmètre — version minimale assumée

**Inclus** : végétation (calibrée σ=1.0), masque OSM (OpenStreetMap est mondial), assemblage
`.omap`, QA contre la carte de référence estonienne.

**Exclu de cette itération** :
- **Relief** — Karttapullautin n'a jamais tourné sur l'Estonie. Le pipeline gère déjà l'absence
  (`out_kp/` absent → skip sans erreur). La carte n'aura pas de courbes.
- **Anthropique** — `fetch.py` cible la Géoplateforme française. L'Estonie a son propre service
  (Maa-amet), avec d'autres couches et d'autres noms. Pas de routes, pas de bâtiments, pas
  d'hydro.
- **Masque BD TOPO** — même raison. Seul le masque OSM s'appliquera.

**Conséquence à assumer** : la carte sera de la végétation sur fond blanc, plus les zones OSM.
C'est suffisant pour tester le pipeline ; ce n'est pas une carte utilisable.

---

## Étape 0 — Inventaire, avant tout code

1. **Données LiDAR** : les dalles Maa-amet de Kilemäed sont-elles toujours en cache local ?
   Combien, et sous quel format (`.laz` simple, pas COPC — `readers.las` requis) ?
2. **Rasters existants** : `density_hag.tif` et `classified.tif` de Kilemäed sont-ils encore
   là, ou faut-il relancer PDAL ?
3. **Carte de référence** : le GPKG estonien est-il accessible pour la QA, et sous quel nom ?
4. **Emprise** : X 411888–414255, Y 6481712–6484028 en **L-EST97 (EPSG:3301)**.

Si les rasters existent, `--skip-pdal` évite un run PDAL complet.

## Étape 1 — Configuration du terrain

Ajouter Kilemäed dans `config.yaml`, section `terrains` :

```yaml
kilemaed:
  bbox: [411888, 6481712, 414255, 6484028]
  crs: EPSG:3301          # L-EST97, pas Lambert 93
  mapping: isom_en        # convention ISOM anglaise, pas FFCO français
  reader: readers.las     # .laz simple, pas COPC
```

**Point d'attention** : si `config.yaml` ne prévoit pas de champ `crs` par terrain, c'est déjà
une hypothèse française à corriger — EPSG:2154 est probablement codé en dur quelque part.
Le signaler plutôt que de contourner.

## Étape 2 — Géoréférencement

Créer `assets/georef_kilemaed.xml`, sur le modèle de `georef_grimbosq.xml` :
- `projected_crs` : EPSG **3301**
- `ref_point` : un point rond dans l'emprise (ex. 413000 / 6483000)
- `scale` : 10000
- `declination` : la déclinaison magnétique en Estonie **n'est pas −2,48°** (valeur française).
  Elle est de l'ordre de +8 à +9° dans les pays baltes. Calculer ou chercher la valeur pour
  cette position, et la documenter. Ne pas recopier la valeur de Grimbosq.
- `geographic_crs` : coordonnées WGS84 correspondant au `ref_point`.

## Étape 3 — Lancer et **noter chaque échec**

```
python main.py kilemaed --skip-pdal
```

**L'objectif de cette étape n'est pas que ça marche du premier coup.** C'est de produire la
liste des points où le pipeline suppose la France. Candidats probables, à confirmer :

- EPSG:2154 codé en dur (conversion de coordonnées, clip, écriture `.omap`)
- `fetch.py` appelé inconditionnellement alors qu'il n'a pas de sens ici
- `find_gpkg()` cherchant un pattern `D0{dept}` inexistant
- Mapping FFCO français utilisé par défaut au lieu d'`isom_en`
- Chemins de fichiers en dur pointant vers Grimbosq
- QA cherchant `{terrain}.gpkg` avec les noms de classes français
  (`Végétation - course lente` vs `Vegetation: slow running`)

**Pour chaque échec** : noter l'étape, le message, et la cause. Corriger au minimum pour passer
à l'étape suivante — pas de refactoring de fond dans cette passe.

**Livrable de cette étape, aussi important que le `.omap`** : `docs/portabilite.md` listant les
hypothèses françaises trouvées, avec pour chacune si elle a été corrigée ou contournée.

## Étape 4 — Masque OSM

Le seul masque applicable. La requête Overpass fonctionne sur une bbox WGS84, donc reprojeter
depuis EPSG:3301 et non 2154 — vérifier que la reprojection n'est pas codée en dur.

**Test de couverture d'abord**, comme pour Grimbosq : compter les polygones `landuse` récupérés
avant d'intégrer. La couverture OSM estonienne est réputée bonne, mais ça se vérifie.

## Étape 5 — QA

`report_hull_metrics()` doit fonctionner avec la carte de référence estonienne, dont les noms de
symboles sont en anglais (`Vegetation: slow running`, etc.). Le mapping `isom_en.yaml` existe
déjà — vérifier que la QA l'utilise et ne suppose pas les noms français.

Rappel des cibles Kilemäed déjà mesurées : le pipeline y produisait 55,9 % du 406 en terrain
ouvert (contre 90,5 % sur Airelles), et 40,6 % de correspondance sur le 406 réel. Ces chiffres
peuvent servir de contrôle de non-régression.

## Étape 6 — Contrôle humain 🧑

Ouvrir le `.omap` dans OOM :
1. S'ouvre-t-il, et les polygones sont-ils au bon endroit ? (test réel du géoréférencement L-EST97)
2. Les symboles sont-ils les bons (86/89/93 pour la végétation) ?
3. L'échelle et l'orientation sont-elles cohérentes ?

---

## Critère de réussite

Ce n'est **pas** « la carte est belle » — elle ne le sera pas, sans relief ni routes.

C'est : **`python main.py kilemaed` produit un `.omap` géoréférencé et symbolisé correctement**,
et `docs/portabilite.md` liste ce qui a dû être corrigé pour y arriver.

Si le pipeline échoue à une étape et que la cause est identifiée et documentée, c'est un
résultat utile — pas un échec.

## Ce qu'il ne faut pas faire

- Ne pas modifier la calibration végétation (σ=1.0, min_area) : elle vaut pour les trois terrains.
- Ne pas écrire un `fetch_maaamet.py` dans cette passe — hors périmètre.
- Ne pas lancer Karttapullautin sur l'Estonie — hors périmètre.
- Ne pas recopier la déclinaison magnétique française.
- Ne pas contourner silencieusement une hypothèse française : la documenter.
