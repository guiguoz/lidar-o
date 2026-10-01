# Journal d'expérimentation — portes et verdicts

> Application de la règle R4 (plan 1) : verdicts datés, **négatifs compris**, commités
> ici ; le journal de travail vit dans `work/expe/JOURNAL.md` (machine exécutant).

## Porte 1 — diagnostic undergrowth (plan 1, Phase 1) — 2026-10-01 : **NON**

**Fenêtre :** fen3_410 (gelée V0.4), centre (449420, 6887239) L93, 500 × 500 m,
dalles 0449_6887 + 0449_6888 (contenance vérifiée sur métadonnées PDAL réelles).
**Planche :** `work/expe/planches/phase1_undergrowth.png` (machine exécutant) —
6 panneaux : KP actuel / C1 / C2 / C3 / C4 / FFCO 406-408-410. À copier en
`docs/images/phase1_undergrowth_gate1_NON.png` dans le commit de verdict
(preuve visuelle du négatif, R4).
**Candidats et couvertures** (fenêtre 25 ha) :
C1 (0,3-1] σ2 m t=1,0 → 38,5 % (~9,6 ha) · C2 (0,3-1] σ2 m t=0,5 → 59,5 % (~14,9 ha) ·
C3 (0-1] σ2 m t=1,0 → 76,3 % (~19,1 ha) · C4 (0,3-1,3] σ2 m t=1,0 → 67,0 % (~16,8 ha).
**Biais connu :** V0.6 = +50 % sur la strate low dans une bande ~30 m en bas de
fenêtre (recouvrement inter-tuiles) — écarté du verdict par le juge, qui l'avait
établi avant de regarder.

**Verdict (juge humain, substance verbatim) :** le signal est très présent mais
n'apporte pas une information cartographiquement propre par rapport au KP actuel.
C1 produit surtout une multitude de petites taches et de connexions fines : à
1:10 000, une texture de densité plutôt que des structures de végétation à ajouter
à la carte. C2–C4 couvrent beaucoup trop : on approche d'un masque général de forêt,
le canal ne localise plus un « sous-bois manquant ». En regardant KP actuel / C1 /
FFCO, aucun motif convaincant du type « ici le KP laisse clairement du blanc, le
canal retrouve précisément une structure végétale cohérente ». C3 (76,3 %) confirme
qu'en élargissant la strate basse on obtient une couverture massive : le levier
« points très bas » n'isole pas proprement une classe de sous-bois.

**Résultat à conserver (verbatim) :** « Sur la fenêtre Grimbosq sélectionnée, les
quatre variantes du canal low testées (C1–C4) ne font pas apparaître un sous-bois
supplémentaire suffisamment structuré et cartographiquement crédible par rapport au
raster KP actuel. La piste est donc abandonnée sans optimisation supplémentaire. »

**Conséquences :**
- Phases 2 et 3 du plan 1 : non conduites sur cette piste (décision du juge).
- Sujets 4a/4b : sans objet ; 4c–4f bloqués par la règle de portes « 1–3 » (plan 1 §5).
- Plan 2 : V5 (`propose409`) close ; V2 perd sa source de correction (P1 Phase 3) et
  devient mesure + décision d'accepter.
- Production intouchée (R2/R6) : aucun paramètre dans `config.yaml`, aucun code modifié.

**Nature du résultat :** négatif expérimental propre — une famille de traitements
(strates low + gaussienne σ2 + seuil) éliminée avant tout contact avec la production.
Mesures utiles conservées pour la suite : V0.6 (biais de recouvrement +50 % dans la
bande), V0.7 (fenêtre effective mbs2=16 → 17 px → 7,20 m → 7 px @1 m/px), C3 = masque
forestier par dilution, et la planche elle-même (référence de ce que le canal donne).

## Porte OVL-1 — recouvrement de dalles (plan 1 §3) — 2026-10-01 : **OUI (surdensité significative)**

**Juge :** agent, sur délégation explicite de l'utilisateur ; base = `overlap_stats.md`
+ planche `work/expe/planches/planche_overlap.png` décrite (bande ratio nettement
visible au centre, atténuation vers les témoins). **Clause visuelle restante :**
couture visible ou non sur le panneau 1 (production recadrée) — à confirmer au
commit de verdict ; si absente, le verdict se requalifie en « surdensité
significative en comptages, trace en classes produites à mesurer » (première
question du sujet correction).

