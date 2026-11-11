MÉGA-SYNTHÈSE OPÉRATIONNELLE — KARTTAPULLAUTIN POUR CARTES DE COURSE D’ORIENTATION
Document destiné à une IA. Aucune définition de KP. Uniquement paramètres, fichiers, commandes, presets, workflows, sources.

1. PARAMÈTRES pullauta.ini — VALEURS ET USAGES
1.1 Paramètres généraux
Paramètre	Rôle	Défaut	Valeurs utilisateurs / notes
northlinesangle	Angle de déclinaison magnétique	0	4 (Suède), 10 (Canada), -5 (France selon zone), 7 (Norvège), 9 (Finlande), 8 (Scandinavie), 3 (montagne), 0 (urbain), -2 (France)
thinfactor	Sous-échantillonnage LiDAR	1	0.5 si densité > 10 pts/m² ; 0.25 tests rapides / montagne ; 0.33 Norvège
basemapinterval	Intervalle contours de base (m)	2.5	1.25, 0.625 (très détaillé) ; 5 (zones plates)
contourinterval	Intervalle contours finaux (m)	2.5	1.25 (compétition) ; 5 (entraînement)
processes	Processus parallèles	1	4 (CPU 4 cœurs) ; 8 (CPU 8 cœurs)
parallel_laz_decompression	Décompression LAZ parallèle	0	1 recommandé
output_dxf	DXF classiques au lieu de binaires	0	1 obligatoire pour OOM/OCAD
vectorconf	Config données vectorielles	""	"osm.txt", "fastighetskartan.txt", "fkb.txt"
epsg	Code EPSG	""	32631 (UTM 31N France) ; 3067 (ETRS89 / UTM 33N Finlande)
scale	Échelle carte	10000	15000
1.2 Paramètres de végétation
Paramètre	Rôle	Défaut	Valeurs utilisateurs / notes
greenshades	Seuils 5 niveaux de vert	0.2,0.4,0.6,0.8,1.0	Forêt dense : 0.15,0.35,0.55,0.75,0.95 ; zones ouvertes : 0.25,0.45,0.65,0.85,1.0 ; départ large : 0.4|0.8|1.3|1.9|2.6 ; karst final : 0.64|0.98|1.37 ; montagne : 0.25|0.45|0.65|0.85|1.0 ; urbain : 0.3|0.5|0.7|0.85|1.0
pointvolumefactor	Compensation densité LiDAR	0.15	0.25–0.35 si rayures vertes ; karst 0.15
undergrowth	Détection végétation basse	0	1 recommandé pour cartes détaillées ; 0 montagne/urbain
vegetation	Génération couche végétation	1	Toujours 1 sauf tests rapides
vege_smooth	Lissage végétation	1	0 pour rendu plus brut
yellowheight	Hauteur max zone ouverte	—	0.88 (karst) ; 1.5 pour mieux détecter sous-bois
yellowthresold	% points sous yellowheight pour jaune	—	0.89 (karst)
greenground	Vert de fond	—	0.8 (karst)
zone1	Plage hauteur calcul verdissement	—	0.5|4|99|1 (karst)
zone2	Plage hauteur calcul verdissement	—	4|7|10.0|0.4 (karst)
threshold1	Plage hauteur + facteur	—	0.20|2.5|0.28 (karst)
threshold2	Plage hauteur + facteur	—	2.5|5|0.37 (karst)
threshold3	Plage hauteur + facteur	—	5|8|0.43 (karst)
threshold4	Plage hauteur + facteur	—	8|12|0.39 (karst)
threshold5	Plage hauteur + facteur	—	12|99|0.37 (karst)
Méthode de calibration végétation :

Partir large : greenshades=0.4|0.8|1.3|1.9|2.6.

Éliminer rayures vertes via pointvolumefactor (0.15 → 0.35).

Affiner greenshades par comparaison avec carte IOF existante.

Utiliser threshold1 à threshold5 pour contrôler hauteur canopée.

Sauvegarder pullauta.ini après chaque configuration réussie.

1.3 Rochers et falaises
Paramètre	Rôle	Défaut	Valeurs utilisateurs
cliffheight	Hauteur min falaise (m)	1.0	0.8 (plus sensible) ; 1.2 (montagne) ; 1.5 (urbain)
cliffangle	Angle min falaise (°)	45	40 (plus sensible) ; 50 (plus strict)
stoneheight	Hauteur min rocher (m)	0.5	0.3 (petits rochers)
stoneangle	Angle min rocher (°)	30	25 (plus sensible)
Note : KP génère par défaut deux types de falaises : passable (hauteur min. 1.2 m) et impassable (hauteur min. 2.5 m).

2. PRESETS COMPLETS
2.1 Forêt dense — Scandinavie / Canada
Source : World of O (Norvège).

