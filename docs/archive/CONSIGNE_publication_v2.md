# Consigne Claude Code — Préparation à la publication (v2)

> Remplace la v1. Corrections : les cartes de référence sont retirées du dépôt (décision prise),
> le README est réordonné pour un lecteur pressé, et la provenance des chiffres est explicitée.
>
> **Deux exigences** : que tout fonctionne depuis un clone propre, et que les limites soient
> annoncées honnêtement.

---

## Étape 1 — Retirer les cartes de référence

**Décision prise** : les cartes de référence ne sont pas publiées.

1. Retirer du dépôt les fichiers de référence : `grimbosq.gpkg`, `airelles.gpkg`, `Kuti.gpkg`,
   `Kilemäed.gpkg`, les `.omap` et `.ocd` de Sandringham, Broadland, Pidula-Teesu, et tout
   autre fichier de carte tierce.
2. Les ajouter au `.gitignore` — en ciblant leur emplacement, pour ne pas exclure les sorties
   du pipeline qui portent les mêmes extensions.
3. **Vérifier l'historique git** :
   ```
   git log --all --diff-filter=A -- "*.gpkg" "*.omap" "*.ocd"
   ```
   Si ces fichiers ont été committés puis retirés, ils restent récupérables. Deux options :
   `git filter-repo` avec force-push, ou **repartir d'un dépôt neuf avec un commit initial
   unique** — plus simple et parfaitement légitime pour une première publication.
4. **Tester le mode dégradé** : le pipeline doit tourner sans aucune carte de référence.
   Le code est en place dans `qa.py`, mais il faut le vérifier depuis un clone vierge.

## Étape 2 — Test du clone propre (VERROU)

Cloner dans un répertoire vierge, suivre le README à la lettre, voir si ça tourne. C'est ce que
fera le premier utilisateur.

À vérifier :
- Dépendances toutes déclarées et installables (`pyproject.toml`)
- **Aucun chemin en dur** vers `e:/Vikazim/...` ou `C:/Users/glemi/...` — ni dans le code, ni
  dans les scripts, ni dans la doc
- `python main.py --help` fonctionne sans configuration préalable
- Assets nécessaires présents, ou URL de téléchargement dans le README

**Ne pas publier tant que ce test n'est pas passé.**

## Étape 3 — Le README, ordonné pour un lecteur pressé

Le lecteur cible : un cartographe de CO, techniquement à l'aise, qui ne connaît rien au projet.
Il veut savoir en trente secondes : **à quoi ça ressemble, et est-ce que ça marche chez moi.**
Les métriques viennent après — sinon il ferme l'onglet avant de les lire.

Ordre :

**1. Une phrase et une image.** Ce que c'est : génération d'une carte de base ISOM à partir de
LiDAR, sortie en `.omap` ouvrable dans OpenOrienteering Mapper. Puis un extrait de carte
générée, à l'échelle — pas la meilleure zone, une représentative.

**2. Comment l'essayer.** Prérequis, installation, la commande. Être explicite sur ce qui est
spécifique à la France (Géoplateforme pour le LiDAR, BD TOPO) et ce qui est générique.

**3. Ce que l'outil capture — avec la provenance des chiffres.**

> Mesuré sur **un seul terrain** (forêt de Grimbosq, Calvados, France), contre une carte FFCO
> de référence, sur emprise commune. Ces valeurs ne sont pas garanties ailleurs.

| classe | détecté | dans la bonne classe |
|---|---|---|
| 406 sous-bois léger | 35 % | 28 % |
| 408 marche | 61 % | 26 % |
| 410 progression difficile | 82 % | 48 % |

Lecture : la première colonne dit ce que le cartographe n'a pas à dessiner, la seconde ce qu'il
n'a pas à retoucher. **Le symbole se corrige en deux clics dans OCAD/OOM ; un polygone manquant
se dessine à la main.**

