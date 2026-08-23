# Consigne Claude Code — Commandes `init`, `tiles` et `check` (v2)

> Remplace la v1. Corrections : séparation des responsabilités (`init` reste générique, le
> connecteur national va dans `tiles`), CRS déduit au lieu d'exigé, taille par défaut avec
> plafond, et **ajout d'une vérification de recouvrement bbox/dalles** — le contrôle qui aurait
> évité le bug de Port-en-Bessin.
>
> Objectif : qu'un nouvel utilisateur passe d'un point sur une carte à un pipeline prêt à
> tourner, sans écrire un fichier à la main ni calculer quoi que ce soit.

---

## Le problème

Avant de lancer quoi que ce soit, l'utilisateur doit aujourd'hui produire :

1. une bbox en coordonnées projetées (nécessite un outil externe)
2. une entrée YAML dans `config.yaml`
3. un `assets/georef_<terrain>.xml` avec une **convergence des méridiens calculée à la main**
4. la liste des tuiles LiDAR, déduite d'une convention de nommage

**Deux de ces quatre étapes ont déjà piégé l'auteur du projet** :
- le décalage d'un kilomètre sur les tuiles IGN (nommées par leur bord **nord**) —
  découvert à Port-en-Bessin, après un run complet produisant deux emprises disjointes
- le signe de la convergence des méridiens — découvert à Kilemäed, masqué en France où
  convergence et déclinaison magnétique coïncident approximativement

Tout est mécanique et calculable.

---

## Commande 1 — `init` (générique, aucun code pays)

```bash
# Mode principal : un point sur une carte + une taille
python main.py init mon_terrain --center 49.043 -0.421

# Taille explicite (défaut 2000 m)
python main.py init mon_terrain --center 49.043 -0.421 --size 3000

# Ou depuis une bbox projetée, si l'utilisateur l'a déjà
python main.py init mon_terrain --bbox 448000 6886000 450000 6889000 --crs EPSG:2154
```

### CRS déduit, pas exigé

`--crs` devient **optionnel**. Depuis les coordonnées géographiques, proposer le CRS approprié et
demander confirmation :

```
Point 49.043 N, -0.421 E → France métropolitaine
CRS proposé : EPSG:2154 (RGF93 / Lambert-93)
Confirmer ? [O/n]
```

Table de correspondance minimale (France 2154, Estonie 3301, Grande-Bretagne 27700, Finlande
3067, Suisse 2056, Norvège 25832/25833), avec **repli sur la zone UTM correspondante** si le pays
n'est pas dans la table. Une projection UTM est toujours utilisable et se calcule depuis la
longitude.

`--crs` explicite court-circuite la déduction. Quelqu'un qui donne un point en lat/lon n'a
souvent aucune idée du code EPSG de son pays — l'exiger était une mauvaise idée.

### Taille par défaut et plafond

- `--size` par défaut : **2000 m** (carte de CO typique : 1 à 5 km²)
- Au-delà de **5000 m**, avertir explicitement : temps de traitement, volume de données,
  et demander confirmation. Un utilisateur peut lancer 50 km² sans s'en rendre compte.

### Ce que `init` produit

**1. L'entrée `config.yaml`** sous `terrains:`. Refuser si le terrain existe déjà, sauf `--force`.

**2. `assets/georef_<terrain>.xml`**, entièrement calculé :
- `ref_point` : centre de la bbox, arrondi au millier
- `ref_point_deg` : conversion WGS84 via `pyproj` (déjà en dépendance)
- `declination` : **convergence des méridiens**, formule
  `(λ_point − λ_méridien_central) × sin(φ)`. Lire le méridien central dans la définition du CRS
  via `pyproj.CRS` — **ne pas le coder en dur par pays**
- `auxiliary_scale_factor` : reprendre la valeur des georef existants (0.999966 pour Lambert-93)
  et **documenter que c'est une approximation valable en plaine**. Ne pas tenter un calcul dont
  la formule exacte attendue par OOM n'est pas établie — c'est un raffinement, pas un prérequis

> ⚠️ **`declination` dans un `.omap` est la convergence des méridiens, PAS la déclinaison
> magnétique.** Les deux coïncident approximativement en France (~−2,4°) mais diffèrent de plus
> de 10° dans les pays baltes. Ne jamais utiliser un service de déclinaison magnétique.

**3. L'arborescence** : `LIDAR/`, `data/`, `output/` si absents.

**4. Un récapitulatif** : ce qui a été créé, ce qu'il reste à faire, et la commande suivante.

### Contrainte d'architecture

**Aucun paramètre spécifique à un pays dans `init`.** La commande doit fonctionner pour un
terrain en Nouvelle-Zélande comme en France. Le seul point de contact avec un pays est la
suggestion de CRS, qui a un repli UTM universel.

---

## Commande 2 — `tiles` (connecteur national, isolé)

```bash
python main.py tiles mon_terrain
```

Affiche la liste des fichiers LiDAR nécessaires pour couvrir la bbox, selon le connecteur
disponible pour le CRS du terrain.

