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
