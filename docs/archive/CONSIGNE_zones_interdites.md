# Consigne Claude Code — Du masque au symbole : zones interdites et terrain découvert

> Fait suite au masque OSM validé (§1.3 atteint, §1.4 concluant : les blocs rectangulaires
> restants sont des parcelles forestières, pas des cultures — 0 % de recouvrement avec les
> polygones `farmland`, rien à corriger de ce côté).
>
> Traite la limite structurelle identifiée en §1.6 de la consigne précédente.

---

## Le problème

Aujourd'hui, `build_mask()` **soustrait** : toute zone masquée devient blanche.

Or en ISOM, le blanc signifie **« forêt courable »**. On dit donc au coureur qu'il peut traverser
librement là où se trouvent en réalité des jardins, des propriétés privées et des cultures.
C'est l'inverse de l'information utile, et c'est visible sur le rendu du village : les jardins
retirés forment des zones blanches au milieu du bâti.

Une carte de CO code ces zones :
- **520 — zone d'accès interdit** (vert olive) pour les propriétés privées et le bâti
- **401 / 403 — terrain découvert** (jaune) pour les cultures et prairies

C'est ce que fait OpenOrienteeringMap avec les mêmes données OSM.

## Le principe du changement

Le masque a **déjà** toutes les géométries nécessaires — il ne s'en sert que pour soustraire.
Il faut qu'il **produise aussi des polygones** dans de nouvelles classes. Le writer sait déjà
écrire des surfaces (végétation), donc le coût marginal est faible.

---

## Étape 1 — Identifiants de symboles (avant tout code)

**Lire les identifiants réels dans `assets/ISOM_2017-2_10000.omap`.** Ne pas se fier à une
liste de mémoire : ce projet s'est fait piéger deux fois — `406.1` au lieu de `406` (symboles à
bandes au lieu d'aplats), et `106` supposé « dépression » alors que c'est « Ruined earth wall ».

Codes à résoudre : **520**, **401**, **403**, et vérifier **521** (bâtiment, déjà utilisé).

Extraire le mapping `code → id` comme pour la végétation, en échouant explicitement si un code
attendu est absent du gabarit.

## Étape 2 — Mapping source → symbole

| source | tag / couche | ISOM | rendu |
|---|---|---|---|
| BD TOPO | `zone_d_habitation` | 520 | olive |
| OSM | `landuse=residential` | 520 | olive |
| OSM | `access=private` | 520 | olive |
| OSM | `landuse=farmland` | 401 ou 403 | jaune |
| OSM | `landuse=orchard`, `vineyard` | 401 ou 403 | jaune |
| OSM | `landuse=meadow` | 401 ou 403 | jaune |
| BD TOPO | `batiment` | 521 | déjà en place, ne pas dupliquer |

**`access=private` n'est pas encore récupéré** — c'est un tag nouveau à ajouter à la requête
Overpass. C'est précisément ce qu'OOMap rend en vert olive, et c'est structurant en CO : le
coureur doit savoir où il ne peut pas entrer.

**Trancher 401 vs 403** en regardant les noms exacts dans le gabarit : 401 est le terrain
découvert franc, 403 le terrain découvert rugueux (avec végétation basse gênante). Pour des
cultures, 401 est probablement le bon choix ; à confirmer sur les intitulés réels.

## Étape 3 — Production des polygones

- Les polygones 520 et 401/403 sont écrits dans le même `.omap`, en plus des couches existantes.
- **Le buffer bâtiment de 15 m reste utilisé pour la soustraction de végétation** (calibration
  validée, ratio 79–89 % hors-bois). Mais pour la production du 520, utiliser la géométrie
  **sans buffer** — un buffer de 15 m autour de chaque maison produirait des zones interdites
  qui débordent sur la voirie et la forêt.
  → Deux usages distincts de la même donnée, à ne pas confondre.
- Fusionner les géométries qui se recouvrent avant écriture (`unary_union` par classe), sinon
  `zone_d_habitation` et `landuse=residential` produiront des polygones superposés.

## Étape 4 — Ordre de dessin

Dans un `.omap`, l'ordre de dessin suit **l'ordre des symboles dans le gabarit**, pas celui des
objets. Le 520 devrait donc se dessiner après les 40x et couvrir la végétation résiduelle.

**À vérifier au rendu** : si des zones vertes restent visibles sous l'olive, c'est que l'ordre
ne joue pas comme prévu, et il faudra soustraire la végétation sous les zones 520 avant
écriture. Ne pas anticiper cette correction — la faire seulement si le contrôle visuel la
justifie.

## Étape 5 — Contrôle humain 🧑

Produire le fichier et s'arrêter. Points à vérifier :

1. Les jardins et le bâti du village apparaissent-ils en **olive**, et non plus en blanc ?
2. L'olive couvre-t-il bien la végétation résiduelle, ou reste-t-il du vert dessous ?
3. Les cultures au sud-ouest apparaissent-elles en **jaune** ?
4. La forêt reste-t-elle intacte — l'olive ne déborde-t-il pas en lisière ?
5. La carte est-elle plus lisible qu'avant, ou l'ajout de deux couleurs la charge-t-il ?

---

## Métriques à sortir

- Surface et nombre de polygones produits par classe (520, 401/403).
- Surface de végétation désormais **couverte** par du 520 (indicateur que le blanc a disparu).
- Confirmation que la surface de végétation elle-même n'a pas changé (le masque de soustraction
  n'est pas modifié par cette consigne).

## Ce qu'il ne faut pas faire

- Ne pas modifier le masque de soustraction de végétation — il est calibré et validé.
- Ne pas coder les identifiants de symboles en dur sans les avoir lus dans le gabarit.
- Ne pas appliquer le buffer de 15 m à la production du 520 (cf. §3).
- Ne pas anticiper la correction d'ordre de dessin avant le contrôle visuel.
