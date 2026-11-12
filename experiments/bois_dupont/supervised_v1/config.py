"""Configuration centrale — supervised_v1 prototype."""
from __future__ import annotations
import pathlib

# ── Chemins ───────────────────────────────────────────────────────────────
_THIS = pathlib.Path(__file__).resolve().parent
_CALIB = _THIS.parent / "calibration_v2"
_DIAG  = _THIS.parent / "diagnostic_vege"

STRATES_PATH = _DIAG / "lidar_vege" / "omapmaker_strates.tif"
OCAD_PATH = pathlib.Path(
    r"E:\RunningRaid\Cartographie\ça te dit 2027\bois Dupont"
    r"\LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc_VegetationBaseMap.png"
)
LAZ_PATH = pathlib.Path(
    r"E:\RunningRaid\Cartographie\ça te dit 2027\bois Dupont"
    r"\LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz"
)
NDVD_BEST_CFG_PATH = _CALIB / "best_config.json"

DATA_DIR    = _THIS / "data"
MODELS_DIR  = _THIS / "models"
FIGURES_DIR = _THIS / "figures"

DESCRIPTORS_FILE = DATA_DIR / "descriptors.npz"
LABELS_FILE      = DATA_DIR / "labels.npy"
SPLIT_FILE       = DATA_DIR / "split.json"

for _d in (DATA_DIR, MODELS_DIR, FIGURES_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ── Grille ────────────────────────────────────────────────────────────────
# Origine OCAD et strates : centre pixel (0,0) = (425001, 6922999) Lambert 93
# Résolution 2 m/px · grille 500 × 500 px · emprise 1 km × 1 km
BBOX   = [425000.0, 6922000.0, 426000.0, 6923000.0]  # xmin ymin xmax ymax
CRS    = "EPSG:2154"
RES_M  = 2.0
GRID_H = 500
GRID_W = 500

# ── Palette OCAD et classes ───────────────────────────────────────────────
# Source : run_calibration_v2.py (confirmée sur le PNG 500×500)
OCAD_PALETTE: dict[tuple[int, int, int], str] = {
    (255, 201,  15): "decouvert",
    (255, 255, 255): "blanc",
    (204, 255, 179): "veg_406",
    (153, 255, 102): "veg_408",
    ( 51, 255,   0): "veg_410",
    ( 25,  25,  25): "bati",   # exclu de l'apprentissage
}

# Classes numériques (bati exclu ; couleur non reconnue → LABEL_NODATA)
CLASS_NAMES = ["decouvert", "blanc", "veg_406", "veg_408", "veg_410"]
CLASS_CODES: dict[str, int] = {name: i for i, name in enumerate(CLASS_NAMES)}
N_CLASSES   = len(CLASS_NAMES)

LABEL_NODATA: int = 255   # sentinelle : bati + couleur non reconnue + cellule sans support LiDAR

# Couleurs de rendu des classes (RGB)
CLASS_DISPLAY: dict[str, tuple[int, int, int]] = {
    "decouvert": (255, 201,  15),
    "blanc":     (255, 255, 255),
    "veg_406":   (204, 255, 179),
    "veg_408":   (153, 255, 102),
    "veg_410":   ( 51, 255,   0),
}
NODATA_COLOR: tuple[int, int, int] = (180, 0, 220)  # violet

# ── Bornes des strates (src/omapmaker_ref.py) ────────────────────────────
# band 0 = g (HAG < H_LOW), band 1 = low, band 2 = med, band 3 = high
H_LOW  = 0.2  # m
H_MED  = 1.5  # m
H_HIGH = 3.0  # m

# ── Descripteurs — échelles spatiales ────────────────────────────────────
# Format : (nom, sigma_m) · radius ≈ 2 × sigma_m
# truncate=2.0 → kernel 2*floor(2*sigma_px)+1 : à 2 m/px :
#   sigma_m=1.0 → sigma_px=0.5 → kernel 3×3 px  (rayon ≈ 2 m)
#   sigma_m=3.0 → sigma_px=1.5 → kernel 7×7 px  (rayon ≈ 6 m)
#   sigma_m=6.0 → sigma_px=3.0 → kernel 13×13 px (rayon ≈ 12 m)
SCALES: list[tuple[str, float]] = [
    ("2m",  1.0),
    ("6m",  3.0),
    ("12m", 6.0),
]
TRUNCATE    = 2.0
MIN_SUPPORT = 1e-9   # n_total_native > MIN_SUPPORT → cellule évaluable

# Poids NDVD best_v2 (descripteur uniquement, pas décision finale)
W_LOW  = 0.35
W_MED  = 0.55
W_HIGH = 0.10

# ── Découpage spatial ─────────────────────────────────────────────────────
# Bandes horizontales parallèles (axe des lignes, Y décroissant)
# Marge 15 px = 30 m >> portée max descripteurs (12 m)
# train  185 × 500 = 92 500 px  · val 135 × 500 = 67 500 px  · test 150 × 500 = 75 000 px
SPLIT_CFG: dict[str, dict] = {
    "train": {"r0":   0, "r1": 185, "c0": 0, "c1": 500},
    "val":   {"r0": 200, "r1": 335, "c0": 0, "c1": 500},
    "test":  {"r0": 350, "r1": 500, "c0": 0, "c1": 500},
    # marges exclues de tous les ensembles : rows [185,200) et [335,350)
}
MARGIN_PX   = 15
RANDOM_SEED = 42

# ── Configurations modèles (12 au total) ─────────────────────────────────
# type RF = RandomForestClassifier · ET = ExtraTreesClassifier
# weight "balanced" ou "balanced_subsample"
MODEL_GRID: list[dict] = [
    {"id":  1, "type": "RF", "n":  100, "depth": None, "leaf":  1, "weight": "balanced"},
    {"id":  2, "type": "RF", "n":  200, "depth": None, "leaf":  1, "weight": "balanced"},
    {"id":  3, "type": "RF", "n":  300, "depth": None, "leaf":  1, "weight": "balanced"},
    {"id":  4, "type": "RF", "n":  200, "depth":   10, "leaf":  1, "weight": "balanced"},
    {"id":  5, "type": "RF", "n":  200, "depth":   20, "leaf":  1, "weight": "balanced"},
    {"id":  6, "type": "RF", "n":  200, "depth": None, "leaf":  5, "weight": "balanced"},
    {"id":  7, "type": "RF", "n":  200, "depth": None, "leaf": 10, "weight": "balanced"},
    {"id":  8, "type": "RF", "n":  200, "depth": None, "leaf":  1, "weight": "balanced_subsample"},
    {"id":  9, "type": "ET", "n":  200, "depth": None, "leaf":  1, "weight": "balanced"},
    {"id": 10, "type": "ET", "n":  200, "depth":   10, "leaf":  1, "weight": "balanced"},
    {"id": 11, "type": "ET", "n":  200, "depth": None, "leaf":  5, "weight": "balanced"},
    {"id": 12, "type": "RF", "n":  200, "depth":   20, "leaf":  5, "weight": "balanced"},
]

# Critère de sélection : macro-IoU sur val (classes absentes = IoU 0 comptées)
SELECTION_METRIC = "macro_iou_val"
