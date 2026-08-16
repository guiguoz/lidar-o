# Plan d'amélioration — rendu végétation Ovector (focus 406)

> **SUPERSEDED par `PLAN_execution_v3.md`** — conservé pour l'historique du raisonnement.
> Le cheminement du cadrage sémantique (plafond LiDAR vs cartographe FFCO) et les critiques
> successives restent valides comme archive ; ne pas exécuter ce document comme plan actif.

> Document destiné à Claude Code. Contexte : pipeline co-vector-fr (IGN LiDAR HD → polygones ISOM 406/408/410).
> Problème central : le 406 (vert clair, végétation basse / sous-bois) est la classe la moins
> stable — polygones excédentaires par rapport au corpus FFCO en feuillus ouverts (limite
> documentée dans le README), sous-représentation possible sous couvert dense, taches diffuses
> fragmentées. « Excédentaire par rapport au corpus » ≠ « faux » : voir cadrage ci-dessous.
> Référence comparative principale : **Blaze** (github.com/Trailblaze-Software/Blaze),
> module `src/lib/vegetation/` (vegetation.hpp, vegetation_polygon.hpp).

## Cadrage préalable — le plafond sémantique (à garder en tête pour tout le document)

> **Remarque de fond — probablement l'angle mort le plus important du plan
> initial.** Le LiDAR répond à la question « où y a-t-il de la matière végétale dans cette bande
> de hauteur ? ». Le cartographe FFCO répond à une question différente : « où cette végétation
> ralentit-elle ou bloque-t-elle suffisamment un orienteur pour mériter un symbole ISOM ? ».
> Fougères, houx, jeune régénération, ronciers : le capteur les détecte très bien en densité de
> points ; le cartographe choisit parfois de ne pas les symboliser — parce que la course reste
> possible, parce que la zone est trop petite pour être significative à 1:10 000, ou par un
> jugement de terrain qu'aucune métrique de densité ne capture.
>
> Conséquence concrète : **il existe un plafond sur ce qu'une IoU face aux cartes FFCO peut
> mesurer**, indépendant de la qualité de l'algorithme. Un NRD parfait, une grille parfaitement
> calibrée, une généralisation parfaite ne fermeront pas cet écart sémantique — seule une
> vérification terrain, ou l'ajout d'un signal qui approche le jugement du cartographe (§3.1
> classification IGN native, §3.6 heuristiques), peut le réduire, jamais complètement.
>
> Implication pratique pour la suite du document : traiter tout gain d'IoU comme une amélioration
> relative à un plafond inconnu, pas comme une convergence vers 100 %. Un plateau de mesure ne
> signifie pas forcément un pipeline mal calibré — il peut signifier qu'on a atteint le plafond
> sémantique plutôt qu'une limite technique.

---

## 0. Diagnostic — pourquoi le 406 est structurellement fragile dans le pipeline actuel

Quatre pistes diagnostiques, à des degrés de confiance très différents (précisés dans chaque
sous-section), identifiées en croisant le code d'Ovector, Blaze, Karttapullautin et la littérature
(Trier 2015, Schaad 2017) :

### D1 — Hypothèse H1 : la métrique ratio serait biaisée par l'occlusion du couvert (non démontré sur les données d'Ovector)
`process_hag.py` calcule `ratio = retours HAG [0.3–3 m] / total retours`. Le dénominateur inclut
les retours de canopée (> 3 m). Le raisonnement physique suggère :
- **Sous couvert dense** : la canopée intercepte la majorité des impulsions → dénominateur gonflé →
  ratio artificiellement bas → sous-bois réel (406/408) potentiellement invisible.
- **En feuillus ouverts / clairières** : peu de canopée → presque tous les retours tombent dans la
  bande basse → ratio élevé → possibles taches 406 excédentaires par rapport au corpus FFCO.
  Cohérent avec la limite documentée dans le README (« Open deciduous forests may produce more
  polygons »), mais **ce lien de cause à effet n'est pas établi expérimentalement sur les données
  d'Ovector** — seulement plausible. Et « excédentaire par rapport à la carte » ne veut pas
  nécessairement dire « erreur du capteur » (cf. cadrage préalable) : la végétation peut être
  physiquement là et volontairement non symbolisée par le cartographe.

