# Audit installabilité — Lidar'O V2

> Date : 2026-09-26  
> Objectif : supprimer les manipulations techniques sans rendre Lidar'O dépendant
> d'URLs et APIs externes.  
> Périmètre : lecture seule du dépôt. Aucun code modifié.

---

## 1. EXISTANT — état actuel du dépôt

### 1.1 `main.py init` → `src/init_terrain.py:cmd_init()`

Ce qui est déjà fait :
- Calcule bbox depuis `--center lat lon` ou `--bbox xmin ymin xmax ymax --crs`
- Déduit le CRS depuis les coordonnées (table de 7 pays)
- Écrit `assets/georef_{terrain}.xml` (convergence méridiens, point de référence)
- Ajoute le terrain dans `config.yaml` (bbox + crs uniquement)
- Crée `LIDAR/{terrain}/`, `data/`, `output/`
- Appelle déjà `find_tiles()` et affiche la liste des dalles

Ce qui manque ou pose problème :
- Le `config.yaml` ne stocke **pas** `lidar_dir` ni `bdtopo_path` — les chemins ne sont jamais persistés
- Le `departement` IGN n'est **pas écrit** par `init` — il faut l'ajouter manuellement
- L'affichage post-init contient une URL IGN en dur (`https://geoservices.ign.fr/bdtopo`, ligne 299) — à supprimer
- `LIDAR/{terrain}/` est créé mais c'est un chemin relatif au dossier du projet, pas le chemin réel des dalles de l'utilisateur

### 1.2 `main.py tiles` → `src/providers/france.py:list_tiles()`

Ce qui est déjà fait :
- Calcule les noms exacts des dalles (`LHD_FXX_XXXX_YYYY_PTS_LAMB93_IGN69.copc.laz`)
- Logique correcte et vérifiée sur Grimbosq
- Affiche la liste + source

Ce qui manque ou pose problème :
- `TILE_SOURCE = "https://geoservices.ign.fr/lidarhd"` — URL en dur susceptible de changer
- Affichage minimal : pas d'indication sur le format attendu, pas de dossier cible clairement indiqué
- La commande s'appelle `python main.py tiles {terrain}` (syntaxe incohérente avec le reste)

### 1.3 `main.py check` → `src/check_terrain.py:cmd_check()`

Ce qui est déjà fait :
- Cherche les dalles dans le répertoire `--lidar-dir` ou `LIDAR/`
- Vérifie la couverture bbox (pdal info + fallback nom IGN)
- Vérifie le CRS des dalles vs config.yaml
- Valide le georef XML
- Avertit si BD TOPO absent (non bloquant)
- Info si KP absent (non bloquant)

Ce qui manque ou pose problème :
- **`lidar_dir` non persisté** : le check utilise `LIDAR/` par défaut — si les dalles sont ailleurs, il faut re-passer `--tiles-dir` à chaque run
- **BD TOPO** : uniquement un warning, jamais une erreur — même si le département est déclaré et que le fichier est absent
- **Validation BD TOPO** absente : pas de contrôle des couches, pas de contrôle de la couverture géographique
- **KP** : uniquement une info, pas de détection active du binaire dans cette fonction (délégué à `run_engine.py`)
- Pas de détection des dalles manquantes par nom — seulement un contrôle de couverture globale
- Pas de détection des dalles hors-emprise ou en trop

### 1.4 `main.py run` → `_cmd_run()`

- Appelle `cmd_check` avant le run (bloquant si échec)
- Lit `--tiles-dir DIR` ou `--tiles FILE...`
- Le `tiles-dir` n'est **jamais stocké** dans config — il faut le repasser à chaque run
- KP : cherché via `KP_BINARY` env var ou `shutil.which("pullauta")` — pas de chemin en config

### 1.5 `scripts/fetch.py`

- Lit le GPKG depuis `data/bdtopo/` en cherchant `*D{dept}*.gpkg`
- Le département vient de `config.yaml` sous `terrains.{terrain}.departement`
- Ce champ **n'est pas écrit par `init`** — à ajouter manuellement
- Le GPKG peut être en `.7z` (format livraison IGN actuel) — le pipeline attend un GPKG extrait

### 1.6 `src/run_engine.py:locate_binary()`

```python
env_path = os.environ.get("KP_BINARY")  # → KP_BINARY=/chemin/pullauta
shutil.which("pullauta")                # → PATH
```

- Mécanisme fonctionnel, bien séparé
- Pas de chemin stocké en config
- Pas de téléchargement automatique

### 1.7 Structure `config.yaml` par terrain (actuelle)

```yaml
terrains:
  grimbosq:
    bbox: [448000, 6886000, 450001, 6889001]
    crs: EPSG:2154
    departement: "14"    # ajouté manuellement
    # lidar_dir : absent
    # bdtopo_path : absent
    # kp_binary : absent
```

---

## 2. À RÉUTILISER — briques existantes exploitables

