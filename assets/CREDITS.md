# Crédits assets

## Ressources cartographiques

- **ISOM 2017-2_10000.omap** : gabarit de symboles extrait d'OpenOrienteering Mapper
  (GPL-3.0, https://www.openorienteering.org/)

- **kp_crt.crt** : table de correspondance DXF→ISOM extraite de Blaze (Trailblaze Software,
  GPL-3.0, https://github.com/Trailblaze-Software/Blaze)

## Moteur terrain — Karttapullautin (KP)

- **bin/pullauta.exe** : Karttapullautin v2.12.1
  Source : https://github.com/karttapullautin/karttapullautin/releases/tag/v2.12.1
  Licence : **GNU General Public License v3.0 (GPL-3.0)**
  SHA-256 vérifié : `3fd713b7b442b84649834d15badd1974eb1e928ec01bc3a948fdecf92883a0d8`
  (correspondance confirmée avec l'asset `karttapullautin-x86_64-win.tar.gz` de la release officielle)
  Texte GPL-3.0 inclus : `bin/LICENSE.karttapullautin`

  **Obligations de redistribution GPL-3.0 :**
  - Inclure le texte GPL-3.0 dans la distribution (fourni dans `bin/LICENSE.karttapullautin`).
  - Rendre le code source disponible ou fournir une offre écrite pour le faire.
    Le code source est accessible à l'URL ci-dessus.
  - La licence GPL-3.0 s'applique à pullauta.exe en tant qu'exécutable autonome (subprocess).
    Elle n'impose pas l'ouverture du code de LidarO, qui ne lie pas pullauta statiquement.

## Modèle supervised_e

- **models/model_e_final.pkl** : modèle RandomForest entraîné sur 4 terrains
  (bd, caen, montmirel, sainte_anne — 1 134 385 pixels au total).
  SHA-256 : `48da30428cb0f42479ad5d28d668174a5e710bfdde02fa44c5f539aad320eeb5`
  Toutes les annotations d'entraînement sont issues de cartes appartenant au distributeur.
  Évaluations disponibles : LOTO 4 folds (réemploi + hors-entraînement par fold) —
  voir `experiments/loto_v1/results_e/`.

## Dépendances Python embarquées (sélection)

| Composant        | Licence        | Notes                                      |
|---|---|---|
| GDAL 3.12        | MIT            | gdal.org                                   |
| PROJ 9.8         | MIT            | proj.org                                   |
| GEOS 3.14        | LGPL 2.1       | libgeos.org — liaison dynamique            |
| PDAL 3.5         | BSD 3-Clause   | pdal.io                                    |
| numpy / scipy    | BSD 3-Clause   | —                                          |
| scikit-learn     | BSD 3-Clause   | —                                          |
| Geopandas        | BSD 3-Clause   | —                                          |
| Shapely          | BSD 3-Clause   | —                                          |
| Rasterio         | BSD 3-Clause   | —                                          |
| Pillow           | HPND           | équivalent MIT / libre commercial          |
| ezdxf            | MIT            | —                                          |
| PyYAML           | MIT            | —                                          |
| OpenSSL 3.6      | Apache 2.0     | —                                          |
| Tk/Tcl 8.6       | Tcl/Tk License | libre, redistribution autorisée            |
| Python 3.13      | PSF            | python.org                                 |

La redistribution en binaire embarqué est compatible avec toutes les licences ci-dessus
(MIT, BSD, Apache, LGPL liaison dynamique, PSF, Tcl/Tk) pour un usage libre ou commercial,
sous réserve d'inclure les notices de copyright applicables.
GEOS étant lié dynamiquement (DLL), la LGPL n'impose pas d'ouvrir le code de l'application.
