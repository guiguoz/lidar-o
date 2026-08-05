# `co-vector-fr` / Ovector — Plan d'exécution v3

> **Remplace** le plan d'exécution v2 **et** la série `PLAN_vegetation_406.md` (v1–v4) /
> `PLAN_v5_vegetation.md`. Document unique de référence.
>
> Fusionne : la structure d'exécution du plan v2 (phases, verrous, tests, durcissement) et les
> résultats **mesurés** des sessions de calibration végétation (2026-08-04 et suivantes).
> Là où les deux se contredisaient, la mesure l'emporte sur la supposition.

---

## Note de cadrage — inchangée dans l'esprit, précisée par l'expérience

Le squelette « LIDAR → carte vectorielle ISOM éditable dans OOM » existe déjà (workflow
couch-mapper, Karttapullautin en DXF, import CRT dans OOM). **On ne le développe pas, on le
câble.** La valeur du projet reste double :

1. **La vectorisation propre de la végétation** — seul vrai morceau de R&D.
2. **Le packaging « un coup » pour la France** — emprise → dossier prêt à importer.

Répartition d'effort visée : ~70 % végétation, ~20 % packaging, ~10 % câblage.

**Ce que l'expérience a ajouté au cadrage** : il existe un **plafond sémantique** mesuré. Le LiDAR
répond à « où y a-t-il de la matière végétale ? », le cartographe à « où cette végétation gêne-t-elle
assez pour mériter un symbole ? ». Ce n'est pas le même objet, et sur certains terrains
l'information n'est simplement **pas dans le signal** (voir Domaine de validité). Le livrable doit
donc annoncer non seulement « base propre, finition terrain attendue », mais aussi **où le pipeline
est fiable et où il ne l'est pas**.

---

## État réel du dépôt (à jour)

**Fait et validé :**
- `src/vegetation.py` — moteur de généralisation 7 étapes, calibré, testé sur 3 terrains.
- `scripts/process_hag.py`, `run_terrain.py`, `measure_corpus.py` — classification, orchestration
  partielle, mesure contre corpus de référence.
- Garde-fous : fraîcheur `mtime` du classifié, comptage nodata, `run_metadata.json`
  (`tiles_count`, `tile_ids`, `run_date`).
