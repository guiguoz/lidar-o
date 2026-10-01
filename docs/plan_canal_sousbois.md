# Plan — Canal de sous-bois

> **Statut : phase 0 en attente.** Plan jugé et réécrit par l'agent le 2026-10-01
> (version soumise par l'utilisateur conservée dans le commit de création).
>
> **Objectif** : ajouter au fond de décalque une information que le rendu actuel
> n'a pas — où se trouve la végétation basse.
>
> **Pas une couche ISOM.** Voir §0. **Pas un sauvetage de la piste close :**
> voir §0 bis.

---

## 0. Ce qu'on ne cherche PAS

**Le canal ne produira pas de classification 406 ou 409 — ni aucune classe ISOM.**

```
406 / 408   verts unis   — pénétrabilité ralentie / très ralentie
407 / 409   verts hachurés — mêmes pénétrabilités, bonne visibilité
```

Tous concernent la strate basse. Ce qui sépare une ronce d'une fougère de même
hauteur est le **rapport entre pénétrabilité et visibilité** — un symbole uni ne
promet rien sur la visibilité, un hachuré la promet.

> **Le LiDAR ne mesure pas cette différence.** Il voit une densité de retours,
> pas la nature de ce qui les produit. **Le cartographe tranchera au terrain**,
> comme il le fait déjà.

**Le canal ne modifiera aucune classe de production non plus** : sa sortie est
indicative jusqu'à la porte de phase 2, et même après, seulement sur planche
validée.

**Ce que le canal apporte** : montrer où regarder. Une nuance de plus dans le
fond, là où le rendu actuel laisse du blanc.

---

## 0 bis. Pourquoi ce n'est pas un sauvetage de la piste close

- **Porte 1 (2026-10-01, NON)** a clos le canal undergrowth C1–C4 : son objet
  était une *classification / un correctif*. Motif tuant : C3 (HAG (0 ; 1],
  σ 2 m, t = 1,0) couvre **76,3 % de fen3_410** = masque forestier ; nulle part
  « KP blanc + canal retrouve une structure cohérente ».
- **Objet ici plus étroit** : un signal *indicatif* dans le fond de décalque,
  pas une classe. Le livrable et ses portes ISOM ne changent pas.
- **La phase 0 teste directement le motif tuant** , sur son terrain exact :
  le discriminant est le témoin négatif *dans le blanc forestier* (zone C).
  Gate 1 ne l'avait mesuré que qualitativement, et sur fen3_410.
- **Précédent de veille** : Airelles (France) — lande praticable ≡ sous-bois en
  HAG [0,3 ; 3,0] (bilan_v0, §veille). La bande [0,2 ; 1,0] n'est pas prouvée
  immunisée ; c'est à la phase 0 de le dire.
- **Si la phase 0 conclut A ≈ C : plan CLOS définitif, R8 sans appel**, note de
  clôture dans `docs/bilan_v0.md`.

---

## 1. Phase 0 — Le signal existe-t-il ? *(une heure, et ça décide)*

**C'est la seule chose à faire avant tout développement.**

```
fen1_406 contient 45,9 % de végétation selon la carte FFCO
    dont 29 % de 406
    et le rendu actuel n'y produit RIEN   ← prémisse à revérifier ici même,
                                            par croisement FFCO ∩ rendu
```

> **Si le signal n'est pas dans les données, aucun canal ne le fera apparaître.**

### Les zones — toutes dans le même carreau que A si possible

Leçon OVL : des effets inter-tuiles existent ; un témoin pris dans un autre
carreau mesure aussi cela.

```
A   FFCO 406 ∩ rendu blanc          ← la cible : sous-bois connu, rien au rendu
B   FFCO 408/410 ∩ rendu vert       ← témoin positif : signal connu ET rendu
C   FFCO forestier praticable (blanc) ∩ rendu blanc
                                    ← témoin négatif DANS le blanc : LE discriminant
D   blanc de terrain ouvert         ← sanity : densité basse attendue ≈ 0
```

### La mesure

```
compter les retours HAG ∈ bande, dans chaque zone, pour TROIS bandes à la fois :
    [0,2 ; 1,0] m   [0,3 ; 1,5] m   [0,2 ; 2,0] m
rapporter : densité en pts/m² (médiane, p90) + distribution des HAG 0–2 m
mêmes sol / MNT que la production, entrées gelées
```

**Trois bandes, pas une** : cinq références donnent cinq bornes (§2) ; le verdict
de Gate 1 ne doit pas dépendre d'un choix arbitraire, et celui-ci non plus.

### Ce que le résultat décide

```
A ≈ C sur toutes les bandes
    → la strate basse n'isole pas le sous-bois DANS le blanc
    → PLAN CLOS (motif de Gate 1 reproduit sur son objet exact), R8 sans appel

A nettement > C (ratios rapportés par bande)
    → le signal existe là où le rendu laisse du blanc
    → phase 1

A vs B : rapporté pour information — si A ≈ B, le canal s'allumera aussi
    là où c'est déjà vert ; le contrôle de nouveauté (§4) arbitrera

D ≈ 0 : sanity. Sinon, bug de mesure, ne rien conclure.
```

> **Le second cas est plausible** : KP noie la strate basse dans une densité
> unique, puis le filtre médian à 16 efface ce qui est peu dense. Le signal peut
> survivre au comptage et mourir au lissage. Mais Gate 1 dit aussi le contraire
> possible : C3 = masque forestier. La phase 0 existe pour trancher, pas pour
> confirmer.

**⛔ STOP et rapporter avant la phase 1.** Rapport : `work/expe/sousbois/phase0.md`.

---

## 2. Phase 1 — Produire le canal

**Seulement si la phase 0 est concluante.**

### Le principe, repris de Cassini

```
KP        une densité unique → seuillage → filtre médian
          le sous-bois léger est noyé puis effacé

Cassini   comptage SÉPARÉ de la strate basse
          lissage à part
          seuillage à part
```

> Cassini n'est **pas le seul** de la famille étudiée à compter la strate basse
> à part — Terje ((0,3 ; 1,3]) et omapmaker ([0,2 ; 1,5[) le font aussi, avec
> d'autres bornes — mais c'est le design le plus proche de notre besoin : un
> canal indépendant, lissé et seuillé pour lui-même.

### Ce qu'il faut produire

```
comptage des retours de la bande retenue en phase 0, à 1 m de résolution
    → undergrowth_count.tif

lissage gaussien — σ EN MÈTRES, à déterminer sur le contraste A/C
    (leçon V0.7 : paramètres physiques d'abord ; le σ de Cassini vaut pour
     SA chaîne, sur SES strates, à SA résolution)

seuillage en points par m², défini SUR les distributions mesurées
    (ex. : marge au-dessus du p90 de la zone C) — unité physique,
    interprétable, contrairement à greenshades (thevalue sans dimension, V0.1)
```

> ⚠️ **Ne pas reprendre les valeurs de Cassini sans les avoir éprouvées.** Son
> seuil par défaut est documenté, mais sa chaîne diffère : strates différentes,
> lissage différent, résolution différente. **Point de départ à mesurer.**

### Bornes de la strate — instruites en phase 0

```
Cassini      low = HAG (0 ; 1]
Terje        low = (0,3 ; 1,3]
omapmaker    low = [0,2 ; 1,5[
Trier        bande unique 0,2 – 2,0
Lidar'O      0,3 – 3,0 dans sa chaîne actuelle
```

**Cinq références, cinq bornes différentes.** Les [0,2 ; 1,0] m proposés sont un
choix, pas une valeur établie — la sensibilité de la phase 0 arbitre.

---

## 3. Phase 2 — L'intégrer au fond

**Trois façons, à juger sur planche comme `medianboxsize2` :**

```
A   nuance supplémentaire dans vegetation.png
    → le sous-bois apparaît en vert très clair là où le rendu laisse du blanc

B   calque séparé, affichable indépendamment
    → le cartographe l'active quand il en a besoin

C   canal de diagnostic seulement
    → sorti en .tif, pas intégré au .omap
```

> **A modifie le fond que tu viens de valider.** À ne faire qu'après avoir vu
> sur planche que l'ajout améliore le décalque plutôt qu'il ne le charge.
> **Recommandation si le signal est réel mais ténu : B** — l'information existe,
> elle ne s'impose pas.

**Planche obligatoire** : fond actuel / fond avec canal / contour FFCO, sur les
trois fenêtres, à 1:10 000. Jugement cartographique, même rang que
`medianboxsize2`.

---

## 4. Le contrôle qui compte

```
le canal s'allume-t-il là où la FFCO voit du 406 et le rendu rien (zone A) ?
    → couverture de A = mesure primaire, c'est l'unique question positive

récidive : couverture de C par le canal
    → doit rester faible ; sinon masque forestier, Gate 1 bis, CLOS

nouveauté : recouvrement avec le 406/408/410 déjà rendu
    → si > 50 %, ce n'est pas une information nouvelle
```

> **Ne pas mesurer un gain de rappel global.** Le canal ne vise pas à mieux
> classer, mais à montrer ce qui est aujourd'hui invisible.

---

## 5. Ne pas toucher

```
lightgreentone (160) · medianboxsize (9) · medianboxsize2 (16) · greenshades
    → validés par jugement cartographique, ne pas rouvrir

le pipeline de production · config.yaml · les algorithmes cartographiques
```

**Le canal se développe en parallèle, dans `work/expe/sousbois/`** (gitignoré,
convention du repo — pas de dossier `experiments/`).

---

## ⛔ Portes

```
PHASE 0   le signal existe-t-il ? (A vs C, trois bandes)
          → STOP et rapporter · plan CLOS définitif si A ≈ C (R8 sans appel)

PHASE 1   produire le canal, mesurer sa couverture (A, C, nouveauté)
          → STOP et rapporter

PHASE 2   intégration, sur planche
          → jugement cartographique, comme medianboxsize2
```

**Aucun commit avant relecture. Aucune modification de production sans planche
validée. Verdicts aux deux journaux (`docs/expe_journal.md` +
`work/expe/JOURNAL.md`). Planche en `docs/images/` seulement au commit de
verdict (R2). Note de clôture dans `docs/bilan_v0.md` si CLOS.**
