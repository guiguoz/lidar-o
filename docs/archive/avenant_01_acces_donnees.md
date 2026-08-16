# Avenant n°01 au plan d'exécution `co-vector-fr`

**Objet :** corrections d'accès aux données IGN + ajustements de config restés en suspens.
**S'applique à :** `plan_execution_claude_code_v2.md` et au plan d'implémentation détaillé.
**Préséance :** en cas de conflit entre cet avenant et le plan, **cet avenant prime**.
**Ne change pas l'architecture** : moteur Karttapullautin, pipeline végétation raster-first, stratégie CRT, verrous Phase 0/1, gate de validité — tout reste identique.

---

## A. Accès aux données IGN (correction critique)

### A1 — Le portail `diffusion-lidarhd.ign.fr` est obsolète
Ne **pas** l'utiliser comme route de téléchargement (il était hérité du tutoriel Cassini de 2024). L'écosystème LiDAR HD a migré vers la **Géoplateforme / cartes.gouv.fr**.

Routes correctes :
- **Téléchargement** : service « téléchargement à la carte » de la Géoplateforme — `https://cartes.gouv.fr/telechargement/...` et l'API `https://data.geopf.fr/telechargement/...`.
- **Index des dalles (WFS)** : `https://data.geopf.fr/wfs`.
- Le **nuage de points classé** (`.laz`, dont Karttapullautin a besoin) se récupère par cette voie. MNT/MNS/MNH ne sont que des produits dérivés.

### A2 — Les noms de flux WFS ont changé (octobre 2025)
Les anciens flux `IGNF_LIDAR-HD_TA:nuage-bloc` / `IGNF_LIDAR-HD_TA:nuage-dalle` ont été **dépubliés le 22 novembre 2025**. Tout code, tutoriel ou doc qui les référence est **mort**.

Noms actuels :
- `IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle`
- `IGNF_NUAGES-DE-POINTS-LIDAR-HD:bloc`