- `scripts/mappings/*.yaml` — conventions cartographiques externalisées (FFCO fr, ISOM en).
- Corpus : Grimbosq (feuillus, FR), Airelles (lande d'altitude, FR), Kilemäed (mixte, EE).

**Stubs (`raise NotImplementedError`) :** `fetch.py`, `run_engine.py`, `crt_mapping.py`,
`assemble.py`, `export_oom.py`, `qa.py`, `main.py`.

**Jamais exécuté :** Karttapullautin. C'est le verrou de la Phase 0, et il n'a pas été levé —
tout le travail végétation a été fait en « plan B » sans jamais trancher le plan A.

---

## PHASE 0 — Reconnaissance — VERROU, TOUJOURS OUVERT

**Statut : non fait. Prérequis immédiat de tout le volet livrable.**

Karttapullautin n'a jamais tourné. La question décisive du plan v2 reste sans réponse et elle
commande l'architecture d'assemblage :

> **KP expose-t-il un raster de densité de végétation continu réutilisable, ou seulement le PNG
> vert rendu ?**

Aujourd'hui la végétation est calculée par PDAL (le « plan B » du plan v2), et elle est calibrée.
Ce n'est pas une raison de sauter la Phase 0 : ce qu'on cherche maintenant, c'est **ce que KP
produit pour tout le reste** (courbes, falaises, buttes) et **sous quel format**, parce que c'est
ce qui détermine si `assemble.py` est un travail d'injection XML ou de génération complète.

**Tâches :**
- Vérifier si le `Dockerfile` à la racine embarque déjà KP (une minute, évite peut-être l'install).
- Installer KP (version **épinglée**), le lancer sur les dalles Grimbosq **déjà en cache**.
- Inventorier précisément les sorties dans `docs/etat_existant.md` : formats (DXF ? PNG ?
  `.omap` direct ?), **noms exacts des calques DXF** (le CRT en dépend), présence ou non d'un
  raster de densité végétation exploitable.
- Récupérer le CRT Karttapullautin existant (Orienteering BC) + jeu de symboles ISOM 2017-2 OOM
  ≥ 0.9.x → `assets/`.
- `GetCapabilities` sur `data.geopf.fr` → noms exacts des couches BD TOPO.

**Bénéfice secondaire non prévu au plan v2 :** KP produit sa propre végétation. Ça donne un point
de comparaison direct avec la nôtre sur le même terrain — information qu'aucune de nos mesures ne
fournit, et qui peut être inconfortable si sa sortie brute se révèle proche.

**Définition de terminé :** `docs/etat_existant.md` tranche, brique par brique, réutiliser vs
écrire. Format des sorties KP connu et documenté.

---

## PHASE 6 (traitée en premier car largement faite) — Végétation

> **Cette phase remplace intégralement la Phase 6 du plan v2**, dont plusieurs affirmations sont
> réfutées par la mesure. Voir « Réfutations » en fin de section.

### 6.1 — Acquis verrouillés

**`gaussian_sigma: 1.0`** (était 3.0). Cause racine du blob 406 : un gaussien σ=3 m sur grille 1 m
comblait les creux entre patches voisins et fabriquait une **vallée de densité continue dans le
raster, avant toute généralisation vectorielle**.

| Grimbosq | avant (σ=3) | après (σ=1) | cible FFCO |
|---|---|---|---|
| Concentration du plus gros polygone | 51,3 % du 406 | **7,2 %** | 5,4 % |
| Couverture 406 | 24,4 % | **16,6 %** | 15,0 % |

Validé sur Airelles (structure archipel, max%406 = 3,4 %) et Kilemäed. Tags
`v1_vegetation_baseline` / `v2_vegetation_sigma1`.

**⚠️ Ne pas remonter σ sans re-mesurer.** Le plan v2 présentait ce paramètre comme « la seule
source d'arrondi organique » et « le principal levier de naturel du rendu ». C'est faux et
dangereux : c'est le principal levier de **fabrication d'artefacts**.

### 6.2 — Pipeline de généralisation actuel

Ordre en production dans `src/vegetation.py` :

```
dissolve → remove_holes → remove_small → merge_proximity → remove_isolated → simplify → smooth
```

**Bug d'ordre identifié, non corrigé :** `remove_small` s'exécute *avant* `merge_proximity`, et
`remove_isolated` *après*. Conséquence : une fois des taches agglomérées par la fusion, plus rien
à l'intérieur n'est « isolé » ni « petit » — elles ne sont jamais nettoyées. C'est pourquoi T10
(min_area 50→100) n'avait pas eu l'effet attendu : il traitait des taches individuelles alors que
le problème était l'agglomération. **À reprendre** (Phase 6.6).

**`fusion_distance_m[406]` = 8 m** produit une transition de phase (percolation) : entre 4 m et
8 m, le plus gros polygone passe de 52 % à 73 % du 406 et le compte s'effondre de 681 à 418.
Contrôle à `fd=0` : la nappe existe déjà (75 ha, 51 %) — la fusion **amplifie** un défaut raster,
elle ne le crée pas. Avec σ=1.0 la question est à re-mesurer ; 4 m est le candidat par défaut.

### 6.3 — Domaine de validité (nouveau — absent du plan v2)

Le pipeline **n'est pas uniformément fiable**. Mesuré :

| Terrain | Profil | Δ couverture | Verdict |
|---|---|---|---|
| **Grimbosq** (FR) | Feuillus, couvert fermé | +1,6 pt | **Fiable** — résidu dans le bruit cartographique |
| **Kilemäed** (EE) | Mixte, semi-ouvert | 55,9 % du 406 en terrain ouvert | Intermédiaire |
| **Airelles** (FR) | Lande d'altitude + résineux épars | ×4,8 vs cible | **Hors portée** |

**Cause racine de l'échec Airelles, démontrée :** ISOM code la **praticabilité du sol**, pas la
structure verticale. Une lande d'airelles (30–60 cm, praticable → 403/404 jaune) et un sous-bois
ralentissant (→ 406 vert) ont des profils HAG[0,3:3 m] **identiques** : `density_hag` médiane 4
dans les deux cas, ratio 0,02 dans les deux, et le pipeline classe même *plus* de pixels en 406
sur terrain découvert (34,7 %) que sur du 406 réel (30,4 %). **L'information est absente du
signal** — ce n'est pas un problème de seuil, de lissage ni de métrique dérivée.

### 6.4 — Trois modes de sur-détection distincts

À traiter séparément, ils n'ont ni la même cause ni le même correctif :

1. **Végétation basse en terrain ouvert praticable** — le mode principal (53,7 % du surplus
   Airelles, 55,9 % Kilemäed). Pas de correctif connu par le signal seul.
2. **Débordement sous couvert sur 405 (forêt courable)** — 18,6 % sur Airelles. Canopée présente,
   donc distinct du mode 1. **Non répliqué** faute de terrain de forêt fermée autre que Grimbosq.
3. **Zones humides / rocheuses** — ~19 % du classifié sur Kilemäed. Marais codés en bleu par
   ISOM mais vus comme végétation basse par le LiDAR. **Correctif identifié** : masque
   hydrographie externe (BD TOPO `zone_humide`/`surface_hydrographique` en France, équivalent
   Maa-amet en Estonie), en soustraction avant généralisation — même interface que le masque
   routes/haies déjà prévu.
   > ⚠️ **Ne pas utiliser les polygones FFCO comme masque** : c'est circulaire (on utiliserait la
   > réponse pour produire la réponse) et inopérant en production, où aucune carte n'existe.
   > Usage légitime unique : mesurer **une fois** la borne supérieure du gain atteignable.

### 6.5 — Hypothèses réfutées (ne pas rouvrir sans élément nouveau)

Documenter les réfutations évite de refaire le chemin. Chacune a un test associé.

| Hypothèse | Test qui l'a tuée | Verdict |
|---|---|---|
| Blob = fusion trop agressive | Run de contrôle `fusion_distance[406]=0` : blob de 75 ha toujours présent | Réfutée — cause en amont (σ) |
| Branches basses de résineux (halos sous canopée) | Intersection spatiale 406 × légende FFCO : 53,7 % du surplus en **terrain découvert** | Réfutée |
| Masque de canopée (`count_high/total`) | Séparabilité : Airelles open 0,441 vs veg_406 0,438 ; Grimbosq médiane qui **monte** à l'érosion ; contexte spatial 50–100 m sans séparation | Réfutée localement **et** régionalement |
| Intensité comme discriminant universel | Airelles : distributions superposées (30,7 vs 29,0 sur IQR ~35) | Réfutée **sur lande** |

**Méthode réutilisable** issue de ces tests : avant toute conclusion sur un attribut de retour,
vérifier sa **dépendance à l'angle de visée / ligne de vol** (r et ratio de variance
inter-lignes vs inter-classes). Sans ce contrôle, une piste peut être enterrée pour un artefact.