> **Limitation :** cette section doit être lue comme une hypothèse
> (H1) à tester (cf. Phase 1, Étape B), pas comme un diagnostic acquis. Les seules observations
> vraiment établies dans ce document sont les résultats mesurables via `measure_corpus.py` sur
> Grimbosq et Airelles ; tout constat évoqué sur d'autres terrains (Tourouvre, Montmirel ou
> autres) doit être vérifié avant d'être traité comme un fait — je n'ai pas pu confirmer ces
> résultats dans le dépôt inspecté.

> **Note (échange Facebook Guillaume Lemiègre / Terje Wiig Mathisen, auteur du pipeline JWOC 2015) :**
> l'auteur d'Ovector a *déjà* effectué la bascule comptage brut → ratio normalisé, pour une raison
> proche (artefacts de lignes de vol). Le ratio actuel n'est donc pas une erreur de conception
> mais un choix déjà mûri. H1 propose un **raffinement possible** de ce choix (exclure la canopée
> du dénominateur), pas une remise en cause de la bascule elle-même.

Blaze utilise une métrique conditionnée par la pénétration (`get_blocked_proportion` dans
`vegetation.hpp`) : `ratio = in / (in + below)`, retours au-dessus de la bande exclus du
dénominateur — la métrique NRD (Normalized Relative Density) classique en foresterie. Terje
(JWOC 2015) calcule indépendamment des histogrammes pondérés par noyau gaussien plutôt qu'une
métrique de comptage brute, et passe par un filtre passe-bas avant vectorisation — une
convergence de deux implémentations indépendantes vers une logique voisine, ce qui est un indice
en faveur de H1, **pas une preuve**.

> **Réserve importante (limite méthodologique) :** Blaze ne combine pas seulement le NRD — il combine
> aussi grille dédiée, pondération gaussienne, low-pass et isolignes. Rien ne permet aujourd'hui
> d'isoler la part du NRD dans une éventuelle supériorité de Blaze (dont la qualité relative n'est
> elle-même pas mesurée ici, seulement inspectée sur le code). Attribuer un gain au NRD seul avant
> de l'avoir testé isolément (Phase 1, Étape B) serait un raisonnement à variable confondue —
> exactement ce que la discipline expérimentale du projet doit éviter.

### D2 — Densité de points par cellule : un fait à vérifier en 5 minutes, pas une hypothèse
Deux affirmations de nature différente, à ne pas traiter avec le même niveau d'incertitude :

- **Fait directement vérifiable, avant même l'Étape A** : le nombre de retours par cellule de 1 m
  dans la bande 0.3–3 m se lit directement dans `total_count.tif` / le raster HAG déjà produits par
  le pipeline actuel — quelques lignes (`rasterio` + `np.percentile`) suffisent à sortir la
  médiane et les percentiles réels sur Grimbosq et Airelles. Ce n'est pas une supposition sur la
  densité LiDAR HD en général, c'est une mesure directe sur les données du projet. **À faire en
  tout premier**, avant de lancer quoi que ce soit d'autre dans ce document.
- **Interprétation causale, elle, encore hypothétique** : que ce faible nombre de points explique
  la variance du ratio, et donc le recours à un lissage important (`gaussian_sigma=3` +
  `median_size=9`) qui dilue les petites taches 406. Ce lien n'est pas démontré — il est cohérent
  avec le choix de grille dédiée de Blaze (`vegetation_grid_resolution: 3.0`, ~90 pts/cellule
  contre quelques points à 1 m), mais reste à confirmer par l'Étape A (Phase 1) sur les données
  d'Ovector, pas à admettre par analogie.

### D3 — Hypothèse H2 : la normalisation p95 *par scène* pourrait limiter la portabilité des seuils
`process_hag.py` divise par le p95 de la scène avant seuillage. Deux terrains différents → même
seuil 0.20 ≠ nécessairement même densité physique. Corrélation plausible avec les allers-retours
de calibration T1–T10, pas de lien de cause démontré.

> **Précision (référence externe, Terje Wiig Mathisen, auteur du pipeline JWOC 2015) :** Terje
> normalise lui aussi ses histogrammes de
> comptage (sur une plage fixe 0–255) — la normalisation en soi n'est donc pas le problème, tous
> les pipelines sérieux du domaine en font une. **Le problème est que la normalisation d'Ovector
> est recalculée par terrain** (p95 local), alors que Terje calibre ses valeurs par défaut sur un
> référentiel fixe, accumulé sur 500 à 1000 km² de cartes traitées, et ne fait de l'ajustement fin
> que pour les projets qui l'exigent (JWOC). Reformulation de la recommandation : ne pas supprimer
> la normalisation, mais **arrêter de la recalculer terrain par terrain** — la remplacer par une
> référence fixe (percentile mesuré une fois sur le corpus de calibration, gelé dans `config.yaml`
> comme une constante physique, pas recalculé à chaque `run_terrain.py`). La métrique NRD (D1),
> déjà bornée [0,1] par construction, réduit de toute façon le besoin de cette étape.

