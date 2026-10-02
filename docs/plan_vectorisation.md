# PLAN 2 — Vectoriser le raster KP en végétation `.omap` modifiable

> **Brief destiné à Claude Code (ou tout exécutant).** Autonome.
> **Prérequis de lecture :** `docs/protocole_vectorisation_kp.md` (le protocole adopté,
> ses preuves et ses limites) — ce plan n'en répète pas le contenu, il ordonne **ce qui
> reste à faire** après le commit `47e01eb` (2026-09-30).
> **Indépendance :** ce plan est exécutable **sans** le plan 1
expériences à portes).
> **Au 2026-10-02, le plan 1 est clos sans modification de production** (undergrowth,
> OVL, sous-bois) : les dépendances P1-Phase citées ci-dessous sont des branches
> mortes, conservées pour mémoire.
> **Interdit :** nouveau vectoriseur (CoVe/potrace/graphe de frontières — écartés,
> protocole §3), ML/scoring, modification des étapes 1–9 du moteur sans mesure corpus.
> **Veille vectorisation pro (Illustrator, cartes O réelles, ISOM, OCAD, LivElox) : §5** —
> stratégies S1–S7 intégrées comme mesures, références et variantes ; jamais portes
> (le jugement visuel humain reste la seule porte, R1 du plan 1), jamais dépendances.

---

## 1. Ce qui est déjà fait (ne pas le refaire)

| Fait | Où |
|---|---|
| Pont raster KP → raster classifié (DN 85/170/255), lecture bit/indexé/RGB, mosaïque sur classes, garde-fous | `src/kp_raster.py` + 20 tests `tests/test_kp_raster.py` |
| `vege_bitmode=1` écrit dans le `pullauta.ini` généré | `src/run_engine.py` |
| Source `kp` câblée : vegetation / mask / assemble ; couches veg_406/408/410 injectées en objets ; template piloté par `keep_template` | `main.py` |
| Étape 10 `coverage_partition` (partition plane 410>408>406, chevauchements → 0) | `src/vegetation.py` |
| Calibration teinte→ISOM par couverture : `python -m src.kp_raster report` | `src/kp_raster.py` |
| Démo sans données + figure 3 panneaux + `.omap` contrôlé | `scripts/diag/demo_vectorisation_kp.py`, `docs/images/demo_vectorisation_kp.png` |
| Bugs pré-existants corrigés : SyntaxError `run_engine._build_ini`, double remapping de ton `_merge_vege_tiles` | commits |

## 2. Tâches restantes, dans l'ordre

### V1 — Calibrer `shade_to_isom` sur données réelles (bloquant pour tout le reste)
- Sur `out_kp_grimbosq/` (ou le terrain dont les dalles sont présentes) :
  `python -m src.kp_raster report out_kp_<terrain>` ; placer les coupures pour
  retrouver les cumuls `qa_targets` (19,3 / 6,9 / 8,0 %) ; geler la table dans
  `config.yaml` **par terrain** (structure `terrains.<nom>.shade_to_isom` à créer si
  absente).
