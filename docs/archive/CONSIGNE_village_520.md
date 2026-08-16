# Consigne Claude Code — Zones habitées en 520 (vert olive)

> Fait suite au contrôle visuel du livrable unique `output/grimbosq.omap`.
> **Décision cartographique prise** : le village doit apparaître en vert olive (zone d'accès
> interdit), pas en blanc.

---

## Le changement

`zone_d_habitation` (BD TOPO) et `landuse=residential` (OSM) avaient été **sortis** du 520 lors
d'une passe précédente, au motif que la carte FFCO de référence n'utilise que 8,22 ha de zone
interdite contre 108 ha pour `zone_d_habitation` (facteur ×13).

Ce raisonnement était correct pour reproduire *cette* carte-là, mais le choix retenu est
différent : sur une carte **de base** destinée à être reprise par un cartographe, marquer les
zones habitées en 520 est le comportement prudent. Un blanc dit « forêt courable » là où le
coureur ne doit pas entrer ; retirer de l'olive au terrain est plus facile que de deviner ce
qui manque.

**À faire** : réintégrer `zone_d_habitation` et `landuse=residential` dans la production du 520
au sein de `build_fill_layers()`. `access=private` reste inclus.

Ordre de grandeur attendu : ~108 ha, soit 18 % de l'emprise, avant découpage par les routes.

---

## Précaution 1 — Interrompre le 520 sur les routes (norme ISOM)

La description ISOM du symbole 520, lisible dans le gabarit, précise :

> *The area shall be discontinued where a path or track goes through.*

Sans ça, l'olive forme un pavé uniforme qui masque le réseau de rues — 18 % de l'emprise en
aplat plein, ce qui dominera visuellement la carte.

**À faire** : soustraire de la zone 520 le buffer des routes, **avant** écriture.
Réutiliser le buffer déjà calculé pour le masque de végétation — ne pas en créer un second, et
ne pas modifier sa valeur (elle est calibrée).

Résultat attendu : un village olive traversé de couloirs blancs correspondant aux rues, ce qui
correspond à la lecture d'une carte de CO réelle.

## Précaution 2 — Vérifier que la végétation reste soustraite sous le 520

La mesure précédente donnait **0,000 ha de végétation sous le 520**, ce qui était correct.
Avec l'enveloppe élargie à 108 ha, il faut que ça le reste — sinon du vert réapparaîtra sous
l'olive, ou pire, par-dessus selon l'ordre de dessin.

**À faire** : reprendre la métrique « surface de végétation sous 520 » et vérifier qu'elle est
toujours nulle après le changement. Si elle ne l'est pas, soustraire la végétation sous les
polygones 520 avant écriture.

## Précaution 3 — Documenter le choix

Dans le README d'export (et dans le log de fin de run), ajouter une ligne :

> Les zones habitées (`zone_d_habitation` BD TOPO + `landuse=residential` OSM) sont marquées
> 520 « accès interdit » **par défaut**. C'est un choix prudent pour une carte de base : à
> valider et affiner au terrain. Pour référence, la carte FFCO de Grimbosq n'utilise que
> 8,22 ha de 520 (11 polygones ciblés sur des propriétés précises), contre ~108 ha ici.

Ce n'est pas un détail de forme : sans cette note, quelqu'un qui compare les deux cartes dans
six mois conclura à un bug.

---

## Contrôles

**Métriques à sortir :**
- Surface et nombre de polygones 520 avant / après découpage par les routes.
- Surface de végétation sous 520 (doit être 0).
- Part de l'emprise en 520 (%).

**Contrôle humain 🧑** — produire le fichier et s'arrêter :
1. Le village apparaît-il en olive sur toute son enveloppe ?
2. Les rues sont-elles lisibles à travers l'olive (découpage effectif) ?
3. Reste-t-il du vert sous ou sur l'olive ?
4. À l'échelle d'impression, l'olive domine-t-elle trop la carte, ou l'équilibre est-il tenable ?

Le point 4 est le seul qui peut remettre en cause la décision : si le rendu est écrasant malgré
le découpage par les routes, il faudra revoir — mais ne pas anticiper cette correction.

## Ce qu'il ne faut pas faire

- Ne pas modifier le buffer des routes (calibré pour le masque de végétation).
- Ne pas toucher au masque de végétation lui-même.
- Ne pas retirer `access=private` — il reste pertinent, même s'il ne produit que 0,64 ha
  (lacune OSM documentée).
- Ne pas supprimer le petit polygone 520 de 0,01 ha sans vérifier : il est sous le seuil de
  lisibilité (1 mm² à 1:10 000), mais c'est peut-être une vraie parcelle taguée.