*(Le plan v2 utilisait déjà `...:dalle` — c'est le bon. Confirmation, pas changement.)*

### A3 — RÈGLE D'OR : aucun endpoint codé en dur
L'IGN renomme/migre ses endpoints régulièrement (encore en octobre/novembre 2025). **Tout nom de flux, typename WFS ou URL de téléchargement est un placeholder jusqu'à vérification en direct.**

Obligation pour `scripts/phase0_recon.py` → `test_wfs_capabilities()` :
1. Interroger le `GetCapabilities` **en direct** (`data.geopf.fr/wfs?SERVICE=WFS&REQUEST=GetCapabilities`).
2. En extraire les **vrais noms du jour** (dalles LiDAR HD + couches BD TOPO).
3. Les reporter dans `docs/etat_existant.md`.
4. **Ce sont ces valeurs vérifiées** qui remplissent les placeholders de `config.yaml`, jamais des noms recopiés d'une doc.

Conséquence : `fetch.py` lit ses noms de flux **depuis `config.yaml`** (rempli post-Phase 0), il ne les contient pas en dur.

### A4 — Source de la végétation : décision par RENDU, pas par pureté
Quatre sources possibles. ⚠️ **L'ordre ci-dessous est une préférence à coût/rendu égal, PAS un classement contraignant.** Le critère décisif n'est pas « la donnée la plus en amont gagne » (informationnel) mais « celle qui donne la meilleure base ISOM pour le moins de complexité » (**produit**). KP a été conçu pour la CO : sa quantification du sous-bois encode une heuristique métier mature, potentiellement supérieure à un PDAL brut qu'il faudrait recalibrer entièrement. Donc **si le PNG KP donne le meilleur rendu dans OOM, il gagne** — quantification comprise.

Préférence indicative (à coût/rendu comparable) :
1. **Densité continue KP**, si elle est exposée (à vérifier Phase 0 — la doc connue ne documente que des PNG).
2. **PDAL densité maison** (canaux sous-bois + canopée pondérés) — devient la vraie tête si KP ne sort que du PNG.
3. **MNH LiDAR HD** — **repli médiocre** : capture la **hauteur du couvert, pas la pénétrabilité**. Deux forêts de même canopée peuvent avoir un sous-bois opposé. À n'utiliser qu'en l'absence d'alternative ; cartographie surtout le couvert (l'erreur qu'on cherche à éviter). Téléchargeable via `cartes.gouv.fr/telechargement/IGNF_MNH-LIDAR-HD`.
4. **PNG KP rendu** — donnée la plus en aval (potentiellement déjà quantifiée), mais **peut gagner sur le rendu** (voir ci-dessus).

**La hiérarchie est subordonnée au test de rendu du spike (Phase 1).** Voir section D.

---

## B. Ajustements de config restés en suspens

### B1 — Déclarer `vegetation.source` dans `config.yaml`
`get_vegetation_raster()` s'appuie dessus mais la clé n'était pas déclarée. Ajouter au bloc `vegetation` :
```yaml
  source: PLACEHOLDER_PHASE0   # "kp" | "mnh" | "pdal" — défini manuellement après le verrou Phase 0
```

### B2 — Filtre majoritaire : trancher la dépendance
Le plan mentionne `skimage.filters.rank.majority` comme option **sans déclarer scikit-image**. Choisir :
- **Préféré (zéro dépendance)** : implémentation `np.bincount` par décalages → retirer toute mention de skimage.
- **Sinon** : ajouter `scikit-image` à `pyproject.toml`.
**Interdit dans tous les cas** : `scipy.ndimage.generic_filter` (callback Python par pixel = heures sur ~9 M px).

### B3 — Unité de `sieve_threshold`
`gdal_sieve` travaille en **pixels**, pas en m². Documenter l'unité et le lien à la résolution, sinon le sieve devient faux en silence si la résolution change :
```yaml
  sieve_threshold: 50   # en PIXELS ; = min_area_m2 / (resolution_m ** 2). À 1 m/px : 50 m² = 50 px.
```

---

## C. Sorties Karttapullautin attendues (réf. Orienteering BC — à confirmer en Phase 0)

Hypothèses nommées pour démarrer la Phase 0 sans placeholders vides. **Source : documentation Orienteering BC, basée sur la version Perl historique de KP.** ⚠️ La réécriture Rust peut avoir renommé fichiers/calques → `inspect_kp_outputs()` doit **confirmer en direct** ; ces noms sont des points de départ, pas des certitudes.

**Végétation (dossier `temp/`)** — résout l'inconnue source :
- `undergrowth.png` (+ `.pgw`) : **le sous-bois, déjà séparé de la canopée** → candidat **source primaire** (franchissabilité). C'est la couche qu'on cherchait.
- `vegetation.png` (+ `.pgw`) : végétation (haute).
- Réserve : ce sont des **PNG rendus**. Question Phase 0 précisée : ce PNG est-il **seuillable proprement**, ou faut-il une densité continue (→ MNH ou PDAL, repli) ? **Audit PNG obligatoire en Phase 0** : bit-depth (8-bit ?), palette indexée ?, déjà seuillé en N teintes ?, compression destructrice ?, histogramme des valeurs. Si déjà quantifié → on perd la finesse de calibration (lissage Étape 0, percentiles) ; ce n'est pas rédhibitoire (cf. A4 : le rendu décide), mais ça doit être **constaté**, pas supposé.

**Relief (DXF, pour câblage CRT)** :
- `out2.dxf` : courbes lissées 2,5 m (courbe de forme 1/2, maîtresse tous les 12,5 m).
- `c2.dxf` / `c3.dxf` : grandes / petites falaises.
- `dotknolls.dxf` : buttes + petites dépressions.
- `contours03.dxf` : courbes 0,3 m (très lourd).

**Piège mode batch** (pour `assemble.py`, Phase 7) : en batch, KP **concatène** les DXF → chaque courbe arrive en multiples tronçons à l'import. Gérer la fusion des tronçons de relief, ou éviter le batch si le relief vectoriel est utilisé.

**`vectorconf`** : KP mappe shapefile → symbole ISOM via un fichier `définition | code ISOM | mapping attributs`. Même logique que notre `symbols_isom.yaml` — confirme l'approche déclarative.

---

## D. Protocole de décision « source végétation » au spike (Phase 1)

La source n'est pas choisie a priori : elle est **mesurée**. Sur **une même dalle de forêt**, produire trois sorties végétation et les importer dans OOM :
1. **PNG KP `undergrowth` polygonisé** (si KP ne sort que du PNG).
2. **PDAL densité + pipeline raster-first** (canaux sous-bois/canopée).
3. **MNH** (pour constater son inadéquation — sert d'étalon « mauvais »).

**Jugement non subjectif — ancré sur des vérités-terrain.** Choisir sur la dalle **2-3 lieux que vous connaissez réellement** (une clairière, un fourré impénétrable, une lisière franche). Pour chaque source, une seule question : **place-t-elle correctement ces vérités-terrain ?** Sans ces points de contrôle, on compare des esthétiques ; avec eux, on compare des **exactitudes** — et le verdict devient défendable et reproductible.

**Gagnante = la base la plus crédible sur les vérités-terrain, pas la plus « pure ».** Le résultat fixe `config.vegetation.source` (B1) pour la suite.

---

## Rien d'autre ne change
Le reste du plan tient. Démarrage inchangé : **Phase 2 (squelette) → Phase 0 (recon) → ARRÊT au verrou humain** (`etat_existant.md` validé) avant toute implémentation des phases 3→10.