> **Limitation :** cette section reste elle aussi une hypothèse (H2) tant
> qu'elle n'a pas été mesurée — pas une conclusion. Protocole opérationnel explicite, à isoler de
> tout changement de métrique : voir Phase 1, Étape C (T11 = percentile fixe, T12 = aucune
> normalisation, comparés au témoin p95 local, à métrique et résolution fixées).

### D4 — Classification dure → polygonize → escalier de pixels → généralisation agressive
Le seuillage produit un raster uint8, `gdal.Polygonize` crée des contours en marches d'escalier,
que DP 2 m + Chaikin doivent ensuite réparer. Blaze trace des **isolignes (marching squares) sur la
grille flottante lissée** (`generate_contours_at_heights` aux valeurs de seuil) : frontières
sub-pixel, déjà lisses, fidèles au seuil exact. Moins de post-traitement destructif nécessaire.

Cause secondaire : une bande unique 0.3–3 m mélange deux réalités ISOM distinctes —
le sous-bois (~0.3–1.3 m, affecte la course : 406, ou 407 si bonne visibilité) et la végétation
moyenne (~1.3–4 m, affecte la visibilité et la pénétrabilité : 408/410). Blaze et le workflow
tmsw.no (JWOC 2015) séparent les bandes.

---

## Phase 1 — Isoler chaque variable

**Objectif : corriger D1/D2/D3 en respectant strictement « une variable à la fois », sans toucher
au moteur de généralisation (gelé v1).**

> **Avertissement méthodologique :** la version précédente de
> cette phase testait résolution, métrique, lissage et normalisation en même temps — ce qui viole
> le principe énoncé plus bas dans ce document (« une phase = une PR = une variable »). Corrigé
> ci-dessous. Piège additionnel : résolution et métrique **interagissent**.
> Le NRD a besoin d'un nombre minimal d'impulsions par cellule pour être stable (garde `N_min`) ;
> le tester à la résolution actuelle de 1 m risque de le faire échouer pour la mauvaise raison
> (pas assez de points, pas parce que la formule est mauvaise). D'où l'ordre ci-dessous, qui fixe
> la résolution avant de faire varier la métrique — et, si le budget de calcul le permet, un petit
> plan factoriel {ratio, NRD} × {1 m, résolution retenue} plutôt qu'un enchaînement purement
> séquentiel.

### Étape A — Résolution seule
Changer uniquement `vegetation.grid_resolution_m` (1 → 2 → 3 m), **métrique ratio actuelle
inchangée**, lissage et seuils inchangés (adapter seulement le rayon en nombre de cellules pour
garder une distance physique comparable). Mesurer avec `measure_corpus.py` sur Grimbosq et
Airelles. Retenir la résolution qui maximise l'IoU sans dégrader 408/410.

