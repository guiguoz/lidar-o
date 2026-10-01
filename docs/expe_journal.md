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
