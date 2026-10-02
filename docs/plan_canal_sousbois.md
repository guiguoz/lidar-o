# Plan — Canal de sous-bois

> **Statut : passe antécédents (§0 ter) en cours de transmission, avant toute
> phase 0.** Plan jugé et réécrit par l'agent le 2026-10-01 (version soumise par
> l'utilisateur conservée dans le commit de création).
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

## 0 ter. Passe préalable — antécédents (consigne exécuteur, avant toute phase 0)

> **Passe documentaire et mesure ciblée préalable.** Objectif : déterminer si
> la phase 0 apporte une information réellement nouvelle, ou si les diagnostics
> déjà réalisés permettent déjà de conclure.
>
> **Aucune nouvelle expérimentation exploratoire.** Un seul calcul nouveau est
> autorisé (§0 ter.3.2), uniquement si le chiffre n'existe pas déjà.
>
> **Aucune modification de production. Aucun développement. Aucun commit avant
> relecture humaine.**
>
> **Passe exécutée le 2026-10-02 : ANTÉCÉDENTS INSUFFISANTS → la phase 0
> conserve son intérêt (cas B : densité 0,366 pt/m² non nulle en A).** Verdict
> et chiffres dans `docs/expe_journal.md`. Phase 0 ouverte sur go explicite,
> avec les contraintes ci-dessous intégrées à §1.

### 1. Gate 1 — reprendre précisément les résultats existants

Le plan ne cite que C3 (HAG (0 ; 1], σ 2 m, t = 1,0 → 76,3 % de fen3_410) :
insuffisant pour vérifier la portée de la Porte 1. Retrouver dans les journaux
et rapports existants les quatre candidats C1–C4 ; pour chacun, relever
exactement, **sans rien recalculer** :

```
identifiant · bande HAG · sigma · seuil · surface / pourcentage produit
fenêtre utilisée · résultat visuel / constat principal
raison du non-renvoi · date du test · verdict Porte 1
```

Point de départ connu (`docs/expe_journal.md`) : couvertures fen3_410 =
C1 38,5 % · C2 59,5 % · C3 76,3 % · C4 67,0 %. Pour C3, rechercher le même
indicateur sur les autres fenêtres si la mesure a déjà été faite.

### 2. Expérience 1.10 — contre-indice déjà disponible

Retrouver et documenter : AUC conditionnelle n≥3 — W1 [0,3 ; 1,5] = 0,5113 ·
WC [1,5 ; 3,0] = 0,5456 · W3 [0,3 ; 3,0] = 0,5461. Avec sa limite de portée :
elle mesure la séparation entre classes de végétation, **pas** la détection du
sous-bois dans le blanc du rendu. Indice défavorable supplémentaire (la bande
haute ne s'est pas révélée moins discriminante que la basse ; niveaux proches
du hasard), écho terrain dans la veille (Airelles : lande praticable ≡
sous-bois en HAG [0,3 ; 3,0]). **Ne pas en tirer une conclusion plus forte que
ce qu'elle mesure.**

### 3. fen1_406 — mesure ciblée susceptible de rendre la phase 0 inutile

**3.1 Chercher d'abord le résultat existant** — dans `diag_hag_classes.json` et
diagnostics associés : classe 2 = 0,80 % des points au-dessus de 0,2 m ;
classe 3 = 31,40 % au-dessus de 0,2 m. Insuffisant seul : il manque le nombre
absolu de retours, donc la densité en pts/m².

Chercher aussi, et c'est la recherche décisive : **toute comparaison déjà
mesurée, sur une bande basse, entre « FFCO 406 ∩ rendu blanc » et « forestier
blanc ∩ rendu blanc »** (ou équivalent A vs C). Si elle existe, la rapporter :
c'est le seul antécédent qui puisse rendre la phase 0 sans objet sur pièce.
Le constat visuel de Gate 1 (« nulle part KP blanc + canal retrouve une
structure cohérente », sur fen3_410) est cité verbatim avec sa limite : visuel,
une fenêtre, pas une comparaison A vs C mesurée.

**3.2 Si le chiffre de densité n'existe pas**, unique calcul autorisé, sur
zone A = FFCO 406 ∩ rendu blanc **dans** fen1_406 :