ini
[General]
northlinesangle = 8
thinfactor = 0.5
basemapinterval = 2.5
contourinterval = 2.5
processes = 4
parallel_laz_decompression = 1
output_dxf = 1

[Vegetation]
greenshades = 0.15,0.35,0.55,0.75,0.95
undergrowth = 1
vegetation = 1

[Rocks]
cliffheight = 0.8
cliffangle = 40
stoneheight = 0.3

[Vector]
vectorconf = fastighetskartan.txt
2.2 Zone mixte — France (LiDAR IGN)
Source : Mapant.fr.

ini
[General]
northlinesangle = -2
thinfactor = 1
basemapinterval = 2.5
contourinterval = 2.5
processes = 2
parallel_laz_decompression = 1

[Vegetation]
greenshades = 0.2,0.4,0.6,0.8,1.0
undergrowth = 1

[Rocks]
cliffheight = 1.0
cliffangle = 45

[Vector]
vectorconf = osm.txt
epsg = 32631
2.3 Terrain montagneux — Alpes
Source : Attackpoint.

ini
[General]
northlinesangle = 3
thinfactor = 0.25
basemapinterval = 1.25
contourinterval = 1.25
processes = 4

[Vegetation]
greenshades = 0.25,0.45,0.65,0.85,1.0
undergrowth = 0

[Rocks]
cliffheight = 1.2
cliffangle = 50
stoneheight = 0.5
2.4 Zone urbaine — Parc en ville
Source : Nopesport Forum.

ini
[General]
northlinesangle = 0
thinfactor = 1
basemapinterval = 2.5
contourinterval = 2.5

[Vegetation]
greenshades = 0.3,0.5,0.7,0.85,1.0
undergrowth = 0

[Rocks]
cliffheight = 1.5
cliffangle = 45

[Vector]
vectorconf = osm.txt
2.5 Terrain karstique — Slovénie
Source : étude ICA 2017.

ini
[General]
pointvolumefactor = 0.15

[Vegetation]
greenground = 0.8
zone1 = 0.5|4|99|1
zone2 = 4|7|10.0|0.4
threshold1 = 0.20|2.5|0.28
threshold2 = 2.5|5|0.37
threshold3 = 5|8|0.43
threshold4 = 8|12|0.39
threshold5 = 12|99|0.37
greenshades = 0.64|0.98|1.37
yellowheight = 0.88
yellowthresold = 0.89
3. FICHIERS PRODUITS PAR KP ET USAGE DANS OCAD
Fichier	Description	Usage OCAD
pullautus.png	Carte finale, 600 DPI, sans dépressions, géoréférencée .pgw	Alternative propre si dépressions gênent
pullautus_depr.png	Carte finale avec dépressions en violet, 600 DPI, .pgw	Fond principal le plus utilisé (≈80%) : contours + falaises + végétation + dépressions
vegetation.png	Dans temp/, fond végétation uniquement (vert/jaune), géoréférencé .pgw	Fond isolé pour tracer la végétation sans distraction
undergrowth.png	Végétation basse	Fond spécialisé sous-bois ; peu utilisé comme fond unique
blueblack.png	Eau	Peu utilisé comme fond principal
c2.png	Grandes falaises	Complément
out2.dxf	Contours lissés (intervalle 2,5 m par défaut)	Import OCAD/OOM + conversion symboles
c1g.dxf	Petites falaises	Import OCAD/OOM
c2g.dxf	Grandes falaises	Import OCAD/OOM
dotknolls.dxf	Collines et petites dépressions en U	Import OCAD/OOM
.pgw	Géoréférencement PNG	À importer avec le PNG
.jgw	Géoréférencement JPG	Renommer .pgw → .jgw si conversion PNG → JPG
Workflow OCAD :

Option 1 — Fond unique : importer pullautus_depr.png + .pgw comme fond. Échelle 1:10 000 ou 1:15 000. Tracer la végétation directement.

Option 2 — Raster + vectoriel : importer vegetation.png + .pgw comme fond. Importer out2.dxf, c1g.dxf, c2g.dxf. Convertir DXF en symboles OCAD. Résultat équivalent à pullautus.png.

Option 3 — Comparaison : pullautus_depr.png + DSM hillshades + photo aérienne Google Earth Pro pour sous-bois.

Fichier CRT : nécessaire pour importer les DXF dans OOM/OCAD avec symboles IOF. Disponible sur Orienteering BC (supprimer extension .txt).

Impression : IrfanView → ouvrir PNG → Image > Information → résolution 600 x 600 DPI → enregistrer → imprimer avec Print size: Original Size from DPI → échelle 1:10 000 ou 1:15 000.