### Étape B — Métrique seule, résolution contrôlée
À la résolution retenue en A (et si possible aussi à 1 m, pour vérifier l'interaction),
comparer **sur la même bande unique 0.3–3 m qu'aujourd'hui** (pas encore de séparation low/mid) :
- ratio actuel = HAG / total retours ;
- NRD = retours_bande / (retours_bande + retours_sous_bande), retours au-dessus de la bande
  exclus du dénominateur (`get_blocked_proportion` façon Blaze), garde `N_min` (défaut 8) — en
  dessous → NoData, pas 0, comblé par moyenne de voisinage sur un rayon de 2 cellules ; exporter
  aussi `confidence.tif` (nombre d'impulsions pénétrantes) pour la QA.

Ceci isole strictement la question « ratio vs NRD change-t-il quelque chose ? », sans la mélanger
avec la séparation des bandes (Étape D) — **contrairement à la version précédente de ce plan**,
qui confondait les deux dans le même changement. Résultat traité comme hypothèse H1 à confirmer
(cf. D1), pas comme acquis même si B montre un gain.

### Étape C — Normalisation seule (protocole T11/T12)
À résolution et métrique gagnantes des étapes A/B fixées, comparer trois variantes :
- T11 : métrique retenue + normalisation par percentile **fixe**, gelé dans `config.yaml`
  (mesuré une fois sur le corpus de calibration, pas recalculé par terrain) ;
- T12 : métrique retenue **sans aucune normalisation** ;
- témoin : normalisation p95 locale actuelle.

Si ni T11 ni T12 ne bat le témoin, garder la normalisation locale — ne pas la supprimer par
principe (cf. H2, D3).

### Étape D — Séparation des bandes low/mid (hypothèse distincte, spécifique au 406)
**Seulement après A+B+C.** Tester séparément si distinguer sous-bois (0.3–1.3 m, impact course)
et végétation moyenne (1.3–4.0 m, impact visibilité/pénétrabilité) améliore *spécifiquement* la
discrimination 406 vs 408/410 — sans quoi une bande unique continue de mélanger deux réalités
ISOM différentes (cf. D4). Produire `count_below`, `count_band_low`, `count_band_mid` ; calculer
`nrd_low` et `nrd_mid` séparément (module `src/metrics.py`) ; classer 406 depuis `nrd_low`,
408/410 depuis `nrd_mid`. Comparer contre le meilleur résultat de C (bande unique) — cette étape
ne se justifie que si elle améliore le 406 sans dégrader 408/410.

### Validation — à chaque étape, pas seulement à la fin
`measure_corpus.py compare` sur Grimbosq ET Airelles après **chaque** étape (A, B, C, D), version
courante vs précédente, avec les mêmes réglages de généralisation en aval. Métriques à ajouter au
script si absentes : IoU par classe, écart de surface par classe (%), ratio nombre de polygones
sortie/référence. Critère de succès global : IoU 406 en hausse sur les deux terrains, réduction
nette des polygones 406 excédentaires par rapport au corpus FFCO en feuillus ouverts (Grimbosq),
sans régression 408/410 — **gardé en
tête que ce gain est mesuré contre un plafond sémantique inconnu (cf. Cadrage préalable), pas
contre une cible à 100 %.**

## Phase 2 — Polygonisation par isolignes (corrige D4) — **rétrogradée, piste à traiter avec prudence**

> **Avertissement (référence externe, choix de conception déjà fait par l'auteur d'Ovector) :**
> l'auteur d'Ovector a explicitement choisi de
> classifier le raster puis polygoniser **chaque classe indépendamment**, précisément pour
> **éviter** l'emboîtement clair/moyen/foncé — et c'est exactement l'objection que Terje soulève
> face à l'approche par isolignes/contours de son propre interlocuteur dans le fil. La Phase 2
> telle que décrite initialement (isolignes façon Blaze) risque donc de réintroduire un problème
> d'imbrication qu'Ovector a déjà délibérément écarté par son architecture. **Cette phase passe de
> « amélioration structurelle recommandée » à « piste à tester avec prudence, seulement si
> l'escalier de pixels reste visuellement problématique après import OOM une fois la Phase 1
> validée »**, et seulement en évaluant explicitement le compromis emboîtement vs marches
> d'escalier (§2.2 ci-dessous) plutôt qu'en l'important tel quel.

**Ne lancer qu'après validation Phase 1** (les seuils changent de signification, inutile de
recalibrer deux fois), et seulement si le besoin est confirmé.

2.1. Nouveau `stage_polygonize_isolines` dans `src/vegetation.py` : `skimage.measure.find_contours`
     (ou `matplotlib.contourf` → chemins fermés, ou `gdal.ContourGenerateEx` avec
     `POLYGONIZE=YES`) sur la grille flottante lissée, aux valeurs de seuil du preset.
     Attention aux contours ouverts en bord de raster : padder la grille avec une valeur < seuil
     avant traçage pour forcer la fermeture (astuce standard).

2.2. Imbrication : les isolignes produisent des polygones emboîtés (le 410 est inclus dans le 408,
     etc.). Deux options — trancher par test :
     - a) **Garder l'emboîtement** et laisser l'ordre de dessin ISOM faire le travail dans OOM
       (Blaze gère un `draw_priority` 406 < 408 < 410). Plus simple, surfaces exactes à l'écran.
     - b) Soustraction booléenne (`shapely.difference`) pour livrer des couches disjointes,
       comme aujourd'hui. Blaze implémente les deux (cf. `subtract_from_polygon`).
     Le README revendique l'indépendance par classe comme choix de design : l'option (a) le
     remet en cause, en discuter dans le rapport de test.

2.3. Alléger la généralisation en aval : avec des frontières sub-pixel, DP peut passer de 2.0 m à
     ~1.0 m et Chaikin devenir optionnel. Reprofiler `grimbosq_v0` → `grimbosq_v2`.