- **Acceptation :** table gelée + commit **et planche 1:10 000** (raster KP vs classes
  vectorisées) **regardée par un humain** ; couverture à ± 3 points des `qa_targets` =
  mesure informative (cohérence R1 du plan 1 : les chiffres expliquent, l'œil décide).
  Le `report` du terrain suivant part de cette table comme prior.
- **Ordonnancement :** V1 est **refaite** après toute modification **de production**
  future (sujet nouveau à porte) : un raster amont modifié invalide les coupures
  gelées. Au 2026-10-02, le plan 1 est clos sans modification de production : les
  coupures, une fois gelées, restent valides.

### V2 — Coutures inter-tuiles : mesurer puis décider (mesure faite à OVL-2 ; décision = accepter)
- **Statut 2026-10-02 :** sujet OVL **CLOS** (porte OVL-1 OUI en comptages, puis
  audit OVL-2 et clôture : surdensité de passes convergentes en bord de tuile,
  **sans effet cartographique sur l'emprise de Grimbosq**, voxeldownsize disqualifié ;
  note de clôture dans `docs/bilan_v0.md`). Aucun sujet de correction ouvert ni à
  raccorder : V2 = **décision d'accepter, documentée**. L'audit de basculements de
  classes le long des coutures avec contrôle nul — la mesure de V2 — **a déjà été
  fait à OVL-2** (transitions par couture vs baseline : y6887000 +13, y6888000 −13,
  x449000 +125 expliqué en limite géographique ; run 42 m 408→410 consigné en
  observation). Reste pour V2 : vérifier que décision et chiffres sont bien dans
  `docs/bilan_v0.md` (ils y sont, note de clôture OVL), et l'éventuelle mesure
  informative ci-dessous.
  Mécanisme élucidé à la porte OVL-1 (2026-10-01) : les coutures viennent de
  deux passes de vol convergentes incluses dans chaque dalle en bord de tuile
  (chevauchement de points inter-tuiles ≈ 2 m), pas d'un doublon inter-tuiles →
  la mesure V2 se base sur la carte de recouvrement de points (M1∧M2, drapeaux
  de passe), jamais sur les bbox nominales.
- Mesure autonome (sans P1), **pour mémoire / autres emprises** (faite sur
  Grimbosq à OVL-2) : diff de classes le long des joints de tuiles sur le
  raster mosaïqué, **avec contrôle nul** : même mesure sur des pseudo-joints (mêmes
  lignes décalées à l'intérieur d'une tuile) — sans contrôle nul, n'importe quelle
  texture du couvert passerait pour une couture. Publier % discordants joints −
  % discordants contrôle.
- **Mesure dérivée d'OCAD** (wiki LiDAR Point Cloud Manager) : vérifier si les tuiles
  IGN portent des points LAS « overlap » (classe 12, inter-lignes de vol) et leur part
  en/joint de recouvrement — levier indépendant du double-comptage de retours
  (voxeldownsize) : OCAD seuille ces points au lieu de sous-échantillonner.
- Si une mesure future (autre emprise) montre un effet de classe le long des
  coutures au-delà de ce qu'OVL-2 a audité : **sujet séparé à porte propre**, hors
  de ce plan. La correction Phase 3 n'existe plus (porte 1 NON, voxeldownsize
  disqualifié, OVL CLOS).
- **Acceptation :** chiffre dans `docs/bilan_v0.md` ; décision tracée (corriger /
  accepter) avec la mesure.

### V3 — `coverage_simplify` : simplifier la couverture entière (frontières partagées)
- GEOS ≥ 3.12 est déjà exigé par le Dockerfile ; shapely 2.1 expose
  `coverage_simplify`. Test : remplacer DP+Chaikin par (DP léger → coverage_simplify →
  Chaikin) sur le corpus de calibration ; comparer sommets, médiane mm², % < 1 mm²,
  et **chevauchements résiduels** (doit rester 0).
- **Variante « coins » (S1, Illustrator) :** Chaikin arrondit les angles ; les traceurs
  pro les préservent (slider « Corners »). Comparer deux variantes : Chaikin actuel vs
  simplification **préservant les coins** (DP seul avec epsilon, ou Chaikin à coins
  verrouillés — angles nets conservés). Distribution des angles de coin avant/après
  dans la table d'acceptation.
- **Acceptation :** table avant/après sur corpus : sommets, médiane mm² et % < 1 mm²
  ISOM, **chevauchements (doivent rester 0) et lacunes inter-classes** (slivers blancs
  entre 406/408/410 : Chaikin par polygone après coverage_simplify casse les frontières
  partagées ; la partition répare les chevauchements, pas les lacunes) — lacunes ≤
  baseline mesurée. Adoption seulement si sommets −30 % sous ces contraintes ; sinon
  abandon documenté.

### V4 — Vérification OOM bout en bout
- Ouvrir `output/<terrain>.omap` dans OpenOrienteering Mapper : objets sélectionnables
  par classe, template KP à 50 % dessous, poids du fichier, temps d'ouverture.
- Basculer `keep_template: false`, régénérer, vérifier que la carte reste complète
  (le vert vectoriel seul doit suffire).
- **Mode dégradé si OOM indisponible dans l'environnement d'exécution :** validation
  XML (comptes d'objets par symbole cohérents avec le gpkg, aller-retour de
  géoréférencement — logique `_verify_omap` de `scripts/diag/demo_vectorisation_kp.py`)
  + planche rendue 1:10 000 ; la vérification OOM reste recommandée mais non bloquante.
