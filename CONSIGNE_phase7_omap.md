# Consigne Claude Code — Phase 7/8 : génération `.omap`

> Objectif : produire un fichier `.omap` unique, ouvrable dans OpenOrienteering Mapper,
> contenant la végétation vectorisée d'Ovector (σ=1.0) + le relief Karttapullautin (DXF)
> + l'anthropique BD TOPO, avec les symboles ISOM déjà affectés.
>
> **Toutes les informations de format ci-dessous ont été vérifiées sur des fichiers réels**
> (`ISOM_2017-2_10000.omap`, `sainte_anne.omap`). Ne pas les redécouvrir, les utiliser.

---

## 0. Faits établis sur le format `.omap`

**Ce n'est pas un ZIP.** C'est du XML brut, encodage UTF-8, racine `<map>` :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<map xmlns="http://openorienteering.org/apps/mapper/xml/v2" version="9">
```

Structure générale, dans l'ordre :
```
<map>
  <notes>
  <georeferencing>          ← échelle, CRS, point de référence, déclinaison
  <colors count="35">       ← 35 couleurs ISOM, à reprendre telles quelles du gabarit
  <symbols count="191" id="ISOM 2017-2">   ← définitions des symboles
  <parts count="1" current="0">
    <part name="..."><objects count="N">
      <object .../>          ← les objets à générer
    </objects></part>
  </parts>
  <templates>, <view>, <print>, <barrier>  ← optionnels / à reprendre du gabarit
</map>
```

### Stratégie retenue : gabarit + injection

Ne **pas** sérialiser les 191 symboles et 35 couleurs à la main. Partir de
`assets/ISOM_2017-2_10000.omap` (fourni), qui contient déjà tout le jeu ISOM 2017-2 et
0 objet utile, et **remplacer le contenu de `<objects>`**.

`sainte_anne.omap` est fourni comme **référence de géoréférencement** : c'est une carte du
secteur Grimbosq, déjà en Lambert 93 avec le bon point de référence. Copier son bloc
`<georeferencing>` dans le gabarit.

### Symboles : identifiants internes vérifiés

L'attribut `symbol="N"` d'un objet référence l'`id` interne du symbole, **pas** son code ISOM.
Correspondances relevées dans `ISOM_2017-2_10000.omap` :

| code ISOM | `id` interne | `type` | nom |
|---|---|---|---|
| 101 | 0 | 2 | Contour |
| 102 | 2 | 2 | Index contour |
| 111 | 17 | 1 | Small depression |
| 112 | 18 | 1 | Pit |
| 403 | 82 | 4 | Rough open land |
| **406** | **86** | 4 | Vegetation: slow running |
| 407 | 88 | 4 | Vegetation: slow running, good visibility |
| **408** | **89** | 4 | Vegetation: walk |
| 409 | 92 | 4 | Vegetation: walk, good visibility |
| **410** | **93** | 4 | Vegetation: fight |

`type` : 1 = point, 2 = ligne, 4 = surface, 8 = texte.

**Ne pas coder ces id en dur dans le script.** Les lire au démarrage en parsant le bloc
`<symbols>` du gabarit (`code` → `id`), et échouer explicitement si un code attendu est absent.
Un changement de gabarit ne doit pas casser silencieusement le mapping — c'est le même risque
que les calques DXF de Karttapullautin.

### Géoréférencement (bloc réel de `sainte_anne.omap`)

```xml
<georeferencing scale="10000" auxiliary_scale_factor="0.999966" declination="-2.48">
  <projected_crs id="EPSG">
    <spec language="PROJ.4">+init=epsg:2154</spec>
    <parameter>2154</parameter>
    <ref_point x="450000" y="6888000"/>
  </projected_crs>
  <geographic_crs id="Geographic coordinates">
    <spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>
    <ref_point_deg lat="49.04313972" lon="-0.42052612"/>
  </geographic_crs>