```
Tuiles LiDAR HD à télécharger (6) :
  LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz
  LHD_FXX_0448_6888_PTS_LAMB93_IGN69.copc.laz
  ...
Source : https://geoservices.ign.fr/lidarhd
À placer dans : LIDAR/
```

**Séparée de `init` volontairement** : `init` doit rester générique, `tiles` est le seul endroit
qui connaît des conventions nationales. Les deux évoluent indépendamment.

**Convention IGN — origine du bug de Port-en-Bessin** : la tuile `LHD_FXX_XXXX_YYYY` couvre
`x ∈ [XXXX×1000, (XXXX+1)×1000]` et `y ∈ [(YYYY−1)×1000, YYYY×1000]`. **YYYY est le bord nord.**

Sans connecteur pour le CRS du terrain : message neutre — « placez vos dalles LiDAR (LAZ/COPC)
couvrant la bbox dans `LIDAR/` ». Le reste du pipeline est agnostique.

**Structure** : `src/providers/france.py`, interface minimale « depuis une bbox et un CRS,
retourner la liste des fichiers et leur source ». Un contributeur ajoute son pays sans toucher
au cœur — ce que le README appelle déjà.

**N'écrire que le connecteur France**, comme exemple.

---

## Commande 3 — `check` (le contrôle qui manquait)

```bash
python main.py check mon_terrain
```

**C'est l'ajout le plus important de cette consigne.** À Port-en-Bessin, les dalles étaient
présentes mais décalées d'un kilomètre : le pipeline a tourné jusqu'au bout et produit une carte
où végétation et couches anthropiques occupaient deux zones disjointes. Rien ne l'a signalé.

`check` vérifie, avant tout traitement :

| Contrôle | Action si échec |
|---|---|
| Dalles présentes dans `LIDAR/` | Erreur, renvoyer vers `tiles` |
| **Étendue des dalles vs bbox déclarée** | **Erreur si recouvrement < 90 %**, avec les deux emprises affichées |
| CRS des dalles vs CRS déclaré | Erreur explicite |
| `assets/georef_<terrain>.xml` présent et valide | Erreur, renvoyer vers `init` |
| BD TOPO présente (si `departement` déclaré) | Avertissement, pas erreur — le pipeline tourne sans |
| Karttapullautin dans `out_kp/` | Information seulement — le relief est optionnel |

**Appeler `check` automatiquement en tête de `run`**, avec `--skip-check` pour le contourner.
Un contrôle qu'il faut penser à lancer ne sert à rien.

L'affichage en cas d'échec doit être lisible :

```
ERREUR : les dalles ne couvrent pas la bbox déclarée.
  bbox config   : X 424000–427000  Y 6920000–6922000
  dalles LIDAR/ : X 424000–427000  Y 6921000–6923000
  recouvrement  : 50 %
  → Convention IGN : les tuiles sont nommées par leur bord NORD.
    Vérifiez avec : python main.py tiles mon_terrain
```

---

## Hors périmètre de cette passe

- **Téléchargement automatique des dalles** — chantier séparé, cas d'erreur propres (réseau,
  quotas, couverture). La liste des noms est déjà l'essentiel du gain.
- **Appel à Karttapullautin** — prévu au plan v3 (`run_engine.py`), autre chantier.
- **Interface graphique** — le public est technique, et elle ne supprimerait aucune des étapes
  réellement pénibles (installer PDAL, télécharger des centaines de Mo).

---

## Tests attendus

- **Conversion de coordonnées** : `--center` WGS84 → bbox projetée → retour WGS84 à ±1 m.
- **Convergence des méridiens** : Grimbosq (≈ −2,6°) **et** Kilemäed (≈ −1,27°, signe opposé,
  point à l'est du méridien central estonien). Deux terrains de part et d'autre — c'est ce qui
  aurait attrapé H7.
- **Nommage des tuiles IGN** : bbox `[448000, 6886000, 450001, 6889001]` → exactement les 6
  tuiles `0448/0449 × 6887/6888/6889`. Non-régression du bug Port-en-Bessin.
- **Recouvrement `check`** : dalles décalées d'un kilomètre → erreur, pas warning.
- **Déduction de CRS** : point en France → 2154 ; point en Estonie → 3301 ; point hors table →
  zone UTM correcte.
- **Terrain existant** : `init` refuse sans `--force`.
- Le XML produit est valide et se recharge par `load_georef()`.

---

## Documentation

Réécrire la section « Declare your terrain » du README :

```bash
python main.py init my_forest --center 49.043 -0.421
python main.py tiles my_forest      # liste les fichiers à télécharger
# … télécharger et placer dans LIDAR/ …
python main.py my_forest --tiles-dir LIDAR/
```

Garder la documentation du format manuel plus bas, en référence — quelqu'un voudra comprendre ce
que fait la commande ou ajuster un paramètre.

**Mettre à jour aussi « Complete example »** : elle décrit les étapes manuelles que ces
commandes remplacent.