**Chiffres (fenêtre O2, bande ~30 m centrée sur y=6887000, témoin > 50 m) :**
| strate | A front/témoin | B/A front | B/A témoin | Δ | B front/témoin (dérivé) |
|---|---|---|---|---|---|
| low | 1,25× (5 vs 4 pts/m²) | 0,333 | 0,500 | −0,167 | 0,83× |
| medium | 1,35× (27 vs 20) | 0,518 | 0,684 | −0,166 | 1,02× |
| high | 1,85× (170 vs 92) | 0,492 | 0,682 | −0,190 | 1,33× |

**Lectures :** (1) voxeldownsize n'est pas une déduplication mais un éclaircissement
densité-dépendant : sur-corrige low (0,83), corrige medium (1,02), sous-corrige high
(1,33) ; (2) hors recouvrement, voxeldownsize jette 32–50 % des points réels
(B/A témoin) — impropre comme correction de production en l'état ; (3) Δ non nul =
effet spécifique du double apport confirmé (contrôle nul valide) ; (4) mécanisme :
dalles coupées nettement (chevauchement de points inter-tuiles ≈ 2 m), surdensité
due aux **deux passes de vol convergentes incluses dans chaque dalle en bord de
tuile** → défaut systématique le long de **chaque couture de dalles de la carte**,
pas doublon inter-tuiles localisé.

**Conséquences (§3.6) :** aucune correction dans cette phase ; sujet correction
**non ouvert**, en attente de go explicite. Périmètre recommandé si go :
(1) basculement de classes dans les bandes de couture sur toute la carte
(proximité aux seuils — la production n'a pas de voxeldownsize et porte la
surdensité pleine, mais 4→5 / 20→27 / 92→170 pts/m² sont loin des seuils : le
basculement n'est pas garanti) ; (2) test PointSourceId / ScanDirectionFlag en
bande (garder une seule passe = vraie déduplication) ; (3) planche candidat vs
production. Plan 2 V2 : mesurer les coutures via carte de recouvrement de points
(M1∧M2 / drapeaux de passe), pas via bbox nominales.

### Clause visuelle OVL-1 (panneau 1) — 2026-10-01 : **NON, pas de couture visible dans la production sur O2**

Juge : agent, sur planche `planche_overlap.png` attachée en chat (le fichier n'est
pas persisté dans le sandbox). Lecture : panneaux 2 et 4 montrent la bande
(surdensité, ratio bas) ; panneau 3 lavé partout = confirmation visuelle de
B/A témoin 0,50–0,68 ; panneau 1 : verts continus à travers y=6887000 sur les
deux tiers gauches, aucun liseré tonal aligné ; tiers droit : bord vert/beige
dans la bande lu comme limite de parcelle (bord rectiligne, rangs de plantation
au panneau 2, et contresens physique : une surdensité verdirait la bande, ne
l'ouvrirait pas).

**Verdict requalifié comme prévu : surdensité significative en comptages (OUI),
trace en classes produites non visible sur O2.** La carte produite aujourd'hui
ne montre pas sa couture *ici*. La mesure qui décide = audit de basculement de
classes sur toutes les coutures (étape 1 du périmètre correction), car O2 est
une fenêtre aux comptages loin des seuils ; une couture traversant une densité
proche d'un seuil basculerait (30 m à 1:10 000 = 3 mm visibles).

**Recommandation tracée :** ouvrir l'étape 1 seule (audit map-wide des
basculements dans les bandes M1∧M2, aucun code de correction), porte propre ;
si aucun basculement aligné → recouvrement clos en caractéristique de production
documentée (`bilan_v0.md`) ; sinon étapes 2–3 sur second go. Premier candidat à
inspecter par l'audit : le bord vert/beige du tiers droit de O2 (x > 449500) —
si son y est exactement 6887000 sur plusieurs dizaines de mètres, la lecture
« parcelle » est contredite et les chiffres gagnent.

## Porte OVL-2 — audit des basculements de classe (plan 1 §3.7) — 2026-10-01 : **OUI**

**Juge :** agent, sur délégation explicite ; base = `work/expe/overlap/audit/`
(audit_stats.md + planche_audit.png décrits/attachés).

**Résultats :** candidat O2 : médiane y=6887000,5 (seam 6887000), IQR 10 m,
max 23,5 m, 46/143 colonnes alignées ≤1 m → bord mixte (parcelle divaguante +
tronçon ~40 m piné : le test §7.4 tranche contre la lecture « parcelle » sur ce
tronçon — les chiffres gagnent, comme convenu). Par couture : y6887000 excès
+13 (baseline 59), run 42 m (408→410, sens montant) ; y6888000 excès −13
(couture propre = témoin interne de l'audit) ; x449000 excès **+125** (baseline
71, 2,8×), dominant 406↔non-veg, runs ≤19 m fragmentés.

**Lecture :** x449000 = signature d'artefact de traitement (excès fragmenté piné
au pixel sur ligne administrative ≠ objet rectiligne du terrain) ; le motif
« piné SUR la ligne, pas aux bords de bande » et le sens potentiellement
descendant désignent un suspect n°1 autre que la surdensité : **discontinuité
d'échelle entre tuiles** si le normalisateur de `thevalue` (V0.1 : sans
dimension) est calculé par run/tuile — la surdensité (a) reste contributeur
accessoire (signature attendue : bords de bande, sens montant seul).