2.4. Reprendre de Blaze le **filtrage par aire nette** (extérieur − trous,
     cf. `polygon_net_area_m2`) : le `stage_remove_small` actuel utilise `geometry.area` qui,
     pour un anneau fin autour d'une grande clairière, surestime la taille et garde des
     polygones qui devraient sauter.

## Phase 3 — Pistes non explorées (à instruire, une par une, derrière des flags)

3.1. **Classification IGN native comme prior — et proxy low-cost d'« accord physique ».**
     LiDAR HD livre les classes ASPRS (3/4/5 = végétation basse/moyenne/haute, produites par
     l'algo IGN, calibré indépendamment des conventions FFCO). Croiser : cellules où NRD dit
     « 406 » mais classe IGN dit « sol/autre » → suspecte (branches basses, talus). Coût quasi nul
     (un `filters.range` de plus), gain potentiel en réduction des cas ambigus.
     > Lien avec 3.8 ci-dessous : cette classification IGN, indépendante de la carte FFCO, sert de
     > second regard « physique » à coût nul — utile en attendant (ou à défaut) d'un vrai relevé
     > terrain.

3.2. **Saisonnalité des blocs LiDAR HD.** L'acquisition IGN s'étale sur plusieurs années et
     saisons ; en feuillus, feuilles-on/feuilles-off change radicalement les retours 0.3–3 m.
     Récupérer la date d'acquisition dans les métadonnées de dalle (`phase0_recon.py` sait déjà
     interroger la Géoplateforme) et l'écrire dans le rapport QA ; à terme, presets
     `feuillus_ete` / `feuillus_hiver` sélectionnés automatiquement. Piste probablement décisive
     pour la portabilité inter-terrains — personne ne la traite dans les outils existants.

3.3. **Distinction 406 vs 407/409 (sous-bois bonne visibilité).** ISOM représente le sous-bois
     courable-mais-lent avec bandes vertes (407/409) quand la visibilité reste bonne. Proxy
     LiDAR : `nrd_low` élevé + `nrd_mid` faible ⇒ candidat 407 plutôt que 406. À prototyper en
     sortie séparée `veg_407.geojson` que le cartographe garde ou jette.

3.4. **Masque routes/haies BD TOPO** (déjà planifié dans le README) : buffer des
     `troncon_de_route` + couche `haie`, soustraction avant généralisation. À faire tôt, ça
     nettoie beaucoup d'artefacts 406 linéaires en lisière (effets de bord LiDAR près des routes —
     ici, contrairement au cas 3.6, plausiblement un artefact de capteur/traitement plutôt qu'un
     écart de convention cartographique).