| Brique | Emplacement | Valeur |
|--------|-------------|--------|
| Calcul noms de dalles | `src/providers/france.py:list_tiles()` | Logique correcte, vérifiée sur 2 terrains. Conserver telle quelle. |
| Parsing nom de dalle IGN | `src/check_terrain.py:_ign_tile_extent()` | Extrait bbox depuis nom — utile pour identifier dalles manquantes par nom. |
| Validation LiDAR (pdal) | `src/check_terrain.py:_laz_metadata()`, `_tile_extent()`, `_coverage_pct()` | Infrastructure complète. À étendre, pas à réécrire. |
| Validation georef XML | `src/check_terrain.py:_validate_georef_xml()` | Fonctionnel. |
| Localisation KP | `src/run_engine.py:locate_binary()` | Interface propre. À étendre avec chemin config + download. |
| Déduit CRS depuis coordonnées | `src/init_terrain.py:deduce_crs()` | Parfait, conserver. |
| Écriture config terrain | `src/init_terrain.py:update_config_yaml()` | À étendre pour écrire les nouveaux champs. |

---

## 3. À MODIFIER — ce qui doit changer

### 3.1 `config.yaml` — structure terrain

Ajouter les champs suivants (optionnels à l'init, remplis par `setup`) :

```yaml
terrains:
  ma_foret:
    bbox: [...]
    crs: EPSG:2154
    departement: "14"          # écrit par init (France) ou setup
    lidar_dir: "D:/Lidar/ma_foret"   # chemin réel des dalles
    bdtopo_path: "D:/Downloads/BDTOPO_3-5_...D014.gpkg"  # chemin réel du GPKG
    kp_binary: "C:/tools/pullauta.exe"  # chemin KP si ni env var ni PATH
```

### 3.2 `src/init_terrain.py:update_config_yaml()`

- Écrire `departement` automatiquement pour EPSG:2154 (code département à déterminer depuis bbox ou saisie)
- Supprimer l'URL IGN en dur (ligne 299) — remplacer par texte générique

### 3.3 `src/init_terrain.py:cmd_init()` — affichage post-init

Remplacer l'affichage actuel par :

```
DONNÉES NÉCESSAIRES

  LiDAR HD
    6 dalles :
      LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz
      ...
    → Télécharger depuis la source officielle IGN

  BD TOPO
    → Télécharger la donnée correspondant à votre secteur
      depuis la source officielle IGN

  Karttapullautin
    → Télécharger depuis github.com/karttapullautin/karttapullautin/releases

Puis :
  python main.py ma_foret setup
```

### 3.4 `src/check_terrain.py:cmd_check()`

- Lire `lidar_dir` depuis config si disponible (au lieu de `LIDAR/` en dur)
- Lire `bdtopo_path` depuis config si disponible
- Détecter les dalles **manquantes par nom** (diff entre `list_tiles()` et dalles présentes)
- Détecter les dalles supplémentaires (info, pas erreur)
- BD TOPO : erreur si `bdtopo_path` déclaré mais fichier absent ; warning sinon
- Ajouter validation BD TOPO basique (couches nécessaires présentes, couverture)
- KP : utiliser `locate_binary()` + chemin config, afficher résultat précis

### 3.5 `main.py run`

- Lire `lidar_dir` depuis config si `--tiles-dir` non fourni
- KP : tenter `locate_binary()` puis chemin config, puis proposer setup si absent

### 3.6 `main.py tiles` (affichage)

- Supprimer `TILE_SOURCE` en dur
- Afficher clairement le dossier attendu
- Afficher le format attendu (`.copc.laz`)

---

## 4. MANQUANT — à créer

### 4.1 Commande `setup` (cœur du plan V2)

```
python main.py ma_foret setup
```

Mode interactif CLI permettant de :
1. Montrer ce qui est nécessaire (LiDAR, BD TOPO, KP)
2. Demander le chemin du dossier LiDAR
3. Scanner le dossier, valider les dalles, afficher manquants
4. Demander le chemin du fichier BD TOPO
5. Valider le GPKG (format, couches, couverture)
6. Gérer KP (détecter existant → sinon télécharger automatiquement)
7. Stocker les chemins validés dans config.yaml
8. Afficher le résultat du `check` final

### 4.2 Validation BD TOPO complète

Dans `src/check_terrain.py` :
- Couches nécessaires présentes (`troncon_de_route`, `zone_d_habitation`, `batiment`, `plan_d_eau`, `cours_d_eau`, `surface_de_transport`, `zone_de_vegetation`)
- CRS lisible
- Couverture géographique ⊇ bbox terrain (via `bbox` de la couche, pas lecture complète)

### 4.3 Téléchargement automatique KP

Dans `src/run_engine.py` ou nouveau `src/kp_install.py` :
- API GitHub : `https://api.github.com/repos/karttapullautin/karttapullautin/releases/latest`
- Détection plateforme (`sys.platform` + `platform.machine()`)
- Assets v2.15.1 disponibles (~2 MB chacun) :
  - `karttapullautin-x86_64-win.tar.gz`
  - `karttapullautin-x86_64-linux.tar.gz`
  - `karttapullautin-x86_64-macos.tar.gz`
  - `karttapullautin-arm64-win.tar.gz`
  - `karttapullautin-arm64-linux.tar.gz`
  - `karttapullautin-arm64-macos.tar.gz`
- Téléchargement dans `bin/` du projet (ou `~/.local/share/lidar-o/kp/`)
- Confirmation utilisateur avant téléchargement (afficher taille)
- Écriture du chemin dans config

### 4.4 Mode incomplet (run sans données)

`main.py run` sans données complètes doit produire :

```
LiDAR HD
  ✗ 0/6 dalles

BD TOPO
  ✗ absente

Karttapullautin
  ✗ absent

Projet incomplet — lancer : python main.py ma_foret setup
```

Au lieu d'un exit abrupt sur la première erreur.

---

## 5. À NE PAS TOUCHER

Ces fichiers ne doivent pas être modifiés — ils contiennent les algorithmes cartographiques :

| Fichier | Raison |
|---------|--------|
| `src/vegetation.py` | CO Generalization Engine (9 étapes) |
| `src/omap_writer.py` | Génération .omap XML |
| `scripts/process_hag.py` | Normalisation + classification HAG |
| `scripts/mask_vegetation.py` | Masquage anthropique |
| `scripts/generate_bdtopo.py` | BD TOPO → couches .omap |
| `scripts/generate_relief.py` | DXF KP → courbes .omap |
| `scripts/run_terrain.py` | Pipeline PDAL |
| `config.yaml` (section paramètres) | Seuils, profils, rendering — ne pas toucher |

---

## 6. Décision : copier ou référencer les fichiers LiDAR ?

**Verdict : référencer.**

Les dalles LiDAR font 500 MB à 1 GB chacune. En copier 6 pour un projet de 3 km² représente 3–6 GB de duplication sans valeur.

Le pipeline actuel (`--tiles-dir DIR`) attend déjà un répertoire — il lit depuis ce chemin sans copie. Stocker le chemin dans config.yaml est la continuité naturelle de ce comportement.

Risque : lien cassé si l'utilisateur déplace ses fichiers. Mitigé par le message d'erreur explicite (§16 du plan).

**BD TOPO** : même logique. Le GPKG fait ~350 MB compressé, ~1 GB extrait. Référencer le chemin.

---

## 7. Question ouverte : code département

`scripts/fetch.py` cherche le GPKG par `departement` (code à 2 chiffres : "14").

Ce code n'est pas déductible automatiquement depuis la bbox en Lambert-93 — il faudrait un référentiel de codes départements.

Options :
- A. Demander le code département dans `setup` (1 saisie supplémentaire)
- B. Déduire depuis un référentiel IGN embarqué (table simplifiée bbox→dept)
- C. Ne pas demander le département — scanner `bdtopo_path` pour déduire le code depuis le nom de fichier (convention IGN : `*D014*.gpkg`)

**Option C recommandée** : le nom du fichier livré par IGN contient toujours le code département (`BDTOPO_3-5_TOUSTHEMES_GPKG_LAMB93_D014_2026-06-15.gpkg`). Parser le nom évite toute saisie supplémentaire.

---

## 8. Fichiers à modifier — récapitulatif

| Fichier | Nature de la modification |
|---------|--------------------------|
| `src/init_terrain.py` | Supprimer URL IGN ; améliorer affichage post-init ; écrire `departement` si France |
| `src/check_terrain.py` | Lire `lidar_dir`/`bdtopo_path` depuis config ; dalles manquantes par nom ; validation BD TOPO ; état KP |
| `src/run_engine.py` | Lire chemin KP depuis config ; ajouter module download KP |
| `main.py` | Commande `setup` ; mode incomplet ; lire `lidar_dir` config pour run |
| `config.yaml` (structure) | Documenter les nouveaux champs optionnels dans le template commenté |

---

## 9. Nouveaux fichiers à créer

| Fichier | Contenu |
|---------|---------|
| `src/setup_terrain.py` | Logique interactive de `setup` (sélection + validation + stockage) |
| `src/kp_install.py` | Téléchargement KP depuis GitHub releases (détection plateforme, confirmation, extraction) |

---

## 10. Tests requis (rappel du plan)

Sans téléchargement réseau dans les tests automatiques :

- `init --center`, `init --bbox`
- `tiles` : 0, N dalles, bonne liste
- `check` : 0 dalle, 1 manquante, dalle supplémentaire, fichier invalide, BD TOPO absente, BD TOPO mauvaise zone, KP absent, KP présent
- Chemins Windows avec espaces
- Projet déjà configuré

Test d'intégration réel sur Grimbosq (données déjà présentes).

---

*Audit produit avant tout développement. Ne pas modifier le pipeline cartographique.*