- **Acceptation :** capture ou description précise des 3 calques verts + note dans
  `bilan_v0.md` ; aucun objet orphelin hors bbox.

### V5 — Couche sous-bois « propose409 » (dépend de P1-Phase 1 porte 1 + P1-Phase 4a)
- **CLOSE deux fois : porte 1 NON (2026-10-01) puis phase 0 du canal sous-bois
  A ≈ C (2026-10-02, R8 sans appel).** Pas de canal undergrowth, donc pas de couche
  `propose409`, et pas d'« autre canal » sur lequel la rouvrir : sujet définitivement
  clos. Section conservée pour mémoire uniquement (sémantique ISOM figée, tag OOM,
  exclusion de `coverage_partition`).
  « undergrowth »** (vérifié dans `assets/ISOM 2017-2_10000.omap` : 409 = « Vegetation:
  walk, good visibility » ; « Green 100% for undergrowth » n'est qu'une couleur).
  Un sous-bois qui ralentit la course se classe déjà par la vitesse (406/408/410) ;
  407/409 y ajoutent un jugement de **visibilité**, qui est un jugement de terrain
  (protocole vectorisation § reste à l'humain). D'où le mode 4a renommé
  `propose409` : couche séparée dessinée en 409 **pour revue**, que le cartographe
  réaffecte (408/410 selon vitesse, 407/409 seulement si visibilité confirmée au
  terrain). Jamais une couche validante.
- Si la porte 1 du plan 1 valide le canal **et** si la Phase 4a choisit `propose409` :
  couche surfacique 409 dans `src/omap_writer.py`, même pipeline de généralisation
  (aire mini ISOM 409 = 0,7 × 0,7 mm, comme 408 — à geler dans config), **exclue de
  `coverage_partition`** (superposition par conception), documenté.
  Taguer chaque objet `propose409` (tag OOM) à l'écriture : réaffectation groupée
  possible via `Edit > Find` (tag) → `Convert to object` (S6, workflow pro OOM).
- **Étalonnage informatif par allures GPS (S5) : déplacé à V6** (sur les classes
  406/408/410) — propose409 étant définitivement clos, son ancien support ici n'a
  plus d'objet.
- **Acceptation :** `.omap` avec 4 calques verts dont un marqué « pour revue » ;
  planche OOM ; décision humaine finale sur le devenir de chaque objet 409.

### V6 — QA comparée des deux sources
- Même terrain, `vegetation.source: kp` puis `pdal` : table `qa.py` (rappel 406/408/410,
  n objets, médiane mm², chevauchements) + planche 3 panneaux **regardée** (R1).
- **Source `pdal` = chaîne abandonnée dans le livrable (bilan).** Si elle tourne
  encore, la comparaison kp-vs-pdal reste informative en contrôle d'héritage ;
  sinon, V6 se replie sur QA kp + comparateurs (carte pro S3, OCAD optionnel,
  tailles ISOM), et l'objet 4 de la definition of done devient une recommandation
  kp par type de terrain, pdal cité comme chaîne abandonnée.
- **Étalonnage informatif par allures GPS (S5, ex-V5) :** si des traces GPX
  d'épreuves sur Grimbosq existent (LivElox / 3D Rerun) **et** avec l'accord des
  organisateurs, calculer l'allure agrégée par classe de vert (blanc / 406 / 408 /
  410) et la confronter aux plages de runnability IOF (≈ 100 % / slow running /
  walk / fight / 0–20 %) : calibrage informatif des coupures de V1 par bandes de
  vitesse. Rapporté à côté de la planche ; **jamais une porte** — la runnability
  reste un jugement de cartographe (BKO : « there is no precise way of measuring
  runnability »). Données personnelles : statistiques agrégées uniquement, aucune
  trace republiée.
- **Planche de référence pro (S3) :** la carte de Grimbosq de décembre 2015 (CO
  Pédestre / Orientation Caennaise, doma go78.org via omaps.worldofo.com —
  versions **sans tracés** disponibles) géoréférencée (3 points) en panneau
  supplémentaire : référence dessinée par des humains sur le même terrain. JPG
  seulement (worldofo ne publie pas les fichiers vectoriels) : comparaison visuelle,
  pas de statistiques de polygones.
