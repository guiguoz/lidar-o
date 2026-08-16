# Consigne Claude Code — Suites du test Kilemäed

> Le pipeline a produit `output_kilemaed/kilemaed.omap` sur un terrain estonien. Trois problèmes
> sont apparus, de gravité croissante. Cette consigne les traite dans l'ordre — les deux premiers
> sont des corrections, le troisième est un constat à documenter.

---

## Résultat du test, chiffré

Comparaison avec la carte de référence `Kilemäed.gpkg` (couche `_areas`) :

| classe | référence | pipeline | écart |
|---|---|---|---|
| 406 Vegetation: slow running | 169 poly | 1414 | ×8 |
| 408 Vegetation: walk | 35 poly | 3997 | ×114 |
| 410 Vegetation: fight | **0 poly** | 3663 | ∞ |

**Ce que le cartographe utilise à la place** : `Rough open land` (42), `Rough open land with
scattered trees` (70), `Rough open land with scattered bushes` (17) — soit 129 polygones de
**terrain découvert jaune** — plus `Indistinct marsh` (57) et `Marsh` (22) en bleu.

Autrement dit : ce que le pipeline classe en végétation dense, le cartographe le code en terrain
ouvert praticable et en zones humides. C'est le diagnostic Airelles sur un autre terrain —
le LiDAR voit de la matière végétale basse, ISOM la code en jaune parce qu'elle est praticable.

---

## Correction 1 — Filtre d'emprise sur TOUTES les familles (bug actif)

Le garde-fou ajouté pour H3 (relief hors emprise) n'a été appliqué qu'au relief. **La végétation
déborde massivement** :

- bbox déclarée dans `config.yaml` : X 411888–414255, Y 6481712–6484028 → **550 ha**
- emprise réelle des objets produits : X 411000–415000, Y 6481000–6485000 → **1600 ha**

Le pipeline calcule et livre trois fois la surface demandée. Sur Grimbosq le problème n'était pas
visible parce que la bbox coïncidait avec l'emprise des dalles.

**À faire** : appliquer le clip bbox dans l'assemblage général, pour **toutes** les familles
(végétation, fill layers, relief, anthropique), pas dans chaque `build_*_layers()` séparément.
Un seul point de passage, avec un log du nombre de géométries écartées par famille.

C'est le cinquième garde-fou de cette famille (tuiles, fraîcheur, config_snapshot, clip OSM,
emprise relief) — il devrait être le dernier de ce type si le clip est centralisé.

## Correction 2 — Encodage du GPKG de référence

`Kilemäed.gpkg` a ses noms de tables encodés en **latin-1** (`Kilem\xe4ed_areas`) au lieu
d'UTF-8. GDAL, pyogrio et geopandas échouent tous à l'ouvrir — `UnicodeDecodeError`.

**À faire** : dans `qa.py` (et partout où une carte de référence est chargée), détecter ce cas
et le traiter — soit par un fallback de lecture, soit par une erreur explicite indiquant qu'il
faut ré-exporter le fichier depuis OOM en UTF-8.

**Ne pas laisser échouer silencieusement** : si la QA ne peut pas charger la référence, elle
doit le dire, pas afficher un tableau sans comparaison qui ressemble à un tableau normal.

## Correction 3 — Artefact de bandes verticales

Le rendu montre des stries verticales régulières, surtout à droite et en bas de l'emprise. Ce
n'est pas de la végétation : c'est un artefact de raster, probablement lié aux lignes de vol
LiDAR ou au rééchantillonnage.

**À instruire** (pas forcément à corriger dans cette passe) : regarder `density_hag.tif` de
Kilemäed directement — les bandes y sont-elles déjà présentes, ou apparaissent-elles à la
classification ? La densité Maa-amet (3,77 pts/m²) est bien plus faible que l'IGN, ce qui rend
le pipeline plus sensible aux variations de recouvrement entre lignes de vol.

---

## Constat à documenter — le domaine de validité se confirme

**Ne pas tenter de recalibrer Kilemäed.** Le problème n'est pas la taille des taches ni les
seuils : c'est que le pipeline produit du vert là où la convention cartographique demande du
jaune et du bleu. Aucun réglage de `min_area` ou de `sigma` ne transformera un 410 en
`Rough open land`.

**À écrire dans `PLAN_execution_v3.md` §6.3 (domaine de validité)** :

| Terrain | Profil | Verdict |
|---|---|---|
| Grimbosq (FR) | Feuillus, couvert fermé | **Fiable** — Δcov +1,6 pt |
| Airelles (FR) | Lande d'altitude | **Hors portée** — signal absent |
| Kilemäed (EE) | Landes, marais, forêt claire | **Hors portée** — le cartographe code en jaune/bleu ce que le LiDAR voit en vert |

Et la conclusion transversale : **le pipeline est portable techniquement, pas
cartographiquement.** Il tourne sur un terrain étranger, produit un `.omap` valide, dans le bon
CRS. Mais sa calibration vaut pour la forêt tempérée à couvert structuré, et les conventions
ISOM appliquées à d'autres milieux (landes, marais) divergent trop.

C'est un résultat, pas un échec : il borne ce que l'outil peut faire, et c'est une information
que le livrable doit annoncer.

## Piste ouverte, non traitée ici

`Indistinct marsh` (57) + `Marsh` (22) sur la référence confirment le **troisième mode de
sur-détection** identifié au plan v3 §6.4 (zones humides). Sur ce terrain il est massif. La
source de masque reste à trouver — la BD TOPO 3-5 n'a pas de `zone_humide`, et l'équivalent
estonien n'a pas été cherché. OSM a `natural=wetland`, jamais testé.

À noter comme piste, pas à implémenter dans cette passe.

---

## Ordre d'exécution

1. Correction 1 (clip bbox centralisé) — bug actif, à corriger avant tout.
2. Correction 2 (encodage QA) — bloque toute mesure sur ce terrain.
3. Correction 3 (bandes) — diagnostic seulement, pas de correctif obligatoire.
4. Mise à jour du plan v3 §6.3.

## Ce qu'il ne faut pas faire

- Ne pas recalibrer `min_area`, `sigma` ou les seuils pour Kilemäed — le problème est ailleurs.
- Ne pas appliquer le clip dans chaque `build_*_layers()` : un seul point centralisé.
- Ne pas implémenter le masque zones humides dans cette passe.
