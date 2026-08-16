# Consigne Claude Code — OSM `landuse` et revue `omapmaker` (v2)

> Remplace la v1. Trois modifications : test de couverture préalable en verrou, liste de tags
> révisée, et une limite structurelle nouvellement identifiée (§1.6) qui dépasse ce volet.
>
> Fait suite au masque BD TOPO validé (`batiment` +15 m, ratio 79–89 % hors-bois,
> 406 : 105,8 → 96,4 ha).

---

## Contexte — ce qui reste non résolu

Le masque BD TOPO a nettoyé le village et les abords de routes. **Il reste les parcelles
agricoles** : blocs rectangulaires en damier au sud-ouest et au centre-droit de l'emprise
Grimbosq, bords rectilignes alignés sur des limites parcellaires. Vergers, cultures pérennes,
prairies — de la végétation basse réelle, vue correctement par le LiDAR, mais qu'ISOM code en
jaune (401/403) et non en vert.

**La BD TOPO 3-5 ne permet pas de les identifier.** Vérifié sur le GPKG départemental :
`zone_de_vegetation` ne contient que des types positifs (Bois 15, Haie 40, Forêt fermée 12,
Peupleraie 1, Lande 1). Ni Culture, ni Verger, ni Vigne.

**OpenStreetMap les a** — c'est ce qu'utilise OpenOrienteeringMap (`github.com/cadnant/oomap`,
maintenu ; `oobrien/oomap`, original) pour poser du jaune sur les champs. Pas du cadastre,
contrairement à ce qu'on pourrait croire : les tags `landuse`.

---

## VOLET 1 — Masque OSM `landuse`

### 1.0 — Test de couverture — VERROU, avant tout code

**La couverture `landuse` d'OSM en France est très inégale** : excellente là où un mappeur actif
est passé, absente ailleurs. L'affirmation « OSM est bien à jour en zone rurale » est plausible
mais non vérifiée. Ce test la tranche en cinq minutes.

1. Requête Overpass sur la bbox Grimbosq (`448000, 6886000, 450001, 6889001` en EPSG:2154 →
   reprojeter en WGS84, Overpass ne travaille qu'en géographique).
2. Compter les polygones par valeur de `landuse`, et leur surface totale.
3. **Croiser avec les blocs en damier identifiés visuellement** (sud-ouest et centre-droit) :
   sont-ils couverts par des polygones OSM, ou non ?

**Critère de poursuite** : si les blocs en damier ne sont pas tagués, ce volet ne les retirera
pas — dire lequel des deux cas, et s'arrêter. Ce serait une information utile, pas un échec :
le repli est le RPG (Registre Parcellaire Graphique, parcelles déclarées PAC), déjà identifié
comme piste hors périmètre immédiat.

### 1.1 — Tags à récupérer

Soustraction ciblée uniquement — là où on sait que ce n'est **pas** de la forêt :

| tag | ce que c'est | statut |
|---|---|---|
| `landuse=farmland` | culture | inclure |
| `landuse=orchard` | verger | inclure |
| `landuse=vineyard` | vigne | inclure |
| `landuse=allotments` | jardins familiaux | inclure |
| `landuse=farmyard` | cour de ferme | inclure |
| `landuse=residential` | zone résidentielle | inclure (complète BD TOPO) |
| `landuse=meadow` | prairie | **inclure, mais mesurer son effet séparément** |
| `landuse=grass` | herbe | **exclure** — tag trop générique (pelouses urbaines, zones herbeuses quelconques) |

**Sur `meadow`** : une prairie permanente peut porter des ronces et des refus que le LiDAR voit
à juste titre. Mais en ISOM une prairie est **jaune** quelle que soit sa végétation basse —
c'est exactement le cas Airelles (végétation basse réelle, praticable, codée jaune). Retirer le
vert y est donc cartographiquement correct. À inclure, mais avec sa surface retirée mesurée à
part, pour pouvoir le sortir s'il mord sur des zones forestières.

**Ne PAS récupérer `landuse=forest` ni `natural=wood` comme masque positif.** Ce serait faire
d'OSM l'arbitre de ce qui est forêt, alors que l'apport du LiDAR est précisément de voir ce
qu'OSM ne voit pas (sous-bois, régénération, trouées). Même raisonnement que pour
`zone_de_vegetation` BD TOPO : filtre par soustraction ciblée, jamais intersection.

### 1.2 — Intégration

- Quatrième source dans `build_mask()`, même interface que les masques existants :
  union des polygones → `difference()` sur 406/408/410.
- **Cache local** du résultat Overpass, clé = (bbox, date). API publique et rate-limitée :
  ne jamais la solliciter à chaque run.
- **Tracer le millésime** : date de récupération dans `run_metadata.json`, à côté du millésime
  BD TOPO (`2026-03-15`). OSM est vivant, une parcelle retaguée change le résultat.
- **Échec explicite** si Overpass ne répond pas — ne pas produire silencieusement une carte
  sans masque OSM en croyant l'avoir appliqué. C'est le quatrième garde-fou de ce type
  (tuiles, fraîcheur, config_snapshot).

### 1.3 — Validation chiffrée

Reprendre l'indicateur qui a validé le masque bâtiment : **proportion de végétation retirée
hors-bois vs en bois** (référence : `zone_de_vegetation` BD TOPO).

Historique de calibration, à titre de repère :
- `zone_d_habitation` +20 m : 43 % hors-bois → **rejeté** (mordait la lisière)
- `batiment` +15 m : 79–89 % hors-bois → **retenu**
- Cible OSM : **> 75 % hors-bois**

Sortir aussi, par classe : surface retirée, nombre de polygones, et **médiane des taches en mm²
à 1:10 000** (le masque fragmente : 1076 → 1607 objets sur le 406 lors de la passe précédente,
médiane 2,01 → 1,90 mm²). Si la médiane passe sous 1,5 mm², le gain de propreté se paie en
lisibilité.

### 1.4 — Contrôle humain 🧑

Rendu avant/après de la zone sud-ouest (blocs en damier). Les parcelles disparaissent-elles,
la forêt adjacente reste-t-elle intacte ?

### 1.5 — Limite à documenter

Couverture OSM inégale (cf. 1.0). Si le test de couverture est positif, noter quand même que
le résultat dépend d'une source contributive dont la fraîcheur n'est pas garantie.

### 1.6 — Limite structurelle identifiée : le masque produit du blanc, pas du jaune

**Point nouveau, qui dépasse ce volet et concerne tous les masques déjà en place.**

Aujourd'hui, toute zone masquée devient **blanche**. Or en ISOM le blanc signifie « forêt
courable » — l'inverse d'un champ ou d'un jardin. Les cultures retirées devraient devenir 401
(terrain découvert) ou 403 (terrain découvert rugueux) ; les jardins autour du village aussi.

Le masque a déjà la donnée qu'il faut : les polygones `landuse` OSM et `zone_d_habitation`
BD TOPO **sont exactement les géométries** qui permettraient de poser le bon symbole. Il ne
s'en sert que pour soustraire.

**Ne pas implémenter dans ce volet** — c'est un chantier distinct (ajout de classes ISOM en
sortie, pas seulement retrait). À inscrire au plan v3 comme chantier suivant, avec la remarque
que le coût marginal est faible : les géométries sont déjà chargées.