3.5. **Calibration automatique des seuils contre le corpus FFCO.** Étendre `measure_corpus.py`
     avec un mode `optimize` : recherche par grille (ou Nelder-Mead) des seuils maximisant l'IoU
     moyenne sur les terrains de référence, avec validation croisée un-terrain-exclu. Ce n'est
     pas du ML — c'est l'automatisation de T1–T10, en respectant la doctrine du projet
     (les cartes FFCO mesurent, elles n'entraînent pas un modèle opaque).

3.6. **Heuristiques de recouvrement dur (technique décrite par Terje Wiig Mathisen / mapant.no).**
     Avant tout seuillage continu, appliquer 2-3 règles déterministes de garde-fou, cheap et
     robustes, du type « si ≥ 98 % des retours sont au sol → toujours 401/403 ouvert, quel que
     soit le NRD calculé » ou « la classe blanc/jaune vs vert se tranche d'abord sur la somme des
     bandes vertes, avant nuance interne ». Objectif : filtrer en amont les 406 excédentaires de
     bordure de clairière (cas où le NRD, même corrigé en D1, reste ambigu sur de très petits
     échantillons — et où la frontière physique/cartographique du cadrage préalable rend le
     jugement intrinsèquement flou, pas seulement bruité).
     Ne remplace pas la métrique NRD — s'ajoute en pré-filtre, avant classification par seuils.

3.7. **Coutures de dalles.** Vérifier qu'aucun seuillage/lissage n'est fait dalle par dalle sans
     zone tampon (Blaze soigne ça : `trim_vege_polygons_to_extent` avec snap des sommets aux
     bords). Si le pipeline traite les COPC fusionnés, documenter la limite mémoire ;
     sinon, tampon ≥ rayon de lissage × résolution.

3.8. **Double niveau de validation — accord cartographique vs accord physique (piste de fond,
     non bloquante pour les phases 1-2).** `measure_corpus.py` ne mesure aujourd'hui qu'un seul
     niveau : pipeline ↔ carte FFCO (« accord cartographique »). Or le cadrage préalable de ce
     document explique que la carte FFCO n'est pas une vérité physique — un second niveau,
     pipeline/LiDAR ↔ réalité terrain (« accord physique »), manque structurellement :

     ```
     végétation physique réelle → LiDAR → pipeline → carte
     ```

     Aujourd'hui seule la flèche pipeline→carte est mesurée. Une vraie mesure d'accord physique
     nécessiterait des relevés terrain géoréférencés indépendants — **donnée que le projet n'a pas
     actuellement** (le README ne liste que LiDAR HD + BD TOPO + cartes FFCO, aucun plan de
     sondage terrain). Ne pas bloquer les phases 1-2 sur cette absence. Deux options à coût
     croissant, à instruire séparément :
     - **Court terme, coût nul** : utiliser 3.1 (classification ASPRS IGN, indépendante des
       conventions FFCO) comme proxy physique partiel — pas un vrai relevé terrain, mais un second
       regard décorrélé de la carte de référence, à coût zéro.
     - **Long terme, coût réel** : si le projet grandit, envisager un petit protocole de sondage
       terrain ciblé (quelques placettes GPS par terrain, densité de végétation mesurée au sol) sur
       les zones où pipeline et FFCO divergent le plus — précisément pour trancher si la
       divergence est un défaut du pipeline ou un choix cartographique légitime.

## Ordre, garde-fous, critères d'arrêt

- Une phase = une PR = une comparaison `measure_corpus` avant/après sur **les deux** terrains
  de calibration. Ne jamais empiler deux changements de métrique dans le même test.
- Conserver `v1_vegetation_baseline` intact et comparable (le mode `ratio` reste dans la config).
- Chaque nouveau paramètre va dans `config.yaml` avec valeur par défaut + commentaire daté,
  conformément au style existant.
- Critère global de réussite : sur Grimbosq, le surplus de polygones 406 en feuillus ouverts
  (limite connue, formulé comme écart au corpus FFCO, pas comme erreur du capteur — cf. cadrage)
  doit disparaître ou être divisé par ≥ 3 sans perte d'IoU sur 408/410 ; sur Airelles, pas de
  régression.

---

## Changelog (traçabilité des révisions — hors texte principal, pour référence)

- **v1 (version initiale)** : diagnostic D1–D4, Blaze comme référence de comparaison, Phase 1
  (métrique NRD + grille dédiée), Phase 2 (isolignes), Phase 3 (pistes non explorées).
- **v2 (suite à un échange public Guillaume Lemiègre / Terje Wiig Mathisen, auteur du pipeline
  JWOC 2015)** : Phase 2 rétrogradée (l'auteur d'Ovector a déjà choisi la polygonisation
  indépendante par classe pour éviter l'imbrication) ; D1 nuancée (le ratio actuel est déjà une
  bascule mûrie, pas une erreur de conception) ; D3 nuancée (la normalisation en soi n'est pas le
  problème, c'est son recalcul par terrain) ; ajout des heuristiques de recouvrement dur (3.6).
- **v3 (suite à une première revue croisée externe)** : Phase 1 restructurée en étapes A/B/C/D
  strictement isolées (résolution → métrique → normalisation → séparation de bandes), avec un
  test factoriel pour l'interaction résolution×métrique ; D1/D3 requalifiées en hypothèses
  (H1/H2) ; ajout du cadrage sémantique (végétation physique vs cartographique) ; réserve posée
  sur des données terrain (Tourouvre, Montmirel, T11/T12) non vérifiables dans le dépôt inspecté.
- **v4 (suite à une seconde revue croisée externe)** : D2 scindée entre fait directement
  vérifiable (comptage de points par cellule, à checker en 5 min sur les rasters déjà produits)
  et interprétation causale encore hypothétique ; reformulation systématique de « faux polygones »
  en « polygones excédentaires par rapport au corpus FFCO » ; ajout de la piste 3.8 (double niveau
  de validation, accord cartographique vs accord physique) ; allègement des mentions de provenance
  dans le corps du texte au profit de ce changelog (les citations de sources externes réelles —
  Terje Wiig Mathisen, Blaze — restent inline car elles sont des preuves, pas de l'historique
  d'édition).