- **Vocabulaire ISOM §2.6 (S2) pour le compte rendu :** généralisation *sélective*
  (dimensions mini, ce qu'on omet) vs *graphique* (simplification, déplacement,
  exagération) ; la lisibilité ne doit jamais être sacrifiée au détail ; les
  frontières nettes entre végétations sont des points de repère du lecteur — la
  topologie (0 chevauchement, 0 lacune) de V3/V4 est une exigence ISOM, pas
  seulement interne.
- Y adjoindre le **contrôle des tailles mini ISOM par symbole** (stratégie OCAD
  « Check Legibility Space » : aires minimales ISOM 2017 comme aide à la
  généralisation ; OCAD ne contrôle pas les largeurs minimales — nous, si : métriques
  de largeur/isthmes déjà dans le moteur), en aide informative, jamais en arbitre.
- Comparateur externe optionnel : « Extract Features » / « Vegetation Base Map » d'OCAD
  (vectorisation végétation native) si licence OCAD disponible — OCAD prévient lui-même
  que les résultats « should be treated with caution » : indicateur, pas référence.
- **Acceptation :** table + planche commitées ; recommandation écrite par type de
  terrain (feuillus/resineux, densité de vol) dans `docs/portabilite.md`.

### V7 — Portabilité : deuxième terrain
- Répéter V1 sur un second terrain **normand de préférence** (domaine ciblé,
  bilan) ; kuti ou kilemaed seulement en sensibilité **explicitement hors domaine**
  (veille : Kilemaed lande sémantiquement discordante, Airelles hors domaine) ;
  mesurer la dérive de la table `shade_to_isom` ; en déduire une règle de transposition
  (ou son impossibilité) dans `docs/portabilite.md`.
- **Acceptation :** rappel FFCO ou contrôle visuel documenté sur le terrain 2, sur
  planche 1:10 000 (R1) ; aucun paramètre codé en dur spécifique au terrain 1.

### V8 — Consolidation documentaire
- `docs/bilan_v0.md` : section « source kp » avec les tables V1/V6/V7.
- `docs/protocole_vectorisation_kp.md` : remplacer les chiffres de la démo synthétique
  par les chiffres réels là où ils existent ; annexe « valeurs gelées ».
- README : si V6 donne un gagnant clair, l'écrire en une phrase.

## 3. Contraintes transverses

- Toute modification du moteur = mesure corpus avant/après (`scripts/measure_corpus.py`)
  + commit séparé ; jamais deux changements dans le même commit.
- Les seuils vivent dans `config.yaml` (`generalization.profiles.*`) ; les valeurs
  gelées par terrain vivent dans `terrains.*`.
- Sorties dans `work/` ; seules planches `docs/images/*.png` et docs sont commitées.
- Tests : tout nouveau comportement a son test dans `tests/test_kp_raster.py` ou
  `tests/test_vegetation.py` (partition plane, 409 exclu, coverage_simplify).
- OCAD (propriétaire) : stratégies lues sur le wiki public, aucun code copié ; ses
  sorties (Vegetation Base Map, Extract Features) ne sont que des comparateurs
  externes optionnels, jamais des dépendances ni des références.
- Traces GPS (LivElox / 3D Rerun) : données personnelles — statistiques agrégées
  seulement, accord des organisateurs/utilisateurs ; jamais une porte.
- Logiciels pro (Illustrator, OCAD…) : stratégies et vocabulaire repris de leurs
  documentations publiques ; aucun code ni binaire propriétaire dans le pipeline.
- Les 3 tests en échec pré-existants sur `main` (`test_init_terrain` check, georef
  450 000 vs 449 000) sont **hors périmètre** : ne pas les « corriger » pour faire
  passer une CI, ouvrir une note distincte.

## 4. Definition of done du plan

1. Table `shade_to_isom` gelée sur ≥ 2 terrains, rappels publiés.
2. Chev. = 0 sur données réelles ; coutures documentées et décision acceptée
   (audit OVL-2 + clôture bilan, 2026-10-02).
3. `.omap` vérifié dans OOM avec et sans template.
4. Recommandation kp écrite par type de terrain (pdal : chaîne abandonnée,
   comparaison informative si elle tourne).