```
nombre de retours HAG ∈ [0,2 ; 1,0] m (toutes classes) · surface de A
    → densité en pts/m² rapportée à la surface de A, PAS à la fenêtre
      (la fenêtre entière en contexte : elle n'est végétale qu'à 45,9 %)
carreaux traversés par A (leçon OVL : effets inter-tuiles)
part des points de classe 2 (sol) dans la bande = plancher de bruit
si directement disponibles dans la même passe : nombre total de retours
    dans A · part des retours dans la bande · part des cellules de A
    contenant au moins un retour dans la bande
```

Ne pas lancer la phase 0. Aucun lissage, aucun seuillage, aucune nouvelle
campagne de fenêtres.

### 4. Ce que cette passe permet réellement de conclure

```
CAS A    retours [0,2 ; 1,0] = 0 dans A
         → aucune information dans cette bande sur cette cible
         → phase 0 sans objet POUR CETTE BANDE ; plan clos seulement si
           aucune autre bande disponible ne justifie une hypothèse distincte
           (1.10 ≈ hasard = indice défavorable, pas une absence)

CAS A bis  comparaison A vs C déjà mesurée trouvée en archive
         → phase 0 sans objet sur son objet même · rapporter et STOP

CAS B    densité non nulle
         → le signal physique existe dans A ; cela ne prouve PAS qu'il
           discrimine le sous-bois du blanc forestier
         → la phase 0 conserve son intérêt : elle doit encore mesurer A contre C

CAS C    densité très faible
         → NE PAS inventer de seuil de clôture
         → rapporter densité, nombre total, part de cellules occupées, et
           taille de cellule impliquant ≥ 5 pts/cellule (prior de faisabilité
           pour la phase 0 : rapporté, pas décidé) · puis arrêter
```

**La faible densité ne suffit pas à conclure « rien à détecter » sans critère
de détectabilité explicite.**

### 5. Synthèse demandée — trois questions et une conclusion

```
Gate 1     que produisaient réellement C1–C4 ? pourquoi la Porte 1 a-t-elle été NON ?
1.10       que montre réellement le résultat 1.10 ? quelle est sa limite de portée ?
fen1_406   quelle est la densité réelle de retours HAG [0,2 ; 1,0] m dans A ?
```

Puis une seule conclusion : **ANTÉCÉDENTS SUFFISANTS → phase 0 sans objet** ou
**ANTÉCÉDENTS INSUFFISANTS → phase 0 conserve son intérêt**. Décision justifiée
par les données, sans ajouter d'hypothèse nouvelle.

### 6. Où documenter — ⛔ STOP

Préparer uniquement `work/expe/sousbois/antecedents.md` (chiffres Gate 1 ;
résultat 1.10 ; mesure fen1_406 ; conclusion sur la nécessité de la phase 0).
Ne pas modifier `docs/plan_canal_sousbois.md` (référence normative, commit
`de29415`) ni `docs/bilan_v0.md` avant validation humaine ; et après, seulement
si la phase 0 devient réellement sans objet.

Après `antecedents.md` : **STOP.** Ne pas lancer la phase 0. Ne pas produire de
nouveau canal. Ne pas modifier la production. Ne pas optimiser seuil, sigma ou
bande. Ne pas committer avant relecture humaine.

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

### Contraintes issues des antécédents (2026-10-02) — à respecter en phase 0

```
emprise    tuile 0447_6888 manquante → zone A = moitié est de fen1_406
           (9,68 ha) ; zones B, C, D en x ≥ 448000

coutures   x=448000 EST une coupe : la bande de surdensité OVL (passes
           convergentes, ±~30 m) gonfle la strate basse exactement là
           → exclure de TOUTE zone le corridor M1∧M2 (overlap_map.tif),
             ou ±30 m à défaut ; rapporter les coutures traversant chaque zone

granularité  0,366 pt/m² en A = comptage clairsemé à 1 m (médiane cellule vide)
           → rapporter à DEUX granularités : 1 m (part de cellules occupées)
             et 4 m (médiane / p90 en pts/m² ; 16 m² garantit ≥5 pts/cellule
             en A à la densité mesurée)

décision   zone C = seule mesure décisive ; ratios par bande + distributions
           + parts de cellules occupées rapportés ; décision à la relecture,
           aucun seuil numérique préfixé
```

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
