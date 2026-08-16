# Avenant n°02.1 — OmapMaker, validation multi-terrains, stabilisation du périmètre

**Objet :** intégrer OmapMaker (mémoire Hjermstad 2025) ; cadrer la validation multi-terrains ; refuser le moteur de score ; stabiliser le périmètre.
**S'applique à :** `plan_execution_claude_code_v2.md`, avenant n°01.
**Préséance :** prime sur le plan v2 et l'avenant n°01 en cas de conflit.
**Esprit :** cet avenant **réduit l'incertitude et le périmètre** ; il n'ajoute aucune infrastructure.

---

## 0. Principe de développement (règle directrice)

**Toute nouvelle idée doit démontrer qu'elle supprime une étape, réduit la complexité, ou améliore objectivement le résultat sur les dalles de validation. À défaut, elle est rejetée par défaut et inscrite au backlog de recherche, pas intégrée à la v1.**

Cette règle se suffit à elle-même : elle aurait disqualifié d'office le ML, le CO Scoring Engine et le corpus-vérité. Elle s'applique aussi aux propositions futures, d'où qu'elles viennent.

---

## 0 bis. Paramètres = données, pas code

Les valeurs de calibration vivent dans `config.yaml` / `symbols_isom.yaml` / `assets/` (CRT, jeu ISOM), **jamais en dur dans le moteur**. Toute recalibration (seuils, presets, mapping d'attributs, déclinaison) doit être possible **sans modifier le code**.

Nuance, pour ne pas tomber dans l'excès inverse (« tout configurable » = autre sur-ingénierie) : la règle vise les **valeurs**. L'ajout d'une **capacité** nouvelle (un type d'opération absent du moteur) reste un changement de code assumé — mais il **expose ses réglages en config**, il ne les enfouit pas.

---

## A. OmapMaker entre dans la reconnaissance (Phase 0 bis)

Un troisième moteur existe, à évaluer **avant** d'écrire du code de production : **OmapMaker** (Øyvind Hjermstad, Chalmers 2025, open-source, GitHub `yvind`). Contrairement à Karttapullautin et Cassini, il **écrit directement le `.omap`** géoréférencé et orienté nord magnétique, et expose déjà des seuils végétation → codes ISOM (403/406/408/410) et des falaises.

