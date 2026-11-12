# V4 — Contrôles structurels .omap (Grimbosq)

Input : v3_arm_c.gpkg — coverage_simplify 2 m, 772 KB

## no_template (v4_no_template.omap, 821.1 KB, écriture 0.2 s)

1. XML valide : **True** — racine <map>
2. Objets par ISOM : {'406': 1340, '408': 409, '410': 18}  (total objets de carte : 1767)
   *Note : le compteur ne lit que le bloc `<objects>` du .omap ; les `<object>`
   graphiques à l'intérieur des définitions de symboles (enfants `<element>`)
   ne sont pas des objets de carte et ne sont pas comptés ici.*
3. Bbox .omap : [448000.0, 6886000.0, 449997.0, 6888997.0] → dans emprise
4. Taille fichier : 821.1 KB

5. Round-trip raster (grille V1) :

| ISOM | Identiques | Perdus | Ajoutés |
|-----:|-----------:|-------:|--------:|
| 406 | 433353 | 12081 | 11152 |
| 408 | 272705 | 3918 | 3643 |
| 410 | 3791 | 105 | 110 |

## with_template (v4_with_template.omap, 821.3 KB, écriture 0.2 s)

1. XML valide : **True** — racine <map>
2. Objets par ISOM : {'406': 1340, '408': 409, '410': 18}  (total objets de carte : 1767)
   *Note : le compteur ne lit que le bloc `<objects>` du .omap ; les `<object>`
   graphiques à l'intérieur des définitions de symboles (enfants `<element>`)
   ne sont pas des objets de carte et ne sont pas comptés ici.*
3. Bbox .omap : [448000.0, 6886000.0, 449997.0, 6888997.0] → dans emprise
4. Taille fichier : 821.3 KB

5. Round-trip raster (grille V1) :

| ISOM | Identiques | Perdus | Ajoutés |
|-----:|-----------:|-------:|--------:|
| 406 | 433353 | 12081 | 11152 |
| 408 | 272705 | 3918 | 3643 |
| 410 | 3791 | 105 | 110 |

---

## V4.5 — Tableau de validation unifié

| Contrôle | sans template | avec template (50 %) |
|----------|:-------------:|:--------------------:|
| XML valide | **PASS** | **PASS** |
| ISOM 406 = 1340 | **PASS** | **PASS** |
| ISOM 408 = 409  | **PASS**  | **PASS**  |
| ISOM 410 = 18   | **PASS**   | **PASS**   |
| Objets parasites (sym_?) | **PASS** | **PASS** |
| Bbox dans emprise V1 | **PASS** | **PASS** |
| Round-trip = coût bras C | **PASS** | **PASS** |
| OOM ouvre sans erreur | **PASS** | **PASS** |
| Géoréférencement sur fond | N/A | **PASS** |
| Sélection objets par classe | **PASS** | **PASS** |
| Anneaux intérieurs visibles | **PASS** | **PASS** |
| Objets hors emprise : 0 | **PASS** | **PASS** |
| Modification d'un sommet | **PASS** | **PASS** |
| Sauvegarde + réouverture | **PASS** | **PASS** |
| Vecteurs seuls exploitables (R1) | **PASS** | N/A |
| Rendu décalque correct (R2) | N/A | **PASS** |

Contrôle post-édition (`ctrl_omap` sur fichiers sauvegardés par OOM) :
`v4_no_template_test.omap` et `v4_with_template_test.omap` → 1340/409/18, aucun sym_?, count OK.

---

## V4.6 — Planche de vérification

Planche 3 panneaux (1:10 000) : [v4_plate.png](v4_plate.png)

A — KP vegetation.png · B — OMAP vecteurs seuls · C — OMAP vecteurs + fond 50 %

---

## Verdict

**V4 PASS** — 2026-10-04

Chaîne complète validée :
KP vegetation.png → shade_to_isom → 406/408/410 → polygonisation (lossless V1)
→ coverage_simplify 2 m (topologie V3) → OMAP → OOM éditable

Prochaine étape : V5 close mémoire.