### 6.6 — Chantiers végétation ouverts, par priorité

1. **Masque zones humides** (mode 3) — le moins cher, gain net, testable sur les 3 terrains.
   Couche externe uniquement.
2. **Ordre du pipeline de généralisation** (§6.2) — corriger `remove_small` / `merge_proximity` /
   `remove_isolated`, re-tester `fusion_distance` à 4 m avec σ=1.0.
3. **Kuti (EE, 16,6 km², 108 polygones Forest)** — seul candidat identifié pour valider le
   comportement sous couvert dense ailleurs qu'à Grimbosq, et donc pour répliquer le mode 2.
   Workflow identique à Kilemäed (`readers.las`, `isom_en.yaml`, quelques entrées `skip` à
   ajouter). Faisabilité HAG déjà levée sur données Maa-amet (voir 6.7).
4. **Critère de fiabilité automatique** — que le pipeline signale lui-même les terrains hors
   domaine plutôt que de produire du 406 faux en silence. Piste : variance spatiale de
   `count_high`. **Contrainte : calculable sans carte de référence.** Calibrable seulement après
   Kuti (aujourd'hui : 3 terrains, mais un seul en forêt fermée).
5. **Intensité en pondération sur terrain forestier** — signal de réflectance **confirmé** sur
   Grimbosq (delta ~200 unités stable sur tous les bins de couvert, donc pas de l'atténuation),
   mais recouvrement des distributions important. Exploitable en variable auxiliaire, pas en
   seuil dur. À tester : est-ce que l'ajouter à `density_hag` améliore la classification ?
6. **Lissages résiduels non testés** : `median_size: 9` et `majority_radius: 3` font une partie du
   même travail de comblement que σ. Le vrai correctif est peut-être « moins de lissage » en
   général. Un run coûte peu.
7. **Inspection OOM à l'échelle d'impression** — dette : le rapport 3875 polygones pipeline /
   420 FFCO sur Airelles n'a jamais été regardé au 1:10 000. `max%406` valide l'absence de nappe,
   pas la lisibilité.

### 6.7 — Portabilité hors France (acquis Estonie)

Faisabilité `hag_nn` à faible densité **levée par la mesure** sur données Maa-amet :
densité réelle 3,77 pts/m² (1,69 sol, 44,8 % de sol), relief 11,6 m, erreur d'interpolation sol
**4,9 cm** (k=8) / 6,6 cm (k=1) — très loin du seuil de bande à 0,30 m. Résolution 1 m directement
utilisable, `hag_count=8` conservé, `readers.las` au lieu de `readers.copc`.

**Vigilance à reporter dans toute analyse estonienne :** contamination de la zone de bascule
HAG[0,30:0,50] = **10,2 % du contenu de la bande végétation**. Elle frappe proportionnellement plus
les zones ouvertes (bande mince) que sous couvert. Contrôle disponible : run en variante
`min_h=0,50` — lire la baisse **différentielle** entre classes ouvertes et couvertes, pas la baisse
absolue.

### 6.8 — Ce que le plan v2 affirmait et que la mesure réfute

- *« Le lissage pré-seuillage est la seule source d'arrondi organique, principal levier de naturel »*
  → **Faux.** C'est le principal générateur de nappes artificielles. σ=1.0, pas 3.0.
- *« KP est déjà calibré pour la franchissabilité à partir des hauteurs de points »*
  → **Non démontrable.** Dans la bande 0,3–3 m, aucune calibration ne peut séparer ce que le signal
  ne distingue pas (Airelles). Le plan posait comme acquis le problème central du projet.
- *Ordre majoritaire → sieve → ouverture*
  → Ne décrit pas le pipeline réellement en production (§6.2), qui a par ailleurs un bug d'ordre
  propre à corriger.

Restent valides du plan v2 : le principe « maximum en espace raster », le polygonize global unique,
la mosaïque avant vectorisation, le cap de résolution à 1 m, la simplification de couverture
topologique, et la batterie de golden tests.

---

## PHASE 1 — Spike de validation — VERROU

**Objectif révisé** : prouver la chaîne complète sur Grimbosq, terrain **où le pipeline est
mesuré comme fiable** — pas un terrain au hasard.

1. Karttapullautin sur les dalles Grimbosq en cache → sorties relief (format à découvrir en Ph.0).
2. Végétation : `vegetation.gpkg` **existant** (σ=1.0) — déjà produit, rien à recalculer.
3. Import des deux dans OOM avec CRT.
4. 🧑 **Contrôle humain** : relief symbolisé via CRT + végétation vectorisée plausible,
   **à l'échelle d'impression 1:10 000**.

**Définition de terminé :** relief et végétation apparaissent ensemble, symbolisés et
géoréférencés, dans OOM.

---

## PHASE 2 — Squelette / Docker / config

Inchangée par rapport au plan v2 : arborescence, `Dockerfile` (KP + PDAL/GDAL, **versions
épinglées**), `config.yaml` (EPSG:2154, échelle cible, emprise max = rejet bloquant),
`symbols_isom.yaml`, `assets/`, `pytest`.

**Ajout :** `scripts/mappings/*.yaml` (conventions cartographiques) est déjà en place et doit
être traité comme partie de la config, pas comme un script.

---

## PHASE 3 — Acquisition données (`fetch.py`) — stub

Inchangée. Le durcissement du plan v2 reste intégralement valide :
**pagination WFS** (piège n°1 — donnée tronquée en silence ; test : objets récupérés =
`resultType=hits`), retry + backoff exponentiel, cache local par (emprise, couche, date),
préférence aux archives départementales préempaquetées quand elles existent.

**Ajout issu de l'expérience :** garde-fou de **comptage de tuiles**. Un bug réel a été rencontré —
4 dalles présentes sur disque ont été ignorées silencieusement par PDAL, produisant 30 % de nodata
et des chiffres plausibles mais faux. Comparer systématiquement tuiles trouvées vs tuiles lues, et
**échouer bruyamment** si les deux diffèrent.

---

## PHASE 4 — Moteur LIDAR (`run_engine.py`) — stub

Wrapper KP (relief) + PDAL (rasters de densité). Durcissement du plan v2 conservé : traitement
dalle par dalle, cap 1 m, version KP épinglée, **test d'existence des calques DXF attendus** (le
CRT casse silencieusement sinon).

**Ajout :** garde-fou de **fraîcheur** — un pipeline qui détecte une dépendance manquante ou un
artefact périmé doit **s'arrêter**, pas continuer sur un fichier obsolète. Bug rencontré :
`run_terrain.py` a enchaîné la généralisation sur un classifié de 14 tuiles alors que le PDAL
venait d'en produire 16, sortant 931 polygones parfaitement plausibles et entièrement faux.
Implémenté (`mtime` check) — à conserver dans le module définitif.

---

## PHASE 5 — Relief & anthropique = CÂBLAGE CRT

Inchangée. Intégration, pas d'algorithme. Si ça demande plus que du mapping déclaratif → alerte
sur-ingénierie.

---

## PHASE 7 — Assemblage (`assemble.py`) — stub

**Architecture à trancher en Phase 0** selon le format de sortie de KP :
- **Si KP sort un `.omap`** → ouvrir son XML, retirer ses objets de végétation, injecter les
  nôtres, réenregistrer. Nettement plus court.
- **Si KP sort du DXF** → génération `.omap` complète, couche par couche, avec ordre de dessin.

Clip végétation aux plans d'eau et routes ; EPSG:2154 homogène ; déclinaison magnétique inscrite.

---

## PHASE 8 — Packaging OOM (`export_oom.py`) — stub

Objectif du plan v2 conservé (base techniquement irréprochable, finition cartographique assumée),
avec le **gate de validité bloquant** : 0 géométrie invalide, couverture végétation valide, 0
feature sans `symbol`, CRT ne référençant que des symboles existants, tout en EPSG:2154.

**Ajout obligatoire — mention du domaine de validité.** L'export doit inclure, dans le README
d'import et dans le rapport QA, une indication du domaine de fiabilité : le pipeline est calibré
pour la **forêt tempérée à couvert structuré** et **ne l'est pas** pour les landes basses en
terrain ouvert. Livrer sans cette mention serait la même faute que produire des chiffres sans
dénominateur.

---

## PHASE 9 — QA (`qa.py`) — stub

Rapport texte + aperçus PNG. **Ajouts :**
- `domain_confidence: high | low | unknown` dans `run_metadata.json`, alimenté par le critère
  de §6.6.4 une fois calibré.
- Report des métriques de structure qui ont servi tout au long : couverture % et
  **concentration du plus gros polygone** (`max%406`). La seconde est celle qui a révélé le
  problème de nappe alors que la première semblait acceptable — les deux, jamais l'une seule.

---

## PHASE 10 — Bout-en-bout (`main.py`) + recette

Inchangée. Critères d'acceptation v1 du plan v2, **plus** :
- Le rapport indique le domaine de validité estimé du terrain traité.
- La documentation ne promet pas un résultat uniforme sur tout type de terrain.

---

## Méthode — ce qui a fonctionné, à conserver

Ces règles ne sont pas théoriques : elles ont produit tous les résultats de la calibration.

- **Une variable par run.** Le protocole factoriel (résolution × métrique) a évité de tuer une
  bonne idée pour un mauvais motif.
- **Toujours un run de contrôle.** `fusion_distance=0` a réfuté l'hypothèse dominante et
  redirigé toute la session. Le contrôle vaut plus que le test.
- **Vérifier les dénominateurs.** Un « facteur ×7 » s'est révélé être une division par la
  mauvaise emprise (2501 ha au lieu de 389). Même piège, deux fois.
- **Distinguer fait vérifiable et interprétation causale.** Le comptage de points par cellule se
  lit en 5 minutes sur des rasters existants ; son effet supposé sur la variance est une
  hypothèse à tester.
- **Poser la prédiction avant de mesurer.** Fait pour Kilemäed, avec critères de confirmation, de
  réfutation, et explicitement **hors test**.
- **Une réfutation propre vaut une confirmation.** Quatre hypothèses éliminées en une session,
  chacune avec son test — c'est ce qui a permis d'arriver à la cause réelle.

---

## Hors périmètre v1

ML · moteur LIDAR maison · écriture directe `.ocd` · objets ponctuels terrain · franchissabilité ·
limites précises de végétation · zones d'accès interdit · BD FORÊT · GUI · parcours · France entière.

---

### Ordre d'exécution recommandé

1. **Phase 0** — lancer Karttapullautin sur Grimbosq, inventorier les sorties. *Verrou : rien
   d'autre du volet livrable ne peut être conçu sans ça.*
2. **Phase 1** — spike sur Grimbosq avec la végétation existante, contrôle humain dans OOM.
3. **Phases 7 et 8** — assemblage et export, architecture décidée par la Phase 0.
4. En parallèle, si le temps le permet : chantiers végétation §6.6 par ordre (masque humide,
   ordre du pipeline, Kuti).

Le volet végétation a une correction validée et un domaine mesuré. Le volet livrable n'a rien.
C'est là que se trouve maintenant le rendement marginal le plus élevé.