</georeferencing>
```

### Conversion de coordonnées — VÉRIFIÉE

Les coordonnées d'objets sont en **unités de 1/1000 mm sur la carte**, relatives au `ref_point`,
avec **l'axe Y inversé** (Y positif vers le bas).

```
unites_par_metre = 1_000_000 / echelle       # 100 à 1:10000, 66.667 à 1:15000
x_omap = round((X_L93 - ref_x) * unites_par_metre)
y_omap = round(-(Y_L93 - ref_y) * unites_par_metre)
```

**Validation faite** : le point omap `(-109310, -77510)` avec ref `(450000, 6888000)` donne
L93 `(448907, 6888775)` — dans l'emprise Grimbosq (X 448–450 km, Y 6886–6889 km). ✅

Écrire un test unitaire sur ce cas exact, plus un aller-retour L93 → omap → L93 à ±1 cm.

### Format des objets

```xml
<object type="1" symbol="86"><coords count="5">-109310 -77510;-109350 -77580; ... ;</coords>
<pattern rotation="0"><coord x="0" y="0"/></pattern></object>
```

- `type="1"` = objet de type chemin (ligne **et** surface — c'est le symbole qui décide).
- `coords` : points séparés par `;`, format `x y` ou `x y flag`, **point-virgule final inclus**.
- `count` doit être exact.
- `<pattern rotation="0">` : présent sur les objets surfaciques du gabarit — le reproduire.

**Flags relevés dans les fichiers réels** : `1, 2, 18, 32, 33, 34, 50`. Les deux qui comptent ici :

| flag | signification |
|---|---|
| 1 | départ de courbe de Bézier (les 2 points suivants sont des points de contrôle) |
| **2** | **point de fermeture** — dernier point d'un anneau extérieur fermé |
| **18** | **fin d'anneau intérieur (trou)** = 16 (hole point) + 2 (close) |

Pour la végétation : polygones en segments droits (pas de Bézier — le lissage a déjà eu lieu
en amont). Donc **aucun flag 1**. Anneau extérieur terminé par flag `2`, chaque anneau intérieur
terminé par flag `18`. Un objet avec trous = tous les anneaux concaténés dans un seul `<coords>`.

---

## 1. Module à écrire : `src/omap_writer.py`

API minimale :

```python
load_template(path) -> Template          # parse gabarit, extrait code→id, colors, symbols
write_omap(out_path, template, layers, georef) -> None
```

`layers` = liste de couches, chacune : nom, code ISOM, liste de géométries Shapely (en EPSG:2154).

Contraintes :
- Ne réécrire que `<georeferencing>` et le contenu de `<objects>` ; **recopier verbatim** les
  blocs `<colors>`, `<symbols>`, `<templates>`, `<print>`, `<barrier>` du gabarit.
- Mettre à jour `count` dans `<objects count="N">` **et** dans `<symbols count="...">` si touché.
- Sortie encodée UTF-8, fins de ligne cohérentes.

## 2. Module : `src/assemble.py` (remplace le stub)

Entrées :
- `output/vegetation.gpkg` — couches `veg_406`, `veg_408`, `veg_410` (déjà en EPSG:2154, σ=1.0)
- DXF Karttapullautin — calques confirmés : `contour`, `contour_index`, `contour_intermed`,
  `depression`, `depression_intermed`, `cliff2`, `cliff3`, `dotknoll`, `formline`
- GeoJSON BD TOPO (routes, bâtiments, hydro)

Traitements :
1. **Clip végétation** sur hydro et routes (buffer) — recoupe le chantier « masque zones
   humides » du plan v3 §6.4 : traiter les deux en une seule opération, avec la BD TOPO comme
   source (jamais les polygones de la carte de référence, ce serait circulaire).
2. Vérifier que **toutes** les couches sont en EPSG:2154 ; échouer sinon.
3. Ordre de dessin : végétation sous le relief, relief sous l'anthropique.
   Dans un `.omap`, l'ordre de dessin suit l'ordre des symboles, pas celui des objets —
   donc rien de particulier à faire tant que les symboles ISOM sont utilisés correctement.

## 3. Gate de validité (bloquant, avant écriture)

Refuser de produire le fichier si :
- une géométrie est invalide (`make_valid` en filet, mais logguer) ;
- une feature n'a pas de code ISOM mappable vers un `id` du gabarit ;
- une couche n'est pas en EPSG:2154 ;
- un anneau a moins de 3 points distincts.

## 4. Tests attendus

- **Conversion** : le cas vérifié ci-dessus, plus aller-retour ±1 cm, plus un test à 1:15000.
- **Golden minimal** : un carré de 100 m de côté en 406 → `.omap` avec 1 objet, symbol=86,
  5 coords, dernier flag `2`.
- **Trou** : un polygone avec un anneau intérieur → un seul objet, anneau intérieur terminé
  par flag `18`.
- **Mapping** : gabarit dont un code attendu est absent → échec explicite, pas de silence.
- **Relecture** : le fichier produit est du XML valide et se reparse (`ElementTree`).

## 5. Point de contrôle humain 🧑

Claude Code ne peut pas ouvrir OOM. Après génération, **s'arrêter** et demander une vérification :
le fichier s'ouvre, les polygones 406/408/410 sont au bon endroit et à la bonne couleur, le
relief est superposé, et l'échelle 1:10 000 donne un rendu lisible.

---

## Ordre de travail suggéré

1. `omap_writer.py` + tests de conversion — le cœur, testable sans OOM.
2. Golden test végétation seule (Grimbosq, `vegetation.gpkg` existant) → **premier `.omap`
   à ouvrir dans OOM**. C'est le jalon qui compte : végétation seule, mais réelle.
3. Ajout des DXF relief, puis de la BD TOPO.
4. Gate de validité et mention du domaine de fiabilité dans le README d'import
   (plan v3 §6.3 — le pipeline est calibré forêt tempérée, pas lande basse).
