# Journal des expériences — verdicts

> Ce document centralise les verdicts des expériences conduites après la clôture du Bilan V0.
> Chaque entrée résume la question posée, le protocole de la porte, et le verdict.
> Les détails complets sont dans `work/expe/JOURNAL.md`.

---

## 2026-10-01 — Plan undergrowth Phase 1 (Porte 1)

**Question posée :** Le comptage de points LiDAR dans la strate basse (0–1,3 m),
après lissage Gaussien (σ=2 m) et seuillage, peut-il constituer un canal de détection
du sous-bois (408/410) indépendant du signal KP actuel ?

**Protocole de la porte :** Jugement humain sur une planche 6 panneaux
(KP actuel / C1 / C2 / C3 / C4 / FFCO) sur la fenêtre O1 = fen3_410 (449170, 6886989,
449670, 6887489), 500×500 m, choisi pour maximiser la présence FFCO 408 (26 % de la fenêtre).

**Candidats testés :**

| Candidat | Strate | σ (m) | Seuil (pts/m²) | Couverture |
|----------|--------|--------|-----------------|------------|
| C1 | > 0,3 m et ≤ 1,0 m | 2,0 | 1,0 | 38,5 % |
| C2 | > 0,3 m et ≤ 1,0 m | 2,0 | 0,5 | 59,5 % |
| C3 | > 0 m et ≤ 1,0 m   | 2,0 | 1,0 | 76,3 % |
| C4 | > 0,3 m et ≤ 1,3 m | 2,0 | 1,0 | 67,0 % |

**Verdict : NON**

Les couvertures (38–76 %) sont trop élevées pour constituer un canal undergrowth :
le signal strate basse est présent partout sous couvert forestier et ne discrimine pas
les zones de végétation dense (408/410) de la végétation légère (406) ou de l'absence
de sous-bois. La Porte 1 ferme la piste.

**Conséquences :**
- Phases 2 et 3 non lancées.
- C1–C4 archivés comme expériences négatives.
- Aucune modification de production.
- Prochaine étape : définir une Porte 2 sur un problème différent du raster actuel
  (géométrie, lisibilité, autre canal).

---

## 2026-10-02 — Canal de sous-bois indicatif (Phase 0)

**Question posée :** Le signal LiDAR dans les bandes basses [0,2–1,0 m], [0,3–1,5 m],
[0,2–2,0 m] est-il spécifique des zones FFCO 406 actuellement blanches dans le rendu KP,
au point de constituer un canal indicatif utilisable par le cartographe ?

**Antécédents convergents :**

Avant la Phase 0, trois résultats existants constituaient des indices défavorables :
1. **Gate 1 — C1–C4 :** masques strate basse couvrant 38–76 % d'une fenêtre forestière
   mixte — signal trop diffus. Indice défavorable, mais porte différente (couverture globale,
   pas contraste A/C).
2. **Exp. 1.10 :** AUC conditionnelle W1 [0,3–1,5 m] = 0,5113 contre WC [1,5–3,0 m] = 0,5456
   — la bande basse ne montre pas de pouvoir discriminant supplémentaire entre classes FFCO.
3. **Diagnostic HAG fen1_406 :** signal non nul (0,366 pt/m²) sans démonstration de spécificité
   — seul le contraste A/C pouvait trancher. Ces antécédents auraient pu éviter la mesure ;
   la consigne de passe documentaire préalable a failli les rendre suffisants.

**Protocole :** zones A (FFCO 406 ∩ KP blanc, 23,01 ha), B (FFCO 408/410 ∩ KP vert, 2,82 ha),
C (forêt praticable sans overlay, 43,10 ha), D (terrain ouvert, 6,39 ha) — dalle 0448_6888,
corridors ±30 m exclus, trois bandes HAG, deux granularités (1 m et 4 m).

**Résultats décisifs :**

| Bande | A (occ 1m) | B (occ 1m) | C (occ 1m) | D (occ 1m) | A/C |
|-------|-----------|-----------|-----------|-----------|-----|
| B1 [0,2;1,0 m] | 0,062 | 0,275 | 0,071 | 0,076 | 0,872 |
| B2 [0,3;1,5 m] | 0,128 | 0,509 | 0,109 | 0,096 | 1,172 |
| B3 [0,2;2,0 m] | 0,208 | 0,647 | 0,164 | 0,148 | 1,267 |

Sur la bande visée B1 : A=0,062 < C=0,071 < D=0,076. La zone cible est la moins occupée.
Les médianes à 4 m sont nulles dans A et C. B=0,275 >> A : le protocole fonctionne, c'est
le signal qui manque. Les contrastes B2/B3 (×1,17–1,27) sont insuffisants pour établir
une spécificité opérationnelle.

**Verdict : NON — plan clos.**

La Phase 0 ne met pas en évidence de signature HAG basse spécifique des zones FFCO 406
actuellement blanches dans le rendu KP. Le signal présent dans A est comparable à celui
du blanc forestier C et du terrain ouvert D. La piste ne permet donc pas de construire un
canal de sous-bois indicatif fiable à partir de ces bandes HAG.

**Conséquences :**
- Aucune Phase 1 ni Phase 2 lancées.
- Résultats archivés dans `work/expe/sousbois/phase0.md`.
- Aucune modification de production.
