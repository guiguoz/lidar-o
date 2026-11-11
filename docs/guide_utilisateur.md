# Guide utilisateur — Lidar'O

> Ce guide suppose que vous ne connaissez pas Python ni le terminal.
> Chaque commande est expliquée étape par étape.
> Plateforme principale : **Windows 10 / 11**.

---

## Sommaire

- [A — Avant de commencer](#a--avant-de-commencer)
- [B — Télécharger l'application](#b--télécharger-lapplication)
- [C — Installer](#c--installer)
- [D — Lancer](#d--lancer)
- [E — Préparer un projet](#e--préparer-un-projet)
  - [Télécharger et préparer la BD TOPO](#télécharger-et-préparer-la-bd-topo-france-uniquement)
- [F — Utiliser l'interface](#f--utiliser-linterface)
- [G — Lancer le calcul](#g--lancer-le-calcul)
- [H — Retrouver et utiliser les résultats](#h--retrouver-et-utiliser-les-résultats)
- [I — Exemple complet](#i--exemple-complet)
- [J — Dépannage](#j--dépannage)

---

## A — Avant de commencer

### Matériel recommandé

| Élément | Minimum | Recommandé |
|---|---|---|
| Mémoire RAM | 8 Go | 16 Go |
| Espace disque libre | 20 Go | 50 Go |
| CPU | 4 cœurs | 8 cœurs |
| Connexion internet | Oui (téléchargements initiaux) | — |

Les données LiDAR sont volumineuses (~500 Mo par dalle 1×1 km). Prévoir de l'espace pour les dalles, les caches intermédiaires et les sorties.

### Système pris en charge

- **Windows 10 / 11** (testé)
- Linux via Docker (voir [§ C — Installer — Docker](#docker))

### Ce qu'il faut préparer

Avant de commencer, vous aurez besoin de :

1. **Les coordonnées de votre terrain** (latitude / longitude, ou emprise en Lambert-93)
2. **Les dalles LiDAR HD** couvrant votre zone (fichiers `.copc.laz`, disponibles gratuitement sur IGN Géoplateforme)
3. **La BD TOPO** de votre département (fichier `.gpkg`, disponible gratuitement sur IGN Géoplateforme — France uniquement)

> Hors France : la BD TOPO n'est pas disponible. Des adaptations sont nécessaires — voir [docs/portabilite.md](portabilite.md).

### Rôle de chaque type de fichier

| Fichier | Rôle dans l'application | Obligatoire ? |
|---|---|---|
| `.copc.laz` — dalles LiDAR | Points 3D utilisés pour le relief (courbes de niveau) et pour le moteur végétation | Oui — toujours |
| `.gpkg` — BD TOPO département | Objets anthropiques : routes, bâtiments, hydrographie, zones boisées et urbaines (masquage végétation) | Oui pour la France — peut être omis hors France |
| `model_e_final.pkl` — modèle supervised_e | Modèle pré-entraîné pour la détection automatique de la végétation en mode `supervised_e` | Seulement en mode `supervised_e` — non public |
| `output/*.omap` — résultat | Carte assemblée à ouvrir dans OpenOrienteering Mapper | Produit par l'application |

La BD TOPO ne remplace ni les dalles LiDAR (nécessaires au relief et à la végétation), ni le modèle supervised_e (nécessaire à ce mode uniquement).

### Ce qui est inclus et ce qui ne l'est pas

| Inclus dans le dépôt | À télécharger séparément |
|---|---|
| Code source de l'application | Python + dépendances (Miniconda) |
| Gabarit de symboles ISOM 2017-2 | Karttapullautin (téléchargé automatiquement par `setup`) |
| Configuration exemple (Grimbosq) | Dalles LiDAR HD IGN |
| — | BD TOPO département IGN |
| — | Modèle supervised_e (si vous utilisez ce mode — non public) |

---

## B — Télécharger l'application

### Aucun installateur disponible

Lidar'O ne dispose pas de release ni d'exécutable prêt à lancer. L'installation se fait depuis les sources.

### Méthode 1 — Archive ZIP (sans Git)

1. Ouvrir la page du dépôt : `https://github.com/guiguoz/lidar-o`
2. Cliquer sur le bouton vert **Code** → **Download ZIP**
3. Extraire l'archive dans un dossier de votre choix (ex. `C:\lidar-o\`)
4. Résultat attendu dans le dossier :

```
lidar-o\
├── main.py
├── config.yaml
├── src\
├── gui\
├── scripts\
├── assets\
├── docs\
└── ...
```

### Méthode 2 — Git (recommandé pour les mises à jour)

Si Git est installé (`git --version` dans le terminal) :

```bat
git clone https://github.com/guiguoz/lidar-o.git
cd lidar-o
```

---

## C — Installer

### Ouvrir le terminal au bon endroit

1. Ouvrir l'**Explorateur de fichiers** et naviguer jusqu'au dossier `lidar-o`
2. Dans la barre d'adresse, taper `cmd` et appuyer sur Entrée
3. Un terminal noir s'ouvre dans le bon répertoire

**Vérifier :** la ligne de commande doit afficher quelque chose comme `C:\lidar-o>`

### Installer Python géospatial (Miniconda)

Le Python inclus dans Windows (ou installé via le Microsoft Store) ne possède pas les bibliothèques géospatiales nécessaires. Il faut Miniconda.

**1. Télécharger Miniconda**

Aller sur [https://docs.conda.io/en/latest/miniconda.html](https://docs.conda.io/en/latest/miniconda.html) et télécharger le programme d'installation Windows 64-bit.

**2. Installer Miniconda**

Double-cliquer sur le `.exe` téléchargé. Laisser les options par défaut.
À la fin, cocher « Add Miniconda3 to my PATH » si l'option est proposée, sinon l'ajouter manuellement (voir note ci-dessous).

> **Note — PATH :** Si les commandes `conda` et `python` ne sont pas reconnues après installation, ouvrir le **Miniconda Prompt** (raccourci créé par Miniconda dans le menu Démarrer) plutôt que `cmd`.

**3. Installer les dépendances**

Dans le **Miniconda Prompt**, naviguer jusqu'au dossier `lidar-o` et exécuter :

```bat
conda install -c conda-forge python=3.11 geopandas shapely scipy numpy ^
    python-pdal pdal rasterio ezdxf requests pyyaml
```

Cette commande installe toutes les bibliothèques nécessaires. Durée : 2–10 min selon la connexion.

**4. Vérifier l'installation**

```bat
python -c "import geopandas, rasterio, numpy; print('OK')"
```

Résultat attendu : `OK`

> **Mode supervised_e uniquement :** ce mode nécessite des bibliothèques supplémentaires (`scikit-learn`, `laspy`) et un fichier modèle de 786 Mo non distribué dans le dépôt.
> Si vous utilisez uniquement le mode `kp` (par défaut), aucune bibliothèque supplémentaire n'est nécessaire.
> Voir [docs/supervised_e.md](supervised_e.md) pour l'installation de ce mode.

### Docker

Si vous êtes sur Linux ou souhaitez une installation isolée :

```bash
docker build -t lidar-o .
docker run -v /chemin/vers/donnees:/data lidar-o run mon_terrain --tiles-dir /data/lidar
```

L'image Docker installe automatiquement toutes les dépendances.

---

## D — Lancer

### Mode interface graphique

```bat
python main.py gui
```

Une fenêtre s'ouvre avec le titre **Lidar'O**. C'est l'interface principale pour les utilisations courantes.

### Mode ligne de commande

```bat
python main.py run mon_terrain --tiles-dir LIDAR\
```

Le mode CLI est adapté aux automatisations et aux relances partielles du pipeline.

### Arrêt propre

- **GUI** : fermer la fenêtre. Si un calcul est en cours, il sera interrompu.
- **CLI** : `Ctrl+C` dans le terminal.

### Relancer lors des utilisations suivantes

Les étapes coûteuses (calcul LiDAR, Karttapullautin) sont mises en cache. Lors des relances, utiliser `--skip-pdal` pour sauter le recalcul LiDAR si les fichiers existent déjà :

```bat
python main.py run mon_terrain --skip-pdal
```

---

## E — Préparer un projet

### Structure recommandée

```
lidar-o\
├── LIDAR\                    ← vos dalles .copc.laz
│   ├── LHD_FXX_0448_6887_...laz
│   └── LHD_FXX_0448_6888_...laz
├── data\
│   └── bdtopo\               ← fichier .gpkg BD TOPO département
├── output\                   ← créé automatiquement
└── config.yaml               ← déclarer votre terrain ici
```

### Trouver les dalles LiDAR nécessaires

```bat
python main.py tiles mon_terrain
```

Cette commande affiche la liste des dalles IGN couvrant votre terrain (France / Lambert-93 uniquement).

Les dalles IGN sont nommées par leur **bord nord**. La dalle `LHD_FXX_XXXX_YYYY` couvre :

```
x ∈ [XXXX×1000, (XXXX+1)×1000]
y ∈ [(YYYY−1)×1000, YYYY×1000]
```

Télécharger les dalles sur [geoservices.ign.fr/lidarhd](https://geoservices.ign.fr/lidarhd) et les déposer dans `LIDAR\`.

### Initialiser le terrain

#### Depuis des coordonnées géographiques (latitude / longitude)

```bat
python main.py init mon_terrain --center 49.043 -0.421
```

Remplacer `49.043 -0.421` par les coordonnées du centre de votre zone (en degrés décimaux, WGS84).

#### Depuis une emprise projetée

```bat
python main.py init mon_terrain --bbox 448000 6886000 451000 6889000 --crs EPSG:2154
```

La commande `init` crée automatiquement :
- une entrée dans `config.yaml`
- le fichier `assets\georef_mon_terrain.xml` (géoréférencement — point de référence, convergence des méridiens, CRS)

### Télécharger et préparer la BD TOPO (France uniquement)

#### 1. Accéder au téléchargement

Aller sur **[geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo)**.

Sur la page, chercher l'onglet ou le lien **« Téléchargement »** puis **« par département »**.

> Si le site a changé d'organisation depuis la rédaction de ce guide, rechercher « BD TOPO téléchargement département » sur le site IGN — la page de téléchargement existe mais son emplacement exact peut varier d'une édition à l'autre.

#### 2. Choisir le bon département

Sélectionner le département qui **couvre votre terrain**, pas votre département de résidence.

Pour trouver le bon code : identifier le département sur la carte de France, ou utiliser les coordonnées de votre terrain sur [epsg.io](https://epsg.io/transform) pour vérifier la zone.

> **Terrain à cheval sur deux départements** : l'application ne gère qu'un seul GPKG par terrain. Si votre emprise touche deux départements, deux solutions :
> - **Solution simple** : télécharger les deux départements et pointer sur le plus grand (l'autre sera ignoré, avec un avertissement sur les couches manquantes aux bords)
> - **Solution complète** : fusionner les deux GPKG avec QGIS ou ogr2ogr avant utilisation (hors scope de ce guide)

#### 3. Choisir le bon format

Dans les options de téléchargement, choisir :

- **Format** : `GPKG` ou `GeoPackage` (pas `Shapefile`, pas `FileGDB`)
- **Projection** : `RGF93 / Lambert-93` (compatible avec EPSG:2154, le CRS du pipeline)
- **Thèmes** : `TOUSTHEMES` — l'archive complète, pas un export par thème

> Le sélecteur de couches peut proposer des exports thématiques (transport, bâti, hydrographie…). Ne pas les utiliser : chaque couche serait dans un fichier séparé, incompatible avec le chargeur actuel.

#### 4. Lire le nom du fichier

Le fichier téléchargé a un nom structuré. Exemple illustratif :

```
BDTOPO_3-5_TOUSTHEMES_GPKG_LAMB93_D014_2026-09-15.7z
```

| Fragment | Signification |
|---|---|
| `BDTOPO_3-5` | Version du produit BD TOPO |
| `TOUSTHEMES` | Tous les thèmes inclus (obligatoire) |
| `GPKG` | Format GeoPackage |
| `LAMB93` | Projection Lambert-93 / EPSG:2154 |
| `D014` | Département **14** (Calvados) |
| `2026-09-15` | Date d'édition |

Le nom exact change à chaque édition — l'important est la présence de `D014` (ou votre code département) et de `GPKG`.

> Les éditions récentes (2024–) utilisent parfois `BDT_3-5` au lieu de `BDTOPO_3-5`. Le format de l'archive peut aussi varier (`.7z`, `.zip`). Ces variations n'affectent pas le contenu.

#### 5. Télécharger et extraire l'archive

1. Télécharger le fichier (`.7z` ou `.zip`) — taille typique : 300–800 Mo selon le département
2. **Extraire l'archive** avant utilisation :
   - Sur Windows : clic droit → **Extraire tout…** (pour `.zip`) ; ou installer [7-Zip](https://www.7-zip.org/) pour les `.7z`
   - L'extraction produit un dossier contenant le fichier `.gpkg`

> **L'archive ne peut pas être chargée directement dans l'application.** Si vous sélectionnez le `.7z` dans l'interface graphique, un message d'erreur s'affiche. Il faut extraire le `.gpkg` d'abord.

#### 6. Ranger le fichier .gpkg

Après extraction, déplacer le fichier `.gpkg` dans `data\bdtopo\` :

```
lidar-o\
└── data\
    └── bdtopo\
        └── BDTOPO_3-5_TOUSTHEMES_GPKG_LAMB93_D014_2026-09-15.gpkg  ← ici
```

> Le dossier `data\bdtopo\` doit être créé s'il n'existe pas. L'application le crée automatiquement lors du premier `setup`.

#### 7. Ce que l'application utilise réellement

L'application extrait les couches suivantes du GPKG :

| Couche BD TOPO | Usage | Obligatoire ? |
|---|---|---|
| `troncon_de_route` | Routes et chemins → symboles 502–505 | Oui (vérifiée par `check`) |
| `batiment` | Bâtiments → symbole 521, masque végétation | Oui (vérifiée par `check`) |
| `surface_hydrographique` | Plans d'eau → symbole 301 | Oui (vérifiée par `check`) |
| `troncon_hydrographique` | Cours d'eau linéaires → symbole 302 | Oui (vérifiée par `check`) |
| `cours_d_eau` | Noms cours d'eau (complément) | Non — avertissement si absent |
| `zone_de_vegetation` | Bois/forêts IGN → masquage végétation | Non — avertissement si absent |
| `zone_d_habitation` | Enveloppes urbaines → masquage végétation | Non — avertissement si absent |
| `troncon_de_voie_ferree` | Voies ferrées | Non — ignoré si absent |

L'archive TOUSTHEMES contient toutes ces couches. Un export thématique partiel manquerait certaines couches vérifiées.

#### 8. Déclarer le fichier dans l'application

**Via l'interface graphique** : cliquer sur **Charger BD TOPO…** et sélectionner le fichier `.gpkg` extrait.

**Via la configuration** (optionnel, pour figer le chemin) : dans `config.yaml`, sous votre terrain :

```yaml
terrains:
  mon_terrain:
    bdtopo_path: "data/bdtopo/BDTOPO_3-5_TOUSTHEMES_GPKG_LAMB93_D014_2026-09-15.gpkg"
```

**Via le code département** (détection automatique) : si vous indiquez seulement `departement: "14"` dans `config.yaml`, l'application cherche automatiquement le fichier le plus récent contenant `D014` dans `data\bdtopo\`. C'est la méthode la plus simple si vous ne changez pas régulièrement de fichier.

#### 9. Conserver les métadonnées et la licence

L'archive BD TOPO contient des fichiers de métadonnées et de conditions d'utilisation. Les conserver dans `data\bdtopo\` à côté du `.gpkg`. La BD TOPO est distribuée sous [Licence Ouverte Etalab 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence) — utilisation libre, attribution requise.

### Configurer et vérifier

```bat
python main.py setup mon_terrain
```

Dialogue interactif qui vérifie et configure :
- le répertoire des dalles LiDAR
- le fichier BD TOPO
- le binaire Karttapullautin (téléchargé automatiquement si absent)

Résultat attendu en fin de `setup` :

```
── Contrôle final ──────────────────────────────────────────────────
Emprise   ✓  448000–450001 × 6886000–6889001 · 2×3 km · Lambert-93
LiDAR HD  ✓  6/6 dalles · dalles jointives
BD TOPO   ✓  BDT_3-5_GPKG… D014… · couches validées · couverture OK
KP        ✓  v2.12.1
────────────────────────────────────────────────────────────────────
PROJET PRÊT
```

---

## F — Utiliser l'interface

### Interface graphique — description des éléments

| Élément | Description |
|---|---|
| **Terrain** | Nom du terrain (doit exister dans `config.yaml`) |
| **Charger LiDAR…** | Sélectionner le répertoire contenant les dalles `.copc.laz` |
| **Charger BD TOPO…** | Sélectionner le fichier `.gpkg` département |
| **Grille de dalles** | Visualisation de la couverture LiDAR (vert = présent, rouge = manquant) |
| **État BD TOPO** | Résultat du contrôle couches + couverture spatiale (vert / orange / rouge) |
| **Karttapullautin** | Présence et version du binaire KP |
| **Mode végétation** | Mode lu depuis `config.yaml` pour le terrain saisi (lecture seule) |
| **Générer** | Lance le pipeline complet |
| **Journal** | Affiche la progression en temps réel |

> La GUI nécessite que le terrain soit déjà initialisé (`python main.py init`).
> Elle ne remplace pas `setup` pour la première configuration.

### Comportements automatiques

**Emprise depuis les dalles LiDAR**
Quand vous chargez un répertoire LiDAR, l'interface lit les en-têtes de chaque fichier `.laz` via PDAL pour calculer l'emprise géographique réelle. Cette emprise est utilisée pour le contrôle de couverture BD TOPO — même si le terrain n'est pas encore déclaré dans `config.yaml`.

**Re-contrôle BD TOPO automatique**
Dès qu'un nouveau répertoire LiDAR est sélectionné, le contrôle BD TOPO est relancé automatiquement avec la nouvelle emprise (si un fichier BD TOPO est déjà chargé). Pas besoin de re-sélectionner le `.gpkg`.

**Mode végétation (lecture seule)**
Le label *Mode végétation* affiche la valeur de `vegetation_source` lue dans `config.yaml` pour le terrain saisi. Le mode ne se change pas depuis l'interface — modifier `config.yaml` directement ou relancer `python main.py setup <terrain>`.

**Interpréteur Python**
Au démarrage, le journal affiche le chemin de l'interpréteur Python utilisé par la GUI :
```
Python : C:\Users\glemi\miniconda3\python.exe
```
Si la ligne indique un autre chemin (par exemple `C:\Python314\python.exe`), les bibliothèques géospatiales ne sont pas disponibles et les contrôles BD TOPO resteront orange. Lancer la GUI depuis le bon environnement :
```bat
rem Miniconda Prompt
python main.py gui
```

### Options de configuration dans `config.yaml`

Le fichier `config.yaml` à la racine du projet contient tous les paramètres. Les options principales par terrain :

```yaml
terrains:
  mon_terrain:
    bbox: [448000, 6886000, 451000, 6889000]  # emprise en coordonnées projetées
    crs: EPSG:2154                             # CRS (Lambert-93 pour la France)
    departement: "14"                          # code département BD TOPO (France uniquement)
    vegetation_source: "kp"                    # "kp" (défaut), "supervised_e" ou "hag"
```

#### Mode végétation `vegetation_source`

| Valeur | Description | Prérequis supplémentaires |
|---|---|---|
| `kp` (défaut) | Karttapullautin — extraction depuis le rendu LiDAR | Aucun |
| `supervised_e` | Détection directe depuis le nuage de points (expérimental) | Fichier modèle 786 Mo |
| `hag` | Classification HAG (Hauteur Au-dessus du Sol) — pour QA uniquement | PDAL |

#### Mode d'export `vegetation_export_mode` (supervised_e uniquement)

```yaml
vegetation_export_mode: "faithful"    # défaut — aucun pixel perdu
# ou
vegetation_export_mode: "generalized" # archive — composantes < 16 m² supprimées
```

### Végétation supervised_e — ce que signifient les classes

| Classe ISOM | Signification terrain | Note |
|---|---|---|
| 401 — terrain découvert | Pré, champ, clairière ouverte | Vectorisé |
| 406 — végétation légère | Course lente — sous-bois léger, taillis peu dense | Vectorisé |
| 408 — végétation intermédiaire | Marche — sous-bois moyennement dense | Vectorisé |
| 410 — végétation dense | Progression difficile | Vectorisé |
| blanc (fond) | Végétation rase, pâture — fond implicite du `.omap` | Pas de polygone |
| Inconnu | Aucune donnée LiDAR — zone non couverte | Absent du `.omap`, ni blanc ni courable |

**Blanc ≠ inconnu** : le blanc est une prédiction (végétation nulle), l'inconnu est une absence de données. Les deux apparaissent en blanc à l'écran mais ont des origines différentes.

---

## G — Lancer le calcul

### Vérifications préalables

Avant de lancer, s'assurer que :
- les dalles LiDAR couvrent bien l'emprise (`python main.py check mon_terrain`)
- la BD TOPO est téléchargée et dans le bon dossier
- au moins 10 Go d'espace disque libre sont disponibles

### Lancer

```bat
python main.py run mon_terrain --tiles-dir LIDAR\
```

### Progression et logs

Le pipeline affiche ses étapes en temps réel :

```
INFO  fetch — data\mon_terrain_bdtopo.gpkg produit
INFO  relief — 6 dalles, 42 min
INFO  vegetation_kp — vegetation_kp.gpkg produit
INFO  assemble — output\mon_terrain.omap (18 couches)
```

Chaque étape affiche sa durée. Si une ligne `INFO SKIP` apparaît, l'étape est sautée car son résultat est à jour.

### Durées indicatives (6 dalles, 2×3 km, laptop récent)

Ces durées ont été mesurées sur un terrain de 2×3 km en Normandie.

| Étape | Mode kp | Mode supervised_e |
|---|---|---|
| `fetch` (BD TOPO) | < 1 min | < 1 min |
| `relief` (Karttapullautin) | 35–45 min | 35–45 min |
| `vegetation_kp` ou `supervised_e` | 1–2 min | 5–15 min |
| `assemble` | < 1 min | < 1 min |
| **Total** | **~45 min** | **~55 min** |

> Si le pipeline semble bloqué à l'étape `relief`, il travaille — Karttapullautin est intensif CPU et ne produit pas d'affichage de progression. Attendre au moins 5 min par dalle avant de conclure à un blocage.

### Interruption et reprise

**Interruption :** `Ctrl+C` dans le terminal. Les fichiers déjà produits sont conservés.

**Reprise depuis une étape :**

```bat
rem Reprendre après le LiDAR (si les rasters existent déjà)
python main.py run mon_terrain --skip-pdal

rem Reprendre à une étape précise
python main.py run mon_terrain --from-step assemble
```

> Il n'y a pas de reprise automatique sur interruption en cours d'étape. Si une étape est interrompue à mi-parcours, elle sera relancée depuis le début la prochaine fois.

---

## H — Retrouver et utiliser les résultats

### Emplacement

Tous les fichiers de sortie sont dans `output\` :

| Fichier | Description |
|---|---|
| `output\mon_terrain.omap` | **Résultat principal** — carte assemblée, prête à ouvrir dans OOM |
| `output\vegetation_kp.gpkg` | Couches végétation vectorielles (mode kp) |
| `output\vegetation_supervised_e_faithful.gpkg` | Couches végétation vectorielles (mode supervised_e) |
| `output\supervised_e_coverage.tif` | Masque couverture LiDAR (1 = couvert, 0 = inconnu) |
| `output\run_metadata.json` | Métriques QA et snapshot de la configuration |

> Conserver `output\` et `assets\georef_mon_terrain.xml` ensemble — ils sont liés par le géoréférencement.

### Ouvrir dans OpenOrienteering Mapper

1. Lancer OpenOrienteering Mapper
2. **Fichier → Ouvrir** → naviguer jusqu'à `output\mon_terrain.omap`
3. La carte s'affiche avec toutes les couches (relief, routes, végétation…)

#### Afficher toutes les couches

Si certaines couches n'apparaissent pas : **Carte → Éditeur de couches** → activer les couches désactivées.

#### Vérification géographique

La carte est géoréférencée. Pour vérifier l'alignement :
- **Carte → Géoréférencement** → confirmer que les coordonnées correspondent à votre terrain
- Si la carte est décalée, vérifier le signe de `declination` dans `assets\georef_mon_terrain.xml`

### Utiliser la carte

Les couches végétation automatiques sont une **base de travail** :
- Les classes 408 et 410 (végétation dense) sont généralement fiables
- La classe 406 (végétation légère) est plus difficile à détecter et doit être vérifiée au terrain
- Le fond de carte KP (raster géoréférencé) aide à positionner les corrections

---

## I — Exemple complet

Cet exemple utilise des noms génériques. Remplacer les valeurs par celles de votre terrain.

### Situation de départ

- Vous souhaitez cartographier une forêt de 3 km².
- Coordonnées du centre : latitude 48.5, longitude 2.3 (Île-de-France).
- Vous êtes en France (département 91).

### Étape 1 — Télécharger les données

**Dalles LiDAR :**
1. Aller sur [geoservices.ign.fr/lidarhd](https://geoservices.ign.fr/lidarhd)
2. Lancer `python main.py tiles ma_foret` pour obtenir la liste des dalles
3. Les télécharger et les déposer dans `lidar-o\LIDAR\`

**BD TOPO :**
1. Aller sur [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo)
2. Télécharger l'archive GPKG du département 91
3. La déposer dans `lidar-o\data\bdtopo\`

### Étape 2 — Initialiser le terrain

```bat
cd C:\lidar-o
python main.py init ma_foret --center 48.5 2.3
```

### Étape 3 — Configurer

```bat
python main.py setup ma_foret
```

Répondre aux questions du dialogue :
- Répertoire LiDAR → indiquer `LIDAR\`
- BD TOPO → indiquer le fichier `.gpkg` téléchargé
- Karttapullautin → appuyer sur Entrée pour le téléchargement automatique

### Étape 4 — Vérifier

```bat
python main.py check ma_foret
```

Résultat attendu :
```
Emprise   ✓
LiDAR HD  ✓  X/X dalles · dalles jointives
BD TOPO   ✓
KP        ✓
```

### Étape 5 — Lancer le pipeline

```bat
python main.py run ma_foret --tiles-dir LIDAR\
```

Attendre la fin. La durée dépend du nombre de dalles.

### Étape 6 — Ouvrir le résultat

Ouvrir `output\ma_foret.omap` dans OpenOrienteering Mapper.

---

## J — Dépannage

### `python` : commande introuvable

**Symptôme :** `python n'est pas reconnu comme commande interne...`

**Solution :** utiliser le Miniconda Prompt (raccourci dans le menu Démarrer) plutôt que `cmd`. Si vous utilisez `cmd`, vérifier que Miniconda a été ajouté au PATH lors de l'installation.

### Mauvaise version de Python

**Symptôme :** erreur d'import ou message `Python 3.14` détecté

**Solution :** utiliser explicitement le Python de Miniconda :

```bat
C:\Users\<user>\miniconda3\python.exe main.py run mon_terrain --tiles-dir LIDAR\
```

Remplacer `<user>` par votre nom d'utilisateur Windows.

### Dépendance absente

**Symptôme :** `ModuleNotFoundError: No module named 'geopandas'` (ou autre)

**Solution :**

```bat
conda install -c conda-forge geopandas
```

Pour `shapely`, `rasterio`, `scipy`, etc. : même commande en remplaçant le nom du module.

### Modèle supervised_e absent

**Symptôme :** `FileNotFoundError: model_e_final.pkl introuvable` lors de l'utilisation du mode `supervised_e`

**Solution :** le modèle n'est pas distribué dans le dépôt. Sans ce fichier, passer en mode `kp` dans `config.yaml` :

```yaml
vegetation_source: "kp"
```

Voir [docs/supervised_e.md § 3](supervised_e.md#3-modèle-final--localisation-et-chargement) pour les informations sur le modèle.

### Chemin avec espaces ou accents

**Symptôme :** erreur bizarre lors du chargement d'un fichier avec des espaces dans le chemin

**Solution :** placer le dossier `lidar-o` dans un chemin sans espaces ni accents (ex. `C:\lidar-o\`, pas `C:\Mes Documents\lidar-o\`).

### CRS inconnu ou non supporté

**Symptôme :** `CRS not supported` ou `No georef found`

**Solution :** vérifier le CRS de vos dalles LiDAR (`pdal info --metadata dalle.laz`) et le déclarer explicitement dans `config.yaml` :

```yaml
terrains:
  mon_terrain:
    crs: EPSG:2154   # adapter à votre système de coordonnées
```

### Dalles manquantes ou non jointives

**Symptôme :** `✗ dalles non jointives` lors de `check`

**Solution :** télécharger les dalles manquantes sur [geoservices.ign.fr/lidarhd](https://geoservices.ign.fr/lidarhd) et les ajouter dans `LIDAR\`.

### Résultat vide ou décalé

**Symptôme :** le `.omap` s'ouvre mais la carte est vide ou très décalée

**Vérifications :**
1. `assets\georef_mon_terrain.xml` existe et contient un point de référence dans l'emprise
2. Le signe de `declination` est correct (négatif à l'ouest du méridien central, positif à l'est)
3. Le CRS des dalles LiDAR correspond à celui déclaré dans `config.yaml`

### Disque plein

**Symptôme :** `OSError: No space left on device` ou `Errno 28`

**Solution :** libérer de l'espace. Les caches intermédiaires sont dans `output\`. Supprimer les fichiers `.tif` intermédiaires (`density_hag.tif`, `density_hag_classified.tif`) si vous souhaitez économiser de l'espace après un run réussi.

### Mémoire insuffisante

**Symptôme :** plantage silencieux ou `MemoryError` sur de grandes emprises

**Solution :**
- Réduire l'emprise du terrain (plus petite bbox)
- Fermer les autres applications
- Passer à 16 Go de RAM si les emprises > 10 km² sont fréquentes

### BD TOPO — mauvais département

**Symptôme :** `✗ couverture spatiale insuffisante` lors de `check` ou `setup`, ou routes / bâtiments absents de la carte produite

**Vérifications :**
1. Identifier le département qui **couvre votre terrain** (pas votre département de résidence)
2. Vérifier que le code département dans le nom du fichier correspond — ex. `D014` = département 14

**Solution :** télécharger le GPKG du bon département sur [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo).

### BD TOPO — archive non extraite

**Symptôme :** dans l'interface graphique, cliquer sur **Charger BD TOPO…** puis sélectionner un fichier `.7z` → message d'erreur affiché, BD TOPO non chargée

**Solution :** extraire l'archive `.7z` avant de la charger :
- Installer [7-Zip](https://www.7-zip.org/) si ce n'est pas déjà fait
- Clic droit sur le fichier `.7z` → **7-Zip → Extraire ici**
- Sélectionner le fichier `.gpkg` extrait dans l'interface

### BD TOPO — mauvais fichier sélectionné

**Symptôme :** `couches manquantes : troncon_de_route, batiment, …` dans le journal de l'interface

**Causes possibles :**
- Export thématique au lieu de TOUSTHEMES (ex. archive "TRANSPORT" seule)
- Fichier d'un autre produit IGN (ex. BD CARTO, qui a une structure différente)
- Fichier extrait d'une archive partielle

**Solution :** télécharger l'archive **TOUSTHEMES** complète depuis [geoservices.ign.fr/bdtopo](https://geoservices.ign.fr/bdtopo).

### BD TOPO — projection incompatible

**Symptôme :** routes et bâtiments apparaissent très loin de leur position réelle, ou message CRS dans les logs

**Explication :** le pipeline attend des données en Lambert-93 (EPSG:2154). Le fichier téléchargé doit porter `LAMB93` dans son nom.

**Solution :** re-télécharger en sélectionnant explicitement `RGF93 / Lambert-93` sur le site IGN. Les archives en `WGS84` ou autres projections ne sont pas compatibles sans conversion préalable.

### BD TOPO — données ne couvrant pas le terrain

**Symptôme :** `✗ couverture spatiale insuffisante` même avec le bon département

**Causes :**
- Terrain à cheval sur deux départements — le GPKG d'un seul département ne couvre pas toute l'emprise
- Emprise déclarée trop large par rapport à la zone réelle

**Solution pour un terrain multi-département :**
L'application ne gère pas nativement plusieurs GPKG. Télécharger les deux départements, puis pointer sur le GPKG principal (le plus grand) : les couches du département manquant seront absentes aux bords, avec des avertissements. Pour une couverture complète, fusionner les deux GPKG avec QGIS (Vecteur → Outils de gestion de données → Fusionner des couches vectorielles) avant de relancer.

### BD TOPO — couche absente

**Symptôme :** `WARNING  Calque 'zone_de_vegetation' absent ou illisible` dans les logs — le pipeline continue mais la végétation n'est pas masquée par les zones boisées IGN

**Explication :** les couches `zone_de_vegetation`, `zone_d_habitation`, `cours_d_eau` ne sont **pas bloquantes** — leur absence génère un avertissement, pas une erreur.

Les 4 couches obligatoires (`troncon_de_route`, `batiment`, `surface_hydrographique`, `troncon_hydrographique`) sont toutes présentes dans l'archive TOUSTHEMES.

**Solution :** aucune si l'archive TOUSTHEMES est utilisée. Si vous voyez ce message avec TOUSTHEMES, vérifier la version de la BD TOPO (les intitulés de couches ont changé entre éditions — voir ci-dessous).

### BD TOPO — intitulés de couches modifiés entre éditions

**Symptôme :** couches non trouvées malgré une archive TOUSTHEMES correcte — la BD TOPO a changé le nom d'une couche entre deux versions du produit

**Explication :** IGN peut renommer des couches entre versions (ex. 3-3 → 3-5). L'application est configurée pour la BD TOPO 3-5 (nommage actuel).

**Vérification :** dans QGIS, ouvrir le `.gpkg` et vérifier les noms des couches disponibles. Les comparer avec ceux listés dans la [§ E — Télécharger et préparer la BD TOPO](#7-ce-que-lapplication-utilise-réellement).

**Solution :** mettre à jour `config.yaml` sous `bd_topo.layers` pour correspondre aux intitulés de votre édition, ou utiliser une archive TOUSTHEMES BD TOPO 3-5.

### Karttapullautin — version incorrecte

**Symptôme :** `KP version: X.Y.Z — attendu 2.12.1` lors de `setup`

**Solution :** re-lancer `python main.py setup mon_terrain` et laisser `setup` télécharger la bonne version.

### Le `.omap` ne s'ouvre pas dans OOM

**Symptôme :** OpenOrienteering Mapper signale une erreur à l'ouverture

**Vérifications :**
- S'assurer que `assets\georef_mon_terrain.xml` est dans le dossier `assets\` du projet
- S'assurer qu'OOM version ≥ 0.9.5 est utilisé (format OOM v2)

### Signaler un problème

Informations utiles à joindre :
- Version : `python main.py --version` (si disponible)
- OS : Windows 10 / 11, version
- Commande exacte lancée
- Dernières lignes du log (sans chemins personnels)

**Ne pas joindre** : dalles LiDAR, fichiers BD TOPO, données personnelles, chemins complets de votre machine.

Ouvrir une issue sur [github.com/guiguoz/lidar-o/issues](https://github.com/guiguoz/lidar-o/issues).