---

## VOLET 2 — Revue de `omapmaker` (documentaire, aucune modification de code)

`github.com/yvind/omapmaker` — Rust, génère des `.omap` directement depuis du LiDAR. Le projet
le plus proche du nôtre. **Objectif : lire, comparer, recommander. Pas de portage.**

### 2.1 Déclinaison magnétique calculée (fort intérêt)

Notre `.omap` porte `declination="-2.48"`, valeur reprise de `sainte_anne.omap` et codée en
dur. `omapmaker` la calcule via le **modèle magnétique mondial**, d'après la date de création et
la position. La déclinaison dérive de plusieurs dixièmes de degré par décennie — sur une carte
de compétition, l'alignement des lignes nord compte.

À instruire : quelle bibliothèque Python (`pygeomag` ou équivalent), quel coût d'intégration,
et **de combien la valeur calculée pour Grimbosq aujourd'hui diffère de −2,48**.

### 2.2 Facteur d'échelle auxiliaire (intérêt moyen)

Notre `auxiliary_scale_factor="0.999966"` vient aussi de `sainte_anne.omap`. `omapmaker` le
calcule depuis l'altitude du centre de carte. Négligeable à 100 m, pas en montagne — donc
pertinent pour Airelles (Pyrénées) plus que pour Grimbosq.

### 2.3 Filtrage par taille minimale selon l'échelle (à comparer)

`omapmaker` filtre selon l'échelle cible (1:10 000 / 1:15 000). Nous avons calibré `min_area`
empiriquement contre le corpus FFCO (100/100/75 m², cibles atteintes à 0,01 mm² près sur le
410). **Comparer les approches** : la sienne est-elle normative (seuils ISOM) ou empirique ?
Convergence = validation croisée utile. Divergence = comprendre pourquoi **avant** de toucher
à nos valeurs, qui touchent les cibles mesurées.

### 2.4 Sortie Bézier (évaluer, ne pas adopter)

Nos contours sont en segments droits. Les Béziers donnent un rendu plus lisse, mais notre
lissage est déjà fait en amont et le plan v3 interdit de retoucher les courbes Karttapullautin.
Ne pas adopter sans mesurer — risque de dégrader un rendu validé.

### Ce qu'il ne faut PAS reprendre

- Son moteur de contours et de végétation : nos paramètres sont calibrés sur trois terrains
  contre corpus FFCO, les siens sur d'autres données.
- Son GUI : hors périmètre v1.
- Sa gestion des falaises : nous avons écarté `cliff2`/`cliff3` sur constat mesuré (745 traits
  de 2,9 m non connectés).

### Livrable

`docs/revue_omapmaker.md` : pour chacun des quatre points, ce qu'il fait, ce que nous faisons,
recommandation (adopter / adapter / ignorer) avec justification. **Aucune modification du code.**

---

## Ordre d'exécution

1. §1.0 test de couverture — verrou.
2. Volet 1 si le test est positif, avec validation chiffrée et contrôle visuel.
3. Volet 2 en revue documentaire.
4. §1.6 (blanc → jaune) inscrit au plan v3 comme chantier suivant, non implémenté ici.

## Rappels de méthode

- Une variable par run, mesure avant/après.
- Toute comparaison sur emprise commune clippée (le ×7 fantôme est venu d'un dénominateur).
- Distinguer fait vérifiable et interprétation causale.
- Poser la prédiction avant de mesurer.
- Un échec propre vaut une confirmation — si OSM ne tague pas Grimbosq, le dire.