**Phase 0 bis (≈ une demi-journée, avant toute ligne de code de production)** — ajouter à `phase0_recon.py` :
- Lancer OmapMaker sur la dalle de spike. Répondre à :
  1. Son écriture `.omap` est-elle robuste et réutilisable **telle quelle** (nous épargnant la stratégie CRT + l'étape OOM manuelle) ?
  2. Son géoréférencement nord-magnétique fonctionne-t-il sur **Lambert-93 / dalle IGN** ?
  3. Comment structure-t-il ses couches (conventions, organisation) ?
  4. Sa végétation est-elle exploitable, ou seulement un seuillage brut **sans** la polygonisation propre / topologie de couverture qu'on vise ?
- **Ne pas copier ses algorithmes** ; identifier ce qui est réutilisable (écriture `.omap`, géoréférencement, structure de couches) et ignorer le reste.

**Décision du spike — passe de 3 à 4 sorties comparées** dans OOM (complète avenant n°01 §D) :
PNG KP polygonisé · PDAL maison · MNH · **OmapMaker**. Critère inchangé : laquelle place le mieux vos 2-3 vérités-terrain.

**Deux issues, toutes deux gagnantes :**
- OmapMaker fournit un export `.omap` robuste et une structure réutilisable → ces **composants sont privilégiés** pour éviter de redévelopper l'existant, et le projet se recentre sur **votre seul vrai différenciateur : la végétation**. La décision finale dépend de la qualité globale de la chaîne et de son **intégrabilité** (à vérifier : licence, architecture, maintenabilité, compatibilité Windows, activité du dépôt). ⚠️ OmapMaker est en **Rust** : « réutiliser ses composants » = l'appeler en sous-processus ou en extraire la logique, pas l'importer dans le Python — l'intégration n'est pas triviale.
- OmapMaker insuffisant → on garde l'architecture KP + vectorisation + CRT, et on récupère **l'annexe A.2 du mémoire** (convergence / déclinaison / grivation / facteurs d'échelle, équation A.1) comme référence **si** un jour vous écrivez le `.omap` vous-même au lieu de passer par OOM.

---

## B. Validation multi-terrains : oui ; moteur de score : non

Distinction nette, pour éviter le glissement « tester » → « bâtir un corpus ».

**✅ Obligatoire — valider sur 3-4 terrains français contrastés** (ex. Grimbosq/Normandie, Landes, Bretagne, un quatrième dissemblable). But : ne pas sur-ajuster les seuils à un seul site. Méthode : faire tourner le pipeline sur ces dalles, regarder les sorties, vérifier qu'un seuil calé à 50 m² ailleurs ne dérive pas. Coût : quelques heures. **Aucune infrastructure.**

**✅ Oui — cartes OCAD existantes en CONTRÔLE VISUEL** : poser une carte main de la zone à côté de la sortie dans OOM et juger « mes masses ressemblent-elles à ce qu'un cartographe a dessiné ici ? ». Contrôle de plausibilité, pas de mesure chiffrée.

**🟡 Optionnel / opportuniste — `measure_corpus.py` comme référentiel chiffré** : comparer vos distributions (aires, largeurs, fragmentation) à celles de quelques cartes OCAD **géoréférencées** n'a de valeur que si ces cartes sont alignables sur **vos** dalles (même région/échelle). Comme « la » distribution FFCO n'existe pas (autant de styles que de cartographes) et que les OCAD géoréférencées alignables sont rares, ceci est un **bonus à n'activer que si le matériel est sous la main — jamais un prérequis v1**. Rappel : le mémoire note que sa propre métrique **ne s'applique pas aux cartes faites main** (sens de parcours).

**❌ Refusé (sur-ingénierie) :** « CO Scoring Engine », score global pondéré, optimisation automatique des paramètres, apprentissage implicite des distributions, corpus érigé en « vérité FFCO », toute formulation faisant de la Phase 6 un « moteur de généralisation ». Concernant les règles : **sont refusés les systèmes de règles contextuelles nécessitant une interprétation sémantique ou un moteur de décision complexe** ; les **opérations géométriques locales et déterministes** (fusion par proximité, simplification, suppression/reclassement selon des critères configurables — déjà utilisées) restent **autorisées**.
Raison : une fonction de score n'a de sens que face à une vérité-terrain (le MNT pour les courbes) ; **la végétation n'en a aucune**. Et là où le score **est** bien fondé (les courbes), le mémoire montre que l'optimisation contre lui a **échoué** — c'est le lissage simple qui a gagné. On ne bâtit pas une infrastructure de mesure pour un objectif sans optimum définissable.

**Statistiques descriptives légères** (nombre de polygones, distribution aires/largeurs, validité de couverture) : conservées **uniquement** comme aide au réglage dans `qa.py` (Phase 9), pour comparer deux jeux de paramètres objectivement plutôt qu'à l'œil. Elles recoupent le gate de validité déjà prévu. Pas un moteur de décision.

---

## C. Principe directeur (renforcé par le mémoire)

Le mémoire Hjermstad est la **preuve empirique** de notre cap : deux approches ML (SAC-AE, U-net) tentées sur un problème **mieux défini que le nôtre** (les courbes ont une vérité-terrain : le MNT) → **aucune n'a abouti** ; la méthode simple (lissage) a gagné ; et l'auteur conclut que l'automatique **ne remplace pas le cartographe**.
Règle maintenue : **maximum en raster, un seul passage vecteur, généralisation géométrique déterministe et paramétrable** ; la généralisation *intentionnelle* (jugement, choix de représentation) reste à l'humain dans OOM. Toute proposition future poussant vers plus de sophistication algorithmique est suspecte par défaut.

---

## D. Stabilisation du périmètre

À partir de cet avenant, **le périmètre fonctionnel est considéré comme stabilisé.** Toute évolution devra être motivée par un **résultat expérimental issu d'un spike**, pas par une revue documentaire ou une spéculation architecturale (cf. §0). Les questions restantes — KP expose-t-il une densité ? OmapMaker tient-il sur Lambert-93 ? quel lissage donne un rendu naturel ? quels typenames WFS du jour ? les seuils tiennent-ils sur 4 terrains ? — portent sur **vos outils, vos données, votre terrain** : à ce stade, les principales incertitudes sont **expérimentales et se lèvent par des essais**, pas par une revue bibliographique supplémentaire.

**Prochaine action = exécution.** Phase 2 (squelette) → Phase 0 + **Phase 0 bis (OmapMaker)** → **ARRÊT au verrou humain**.

Tri des apports futurs **par effet, pas par étiquette** : les **faits techniques** (bug d'un outil, version qui renomme une sortie, endpoint IGN migré, correctif disponible) sont intégrés sans délai — c'est de la veille, elle change l'exécution. En revanche, **toute proposition qui ajoute de la complexité, élargit le périmètre ou modifie l'architecture est différée jusqu'au résultat des spikes**, quelle que soit la façon dont elle se présente (métrique, robustesse, calibration…). L'escalade ne s'annonce jamais comme telle ; c'est l'effet qui décide.
