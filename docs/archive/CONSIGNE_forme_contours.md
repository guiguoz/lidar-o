# Consigne Claude Code — Forme des contours : reprendre `remove_holes` avec les bonnes métriques

> **Changement de priorité, décidé par l'utilisateur.** Ce qui compte pour l'usage réel n'est
> pas la classe (corrigeable en deux clics dans OCAD : sélectionner la zone, changer le symbole)
> mais **la forme des zones de végétation**. Un contour faux doit être redessiné à la main —
> c'est là que le pipeline fait perdre ou gagner du temps.
>
> Conséquence : le problème sémantique jaune/vert passe au second plan. La géométrie devient le
> chantier principal.

---

## Ce que la mesure a établi

Comparaison pipeline vs carte FFCO, **406 sur hull commun** (Grimbosq) :

| indicateur | FFCO | Pipeline | verdict |
|---|---|---|---|
| **Polygones troués** | **1,1 %** (8 trous) | **35,1 %** (1328 trous) | ×32 |
| Surface des trous | 0,23 ha | **17,8 ha** (20 % de la surface brute) | — |
| Aire médiane d'un trou | 2,80 mm² | **0,43 mm²** | sous le seuil ISOM |
| **Compacité 4πA/P²** | **0,663** | **0,451** | écart de forme |
| Périmètre/√aire | 4,33 | 5,30 | contours plus découpés |
| Sommets / 100 m périmètre | 35,5 | **26,8** | pipeline **moins** dense |

**Test de remplissage** : boucher tous les trous fait passer la compacité de 0,451 à **0,580**
(cible 0,663). **Les trous expliquent environ 60 % de l'écart de forme.**

**Deux conclusions immédiates :**

1. La densité de sommets du pipeline est **plus faible** que la référence. DP et Chaikin font
   leur travail — **simplifier davantage n'est pas la piste**, ce serait même contre-productif.
2. Les trous du pipeline sont minuscules (0,43 mm² médian, soit sous le seuil de lisibilité
   ISOM de ~1 mm²) : ce sont des lucarnes invisibles à l'impression qui dentellent les contours
   sans porter d'information.

## Pourquoi `remove_holes` avait été jugé sans effet — et pourquoi c'était faux

Un sweep de `remove_holes` (30 → 3000) avait conclu « médiane inchangée, 2,02 → 2,06 mm² ».
C'était exact, mais **mesuré sur la médiane des taches**, qui ne bouge pas quand on bouche un
trou : la surface d'un polygone change à peine, mais **la forme de son contour change
radicalement**.

Le levier était bon, l'indicateur était faux.

---

## Étape 1 — Nouvelles métriques de forme (prérequis)

Ajouter à `src/qa.py`, sorties à chaque run et par classe :

- **compacité médiane** `4πA/P²` (1 = cercle, 0 = filandreux) — métrique principale
- **% de polygones comportant au moins un trou**
- **nombre total de trous** et leur **aire médiane en mm²** à l'échelle cible
- périmètre/√aire médian (redondant avec la compacité, mais plus lisible)

Cibles mesurées sur la référence Grimbosq : **compacité 0,66**, **< 2 % de polygones troués**,
trous conservés d'aire médiane ~2,8 mm².

Ces métriques doivent aussi apparaître dans les cibles FFCO du tableau QA, au même titre que
`med mm²` et `%<1mm²`.

## Étape 2 — Sweep `remove_holes`, relu correctement

Rejouer le sweep sur Grimbosq, en sortant **les métriques de l'étape 1** et non la médiane des
taches.

**Point de départ calibré, pas un chiffre rond** : les trous que le cartographe conserve font
2,80 mm² en médiane, soit **280 m² au sol** à 1:10 000. Ceux du pipeline font 0,43 mm² (43 m²).
Un seuil autour de **200–300 m²** éliminerait la quasi-totalité des lucarnes parasites tout en
gardant celles qui ont une existence cartographique.

Valeurs à tester : 50, 100, 200, 300, 500 m². Sortir pour chacune :
- compacité médiane, % de polygones troués, nombre de trous restants
- **surface totale par classe** (voir l'arbitrage ci-dessous)
- nombre de polygones (doit rester stable — boucher un trou ne fusionne rien)

## Étape 3 — Arbitrage forme / surface (à voir venir, pas à découvrir)

Boucher les trous **augmente la surface**. Aujourd'hui le 406 pipeline est à 70,8 ha contre
62,4 ha en référence, soit déjà +13 %. Ajouter 17,8 ha de trous bouchés donnerait ~88 ha, soit
**+41 %** — un écart bien plus important qu'aujourd'hui.

C'est un arbitrage réel entre forme et surface, et il faut le trancher explicitement :

- Un seuil intermédiaire (200–300 m²) ne bouche que les petits trous : gain de forme important,
  coût de surface modéré. **C'est probablement le bon compromis** — à vérifier sur les chiffres.
- Si la surface devient trop élevée, elle peut se compenser en remontant légèrement `t406` —
  mais **pas dans le même run** : une variable à la fois, comme toujours.

Sortir le couple (compacité, surface) pour chaque valeur du sweep permet de choisir en
connaissance de cause plutôt que d'optimiser une métrique au détriment de l'autre.

## Étape 4 — Ce qui restera après

Le remplissage total plafonne la compacité à 0,580 contre 0,663 en référence. **Environ 40 % de
l'écart de forme vient donc du découpage des contours extérieurs**, pas des trous.

Ne pas s'y attaquer dans cette passe. Mais noter que la piste « simplifier plus » est
**exclue par la mesure** (densité de sommets déjà plus faible que la référence). Ce qui reste
comme hypothèses, à instruire plus tard :
- les frontières suivent trop fidèlement le seuillage du raster (contours en isolignes de
  densité, là où un cartographe trace une limite franche)
- ou il manque une opération d'agrégation qui n'a pas encore été trouvée — quatre leviers déjà
  réfutés (`remove_holes` sur la médiane, fermeture morphologique, hystérésis, σ)

## Étape 5 — Contrôle humain 🧑

Produire un `.omap` avec la valeur retenue et le comparer visuellement à l'état actuel, sur la
même fenêtre. La question : **les zones de végétation ont-elles des contours plus francs, plus
proches de ce qu'un cartographe tracerait ?**

C'est le seul juge de ce chantier — les métriques disent où on est, pas si c'est bon.

---

## Ce qu'il ne faut pas faire

- **Ne pas simplifier davantage les contours** : la mesure montre que le pipeline a déjà moins
  de sommets par unité de périmètre que la référence.
- Ne pas toucher à σ, aux seuils de densité ou à `fusion_distance` : on teste `remove_holes`
  seul.
- Ne pas optimiser la compacité en ignorant la surface (étape 3).
- Ne pas conclure sur la médiane des taches — c'est l'indicateur qui avait fait rater ce levier.