5. Le protocole (`protocole_vectorisation_kp.md`) ne contient plus aucun chiffre
   synthétique non remplacé ou explicitement marqué « démo ».

## 5. Veille — stratégies de vectorisation pro (2026-10-01)

Même statut que la veille OCAD : **stratégies, références et mesures — jamais
dépendances, jamais portes.**

| # | Stratégie | Source | Intégration |
|---|---|---|---|
| S1 | **Image Trace** (Illustrator) : 5 réglages — Threshold, Paths (fidélité), Corners (préservation des angles), Noise (nombre minimal de pixels adjacents ignoré), Ignore White (fond) — puis nettoyage pro : `Object > Path > Simplify` (« le minimum de points qui tient la forme »), alignement des ancres vacillants (Direct Selection + Align), `Clean up` des objets non peints | helpx.adobe.com « Image tracing presets » ; tutoriels pro | Équivalents déjà présents : Threshold = greenshades (gelé), Noise = aire mini ISOM (V6), Ignore White = fond, Clean up = contrôle orphelins (V4). **Apport nouveau : Corners → variante de V3** (Chaikin arrondit les coins ; les traceurs pro les préservent) |
| S2 | **ISOM 2017-2 §2.6** : la généralisation a deux phases — *sélective* (choisir ce qu'on représente ; dimensions mini adoptées dès le relevé) et *graphique* (simplification, déplacement, exagération). « La lisibilité ne doit jamais être sacrifiée pour représenter un excès de détails » ; la cohérence entre cartes est une qualité première ; **les frontières nettes entre types de végétation sont des points de repère du lecteur** | ISOM 2017-2, PDF bilingue FFCO (mars 2022) ; baoc.org | Vocabulaire et critères de V6 ; V3/V4 : la topologie (0 chevauchement, 0 lacune, frontières partagées) est une exigence ISOM, pas seulement une propreté interne |
| S3 | **Carte pro du même terrain** : Grimbosq la Motte, 6 déc. 2015 — « One-man relais RDE » et « WE RDE court-long » (CO Pédestre / Orientation Caennaise ; collection Axel Pannier). JPG **sans tracés** téléchargeable ; worldofo ne publie **aucun fichier vectoriel** | omaps.worldofo.com id 159467/159468 → doma go78.org | V6 : panneau de référence supplémentaire (géoréférencement 3 points) ; comparaison visuelle uniquement, pas de statistiques de polygones |
| S4 | **OCAD contrôle les dimensions mini IOF pendant le dessin** (indicateur vert/rouge + % trop petit), en plus de Check Legibility Space en fin de carte ; le mapper du WOC 2025 (Janne Weckman, ~50 km² dont 20 km² WOC) l'utilise en contrôle final | ocad.com/blog (tag ISOM 2017 ; interview Weckman) | V6 (tailles mini déjà intégrées) ; référence pour l'édition manuelle dans OOM : « dessiner assez grand ou omettre » |
| S5 | **LivElox / 3D Rerun** : traces GPS téléchargeables (GPX), allures par patte ; runnability IOF = plages de vitesse (blanc ≈ 100 %, 406 slow running, 408 walk, 410 fight, 411 impassable ≈ 0–20 %) mais « there is no precise way of measuring runnability — c'est un jugement du cartographe » | livelox.com/documentation ; bko.org.uk KYS-Vegetation.pdf | V5 : allure agrégée par classe de vert = étalonnage **informatif** des bandes de vitesse (accord organisateurs requis ; données personnelles : agrégats seulement) ; confirme R1 |
| S6 | **OOM pro workflow** : `Edit > Find` par tag d'objet → sélection groupée → `Convert to object` (utilisé p. ex. pour réaffecter les courbes importées de Karttapullautin) | attackpoint.org (Jagge) | V5 : taguer les objets `propose409` à l'écriture pour permettre la réaffectation groupée dans OOM |
Pas un comparateur (c'est notre moteur) : les « benchmark patches » (cercles à végétation connue → histogrammes → étalonnage) redirigés vers **V1** en raffinement optionnel si un mapper arpente des patchs tests ; le plan 1, ancien destinataire des conseils, est clos au 2026-10-02
