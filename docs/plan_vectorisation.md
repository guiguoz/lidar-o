# PLAN 2 — Vectoriser le raster KP en végétation `.omap` modifiable

> **Brief destiné à Claude Code (ou tout exécutant).** Autonome.
> **Prérequis de lecture :** `docs/protocole_vectorisation_kp.md` (le protocole adopté,
> ses preuves et ses limites) — ce plan n'en répète pas le contenu, il ordonne **ce qui
> reste à faire** après le commit `47e01eb` (2026-09-30).
> **Indépendance :** ce plan est exécutable **sans** le plan 1
> (`docs/plan_amelioration_raster.md`) ; les tâches dépendantes sont marquées « P1-Phase n » (plan 1 v2, expériences à portes).
> **Interdit :** nouveau vectoriseur (CoVe/potrace/graphe de frontières — écartés,
> protocole §3), ML/scoring, modification des étapes 1–9 du moteur sans mesure corpus.

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
- **Acceptation :** couverture mesurée des 3 classes à ± 3 points des cibles ; table
  gelée + commit ; le `report` du terrain suivant part de cette table comme prior.

### V2 — Coutures inter-tuiles : mesurer, puis décider (correction = P1-Phase 3)
- Mesure autonome (sans P1) : diff de classes le long des joints de tuiles sur le
  raster mosaïqué ; publier le % de pixels de joint discordants.
- Si > 1 % : appliquer la correction issue du plan 1 (Phase 3, lissage après mosaïque) **avant** de
  re-mesurer la partition plane.
- **Acceptation :** chiffre dans `docs/bilan_v0.md` ; décision tracée (corriger /
  accepter) avec la mesure.

### V3 — `coverage_simplify` : simplifier la couverture entière (frontières partagées)
- GEOS ≥ 3.12 est déjà exigé par le Dockerfile ; shapely 2.1 expose
  `coverage_simplify`. Test : remplacer DP+Chaikin par (DP léger → coverage_simplify →
  Chaikin) sur le corpus de calibration ; comparer sommets, médiane mm², % < 1 mm²,
  et **chevauchements résiduels** (doit rester 0).
- **Acceptation :** table avant/après sur corpus ; adoption seulement si sommets −30 %
  à métriques de forme constantes ; sinon abandon documenté.

### V4 — Vérification OOM bout en bout
- Ouvrir `output/<terrain>.omap` dans OpenOrienteering Mapper : objets sélectionnables
  par classe, template KP à 50 % dessous, poids du fichier, temps d'ouverture.
- Basculer `keep_template: false`, régénérer, vérifier que la carte reste complète
  (le vert vectoriel seul doit suffire).
- **Acceptation :** capture ou description précise des 3 calques verts + note dans
  `bilan_v0.md` ; aucun objet orphelin hors bbox.

### V5 — Couche 409 sous-bois (dépend de P1-Phase 1 porte 1 + P1-Phase 4a `layer409`)
- Si la porte 1 du plan 1 valide le canal undergrowth **et** si la Phase 4a choisit le mode
  `layer409` : nouvelle couche surfacique ISOM 409 dans
  `src/omap_writer.py` (le symbole existe dans le gabarit), même pipeline de
  généralisation (seuils d'aire propres : 409 = sous-bois, aire mini ISOM à vérifier
  dans le gabarit), partition plane étendue (409 sous 406/408/410 ? **non** : 409 se
  superpose par conception — l'exclure de `coverage_partition` et le documenter).
- **Acceptation :** `.omap` avec 4 calques verts ; planche OOM ; décision humaine
  finale sur le maintien de 409 (symbolisation controversée en FFCO).

### V6 — QA comparée des deux sources
- Même terrain, `vegetation.source: kp` puis `pdal` : table `qa.py` (rappel 406/408/410,
  n objets, médiane mm², chevauchements) + planche 3 panneaux.
- **Acceptation :** table commitée ; recommandation écrite par type de terrain
  (feuillus/resineux, densité de vol) dans `docs/portabilite.md`.

### V7 — Portabilité : deuxième terrain
- Répéter V1 sur un second terrain (kilemaed ou kuti, selon dalles disponibles) ;
  mesurer la dérive de la table `shade_to_isom` ; en déduire une règle de transposition
  (ou son impossibilité) dans `docs/portabilite.md`.
- **Acceptation :** rappel FFCO ou contrôle visuel documenté sur le terrain 2 ; aucun
  paramètre codé en dur spécifique au terrain 1.

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
- Les 3 tests en échec pré-existants sur `main` (`test_init_terrain` check, georef
  450 000 vs 449 000) sont **hors périmètre** : ne pas les « corriger » pour faire
  passer une CI, ouvrir une note distincte.

## 4. Definition of done du plan

1. Table `shade_to_isom` gelée sur ≥ 2 terrains, rappels publiés.
2. Chev. = 0 et coutures documentées sur données réelles.
3. `.omap` vérifié dans OOM avec et sans template.
4. Recommandation kp-vs-pdal écrite par type de terrain.
5. Le protocole (`protocole_vectorisation_kp.md`) ne contient plus aucun chiffre
   synthétique non remplacé ou explicitement marqué « démo ».