**Verdict OVL-2 = OUI :** basculements alignés existants (1 couture forte,
1 modérée, 1 propre) ; défaut cartographique là où les densités frôlent un
seuil. Étapes 2–3 non ouvertes — second go explicite requis. Périmètre
recommandé si go : étape 2 = discrimination de mécanisme (portée du
normalisateur KP par relecture V0.1/source ; profil de saut de densité bande
vs toute la ligne ; croisement segments alignés × prédicteurs ; sens par
couture) ; étape 3 = planche expérimentale échelle harmonisée par terrain vs
production, puis proposition de modification de production sur porte dédiée
seulement.

## Porte OVL-2 — verdict du porteurer (2026-10-01) : **CLOS**, run 42 m consigné en observation

Mon verdict agent « OUI » du jour même est **renversé** par le porteur de porte,
sur planche 1:10 000 et chiffres d'audit. Ses quatre arguments, consignés :

1. **x449000 = limite de massif, pas artefact.** La vue d'ensemble montre que la
   ligne sépare deux paysages (massif compact à l'ouest, tissu fragmenté bâti /
   parcelles à l'est) sur toute la hauteur de la carte, bien au-delà de toute
   bande de couture ; un artefact de bord de dalle est un liseré local.
2. **Sens du basculement.** `406 ↔ non-veg` = oscillations dans les deux sens
   autour du seuil le plus bas ; une surdensité classerait vers le haut
   (408/410), un saut d'échelle fixe entre tuiles serait unidirectionnel. Ni
   l'un ni l'autre : limite réelle qui longe et croise la coupe.
3. **Candidat O2 écarté par ses propres chiffres.** IQR 10 m, 32 % de colonnes
   alignées au mètre : un artefact de dalle serait aligné à ~100 % (ligne droite
   par construction) ; cette dispersion décrit une structure du terrain qui
   croise la couture. Lecture « limite de parcelle » maintenue, contresens
   physique non contredit.
4. **Résidu unique : run 42 m sur y=6887000, 408→410, sens montant** — seul
   élément combinant bon sens et longueur cohérente ; isolé sur une couture de
   2 km → consigné en **observation**, pas en défaut ; n'ouvre pas de correctif.

**Conséquences :** sujet OVL clos sans modification de production ; étapes 2–3
sans objet, non ouvertes. Mon hypothèse (b) « normalisateur KP par tuile »
meurt **non testée**, consignée comme telle et non réfutée : si un liseré de
couture réapparaît sur une autre emprise, premiers tests = répartition des sens
des bascules par couture + portée du normalisateur (V0.1 / source KP). La note
V2 demeure : mesurer les coutures par recouvrement de points (M1∧M2 / drapeaux
de passe), jamais par bbox nominal. Planche audit : `work/expe/overlap/audit/
planche_audit.png` (copie `docs/images/` à la charge de l'exécuteur, commit de
verdict = celui-ci).