Ajouter : *métriques mesurées sur une carte de référence non redistribuable — les chiffres ne
sont donc pas reproductibles en l'état.*

**4. Domaine de validité, mesuré sur 5 terrains.** Fonctionne sur la végétation dense (408/410)
en forêt tempérée. Manque l'essentiel du sous-bois léger (406) : limite physique du signal, pas
défaut de calibration — dans cette classe, la densité de retours entre 0,3 et 3 m est
statistiquement indiscernable du terrain courable (AUC 0,487).
Testé et hors domaine : landes d'altitude, landes-marais, forêts à sous-bois uniforme.

**5. QA et carte de référence.** Le pipeline tourne sans référence (métriques dégradées).
Pour activer la comparaison, fournir sa propre carte au format GPKG ou `.omap` et la déclarer
dans `config.yaml`. Décrire le format attendu.

**6. Utilisation hors de France.** Le pipeline a tourné sur données estoniennes. À adapter :
CRS dans `config.yaml`, `georef_<terrain>.xml`, mapping des conventions (`scripts/mappings/`),
et l'absence d'équivalent BD TOPO. Renvoyer vers `docs/portabilite.md`.

**7. Ce que le projet a établi.** Lien vers `docs/bilan_v0.md` : onze pistes d'amélioration
testées et réfutées par la mesure, documentées pour éviter à d'autres de refaire le chemin.

**8. Statut du projet.** *(section à ne pas omettre)* Dire explicitement si le projet est
maintenu, si les issues seront traitées, ou s'il est publié en l'état comme travail posé.
Les deux sont légitimes — mais un dépôt qui ne répond pas alors qu'il semble actif déçoit plus
qu'un dépôt qui annonce être une archive.

**9. Licence, crédits, contact.**

## Étape 4 — Licences et crédits

- **Gabarit ISOM 2017-2** — vient de la distribution OpenOrienteering Mapper. Vérifier la
  licence avant inclusion ; sinon, indiquer où le récupérer.
- **CRT** — récupéré du projet Blaze. Vérifier sa licence et créditer la source dans `assets/`.
- **Karttapullautin** — non redistribuable a priori. Pointer vers son dépôt officiel, ne pas
  l'embarquer.
- **Historique git** — vérifier qu'aucun chemin utilisateur, clé ou donnée privée n'y traîne.

## Étape 5 — Ranger la documentation

Le dépôt contient plusieurs plans et consignes accumulés. Pour un lecteur externe, c'est du bruit.

- Garder à la racine ou dans `docs/` : `README.md`, `docs/bilan_v0.md`,
  `docs/portabilite.md`, `docs/etat_existant.md`
- Déplacer dans `docs/archive/` : les `CONSIGNE_*.md` et `PLAN_*.md`
- Vérifier qu'aucun document actif n'en contredit un autre (le plan v2 interdisait l'écriture
  `.omap`, devenue le cœur du livrable — s'il traîne encore, l'archiver)

## Étape 6 — Commit et tag

Message décrivant l'état publié, pas les derniers changements. Tag `v0.1`.

---

## Ce qu'il ne faut pas faire

- **Ne pas publier avant le test du clone propre.**
- **Ne pas embellir les chiffres, ni omettre leur provenance.** 28 % sur le 406, mesuré sur un
  seul terrain — les deux informations vont ensemble.
- Ne pas publier de cartes de tiers.
- Ne pas laisser les documents de travail en évidence.

---

## Note — réserve sur le calendrier

Le pipeline n'a été utilisé en conditions réelles qu'une fois (Port-en-Bessin), et ce premier
usage a révélé un bug de décalage d'emprise. D'autres attendent probablement.

Publier maintenant, c'est faire découvrir ces bugs par des inconnus plutôt que par toi. Deux ou
trois terrains français de plus, et le dépôt serait sensiblement plus solide.

Ce n'est pas une objection à publier — c'est un arbitrage à faire en connaissance de cause.