4. COMMANDES KP
4.1 Génération de base
bash
pullauta.exe mon_fichier.laz        # Windows
./pullauta mon_fichier.laz          # Linux/Mac
./pullauta                          # Re-rendu après modification pullauta.ini
4.2 Re-processing ciblé
bash
./pullauta makevegenew              # Re-génère uniquement la végétation
./pullauta makevege                 # Variante selon source
./pullauta makecliffs xyztemp.xyz 1.0 1.15   # Re-génère falaises (fichier XYZ, hauteur min, angle min)
./pullauta makecontours             # Re-génère uniquement les contours
4.3 Mode batch
ini
batch = 1
input_dir = ./input
output_dir = ./output
processes = 4
bash
./pullauta
./pullauta pngmerge 1        # Fusionne PNG sans dépressions ; 1=100%, 2=50%, 4=25%
./pullauta pngmergedepr 1    # Fusionne PNG avec dépressions
./pullauta pngmergevege 1    # Fusionne fonds végétation
./pullauta dxfmerge          # Fusionne DXF
4.4 Préparation données
bash
# LiDAR : conversion / projection
las2las -i input.las -merged -o output.laz -epsg 3005 -target_utm 11N

# OSM → Shapefile
ogr2ogr --config OSM_USE_CUSTOM_INDEXING NO -skipfailures -f "ESRI Shapefile" output_shapes map.osm -overwrite -t_srs EPSG:3067
zip -r -j map.shp.zip output_shapes/*
5. PROBLÈMES COURANTS ET SOLUTIONS
Problème	Cause	Solution
Trop de vert	greenshades trop bas	Augmenter seuils (ex : 0.3,0.5,0.7,0.85,1.0)
Rayures vertes	pointvolumefactor trop bas	Augmenter à 0.25–0.35
Pas assez de falaises	cliffheight / cliffangle trop élevés	Baisser cliffheight à 0.8 ou cliffangle à 40
Temps de traitement trop long	Densité LiDAR élevée	thinfactor=0.5 ou 0.25
Manque RAM	Fichiers LiDAR trop grands	Mode batch processes=4
Contours trop espacés	basemapinterval / contourinterval trop grands	Réduire à 1.25 ou 0.625
Géoréférencement incorrect	Projection incorrecte	Vérifier EPSG dans pullauta.ini ou métadonnées LiDAR
DXF non importables OOM/OCAD	Format binaire par défaut	output_dxf=1
Dépressions non visibles	Fichier pullautus_depr.png non généré	Vérifier traitement
6. BONNES PRATIQUES CONFIRMÉES
Données LiDAR : .las, .laz, .xyz classifiés (sol + végétation). Unités en mètres. Densité idéale ≥ 2 pts/m².

Tester sur fichier 1 km² avant zone entière.

Sauvegarder pullauta.ini après chaque test réussi.

Activer parallel_laz_decompression=1.

Vérifier pullautus_depr.png (dépressions en violet) avant finalisation.

Comparer avec carte IOF existante pour ajuster greenshades, cliffheight.

Importer DXF dans OOM/OCAD avec fichier CRT pour symboles IOF.

Fusionner tuiles en batch pour grandes zones.

Éviter : ignorer .pgw, utiliser blueblack.png ou undergrowth.png comme fond unique, oublier de convertir DXF en symboles OCAD, imprimer sans ajuster DPI.

7. SOURCES
GitHub karttapullautin/karttapullautin

Orienteering BC — Basemap Generation

Mapant.fr — Karttapullautin pour les nuls

Routegadget — greenmapping.pdf

Attackpoint — threads LiDAR / pullauta.ini examples

Nopesport Forum — Amateur orienteering mapping

World of O — pullautin-norge

Medium — Greg Wilson, Generating map inputs with Karttapullautin

Jonasgson — Så använder man Karttapullautin

Theseus.fi — Karttapullautin thesis (Harald Joachim)

ICA 2017 — Automatically Generated Vegetation Density Maps

IGN — LiDAR HD

OpenStreetMap Export

Studylib — Use Karttapullautin

NOAA Magnetic Declination Calculator

Fichier CRT Orienteering BC

8. RÉSUMÉ DÉCISIONNEL POUR OCAD
Besoin	Fichier à utiliser	Paramètres clés
Fond principal complet	pullautus_depr.png + .pgw	output_dxf=1, parallel_laz_decompression=1
Tracer uniquement végétation	vegetation.png + .pgw	greenshades, pointvolumefactor, undergrowth
Superposition raster + vectoriel	vegetation.png + out2.dxf + c1g.dxf + c2g.dxf	output_dxf=1, CRT OCAD
Vue d’ensemble rapide	pullautus.png + .pgw	—
Analyse sous-bois	undergrowth.png + pullautus_depr.png + photos aériennes	undergrowth=1, yellowheight=1.5