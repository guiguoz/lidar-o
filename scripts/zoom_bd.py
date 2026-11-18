"""Génère le zoom annoté B vs D sur le bois trapézoïdal.

Trouées blanc enclavées annotées avec la proportion de surface conservée
(label proportionnel, pas binaire conservee/perdue).
"""
from __future__ import annotations
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from scripts.trous_analysis import (
    build_trapeze_mask,
    get_interior_trous,
    mask_boundary,
    overlap_label,
    TRAPEZE_VERTICES,
)
from src.kp_raster import _rgb_lookup, read_ini_vege_params

# ── Configuration ─────────────────────────────────────────────────────────────

FENETRE = dict(row0=0, row1=340, col0=550, col1=920)
SCALE = 3
FONT_PATH = "C:/Windows/Fonts/arial.ttf"

EXP_INI = {
    "B_med1-1_t01": "out_kp_bois_dupont/test/pullauta.ini",
    "D_med3-5_t01": "out_kp_bois_dupont/exp_d/pullauta.ini",
}


# ── Chargement ─────────────────────────────────────────────────────────────────

def load_shade_crop(png_path: str, ini_path: str) -> np.ndarray:
    params = read_ini_vege_params(ini_path)
    lut = _rgb_lookup(params)
    img = Image.open(png_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    r_ch, g_ch, b_ch = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    packed = (r_ch.astype(np.uint32) * 65536
              + g_ch.astype(np.uint32) * 256
              + b_ch.astype(np.uint32))
    shade = np.full(packed.shape, 255, dtype=np.uint8)
    for rgb, idx in lut.items():
        key = rgb[0] * 65536 + rgb[1] * 256 + rgb[2]
        shade[packed == key] = idx
    return shade[FENETRE["row0"]:FENETRE["row1"], FENETRE["col0"]:FENETRE["col1"]]


def load_crop_rgb(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    return arr[FENETRE["row0"]:FENETRE["row1"], FENETRE["col0"]:FENETRE["col1"]]


# ── Contour raster ─────────────────────────────────────────────────────────────

def make_contour(binary: np.ndarray) -> np.ndarray:
    struct4 = ndimage.generate_binary_structure(2, 1)
    return binary & ~ndimage.binary_erosion(binary, structure=struct4)


# ── Annotation des trouées ─────────────────────────────────────────────────────

def classify_b_blobs(
    b_shade: np.ndarray,
    d_shade: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Retourne (labeled_b, high_pct_map, low_pct_map, d_new_map).

    high_pct_map : pixels de CC_B avec pct_overlap >= 50
    low_pct_map  : pixels de CC_B avec pct_overlap < 50
    d_new_map    : pixels de CC_D sans source dans B
    """
    KP_BLANC, KP_JAUNE = 0, 1
    lab_b, int_ids_b = get_interior_trous(b_shade, mask)
    lab_d, int_ids_d = get_interior_trous(d_shade, mask)

    high_pct = np.zeros(mask.shape, dtype=bool)
    low_pct  = np.zeros(mask.shape, dtype=bool)
    d_new    = np.zeros(mask.shape, dtype=bool)

    d_nonvert = (d_shade == KP_BLANC) | (d_shade == KP_JAUNE)

    for cid in int_ids_b:
        px = lab_b == cid
        ov = (px & d_nonvert).sum()
        pct = 100.0 * ov / px.sum() if px.sum() > 0 else 0.0
        if pct >= 50:
            high_pct |= px
        else:
            low_pct |= px

    b_nonvert = (b_shade == KP_BLANC) | (b_shade == KP_JAUNE)
    for cid in int_ids_d:
        px = lab_d == cid
        ov_b = (px & b_nonvert).sum()
        pct_b = 100.0 * ov_b / px.sum() if px.sum() > 0 else 0.0
        if pct_b < 50:
            d_new |= px

    return lab_b, high_pct, low_pct, d_new


# ── Dessin des contours sur image ─────────────────────────────────────────────

def draw_contour_color(
    pix: np.ndarray,
    binary: np.ndarray,
    color: tuple[int, int, int],
    scale: int,
) -> None:
    contour = make_contour(binary)
    for y, x in zip(*np.where(contour)):
        for dy in range(scale):
            for dx in range(scale):
                pix[y * scale + dy, x * scale + dx] = color


# ── Composition finale ────────────────────────────────────────────────────────

def main() -> None:
    with open("results_vege_abc.json") as f:
        r = json.load(f)
    paths = {e["exp"]: e["decode"]["path"] for e in r["results"]}

    H, W = (FENETRE["row1"] - FENETRE["row0"],
             FENETRE["col1"] - FENETRE["col0"])

    mask = build_trapeze_mask((H, W), TRAPEZE_VERTICES, "scripts/bois_trapeze_mask.npy")

    b_shade = load_shade_crop(paths["B_med1-1_t01"], EXP_INI["B_med1-1_t01"])
    d_shade = load_shade_crop(paths["D_med3-5_t01"], EXP_INI["D_med3-5_t01"])

    _, high_pct, low_pct, d_new = classify_b_blobs(b_shade, d_shade, mask)

    b_rgb = load_crop_rgb(paths["B_med1-1_t01"])
    d_rgb = load_crop_rgb(paths["D_med3-5_t01"])

    b_pix = np.array(Image.fromarray(b_rgb).resize((W * SCALE, H * SCALE), Image.NEAREST))
    d_pix = np.array(Image.fromarray(d_rgb).resize((W * SCALE, H * SCALE), Image.NEAREST))

    mask_contour = make_contour(mask)

    # Contour masque trapeze (rouge)
    draw_contour_color(b_pix, mask, (255, 0, 0), SCALE)
    draw_contour_color(d_pix, mask, (255, 0, 0), SCALE)

    # Trouées B avec proportion (vert >= 50%, orange < 50%)
    draw_contour_color(b_pix, high_pct, (0, 200, 0), SCALE)
    draw_contour_color(b_pix, low_pct,  (220, 100, 0), SCALE)

    # Nouvelles trouées D sans source dans B (cyan)
    draw_contour_color(d_pix, d_new, (0, 180, 220), SCALE)

    b_img = Image.fromarray(b_pix)
    d_img = Image.fromarray(d_pix)

    # Récupérer les chiffres du JSON
    b_oz = next(e["open_zones_trapeze"] for e in r["results"] if e["exp"] == "B_med1-1_t01")
    d_oz = next(e["open_zones_trapeze"] for e in r["results"] if e["exp"] == "D_med3-5_t01")
    n_high = int(np.sum(high_pct) > 0)  # fallback si no json detail
    # Compter les blobs à partir du masque annoté
    _, n_high = ndimage.label(high_pct)
    _, n_low  = ndimage.label(low_pct)
    _, n_new  = ndimage.label(d_new)

    try:
        font    = ImageFont.truetype(FONT_PATH, 15)
        font_sm = ImageFont.truetype(FONT_PATH, 12)
    except Exception:
        font = font_sm = ImageFont.load_default()

    WW, HH = W * SCALE, H * SCALE
    MARGIN, LABEL_H, LEG_H = 4, 28, 44
    TOTAL_W = WW * 2 + MARGIN * 3
    TOTAL_H = HH + LABEL_H + MARGIN * 2 + LEG_H

    out = Image.new("RGB", (TOTAL_W, TOTAL_H), (210, 210, 210))
    out.paste(b_img, (MARGIN, LABEL_H + MARGIN))
    out.paste(d_img, (WW + MARGIN * 2, LABEL_H + MARGIN))

    draw = ImageDraw.Draw(out)

    # Titres
    draw.text((MARGIN + 4, 7), "B  med1/1  thresold=0.1", fill=(0, 0, 0), font=font)
    draw.text((WW + MARGIN * 2 + 4, 7),
              "D  med3/5  thresold=0.1", fill=(0, 0, 0), font=font)

    # Légende ligne 1
    ly = LABEL_H + MARGIN + HH + 4
    draw.rectangle([MARGIN, ly + 3, MARGIN + 14, ly + 13],
                   fill=(180, 180, 180), outline=(255, 0, 0))
    draw.text((MARGIN + 18, ly + 1), "bois trapeze", fill=(200, 0, 0), font=font_sm)

    draw.rectangle([130, ly + 3, 144, ly + 13],
                   fill=(180, 180, 180), outline=(0, 200, 0))
    draw.text((148, ly + 1),
              f"blanc enclave >=50% conserve ({n_high})",
              fill=(0, 140, 0), font=font_sm)

    draw.rectangle([430, ly + 3, 444, ly + 13],
                   fill=(180, 180, 180), outline=(220, 100, 0))
    draw.text((448, ly + 1),
              f"blanc enclave <50% conserve ({n_low})",
              fill=(180, 70, 0), font=font_sm)

    # Légende ligne 2
    ly2 = ly + 20
    b_chiffres = (f"B: {b_oz['blanc_enclave_n']} CC blanc ({b_oz['blanc_enclave_ha']:.3f} ha)  "
                  f"jaune {b_oz['jaune_enclave_n']} CC ({b_oz['jaune_enclave_ha']:.3f} ha)")
    d_chiffres = (f"D: {d_oz['blanc_enclave_n']} CC blanc ({d_oz['blanc_enclave_ha']:.3f} ha)  "
                  f"jaune {d_oz['jaune_enclave_n']} CC ({d_oz['jaune_enclave_ha']:.3f} ha)")
    draw.text((MARGIN + 4, ly2), b_chiffres, fill=(60, 60, 60), font=font_sm)

    draw.rectangle([WW + MARGIN * 2 + 4, ly + 3, WW + MARGIN * 2 + 18, ly + 13],
                   fill=(180, 180, 180), outline=(0, 180, 220))
    draw.text((WW + MARGIN * 2 + 22, ly + 1),
              f"nouveau ({n_new})", fill=(0, 130, 180), font=font_sm)
    draw.text((WW + MARGIN * 2 + 4, ly2), d_chiffres, fill=(60, 60, 60), font=font_sm)

    # Échelle
    bar_px = 50 * SCALE
    bx0, by0 = MARGIN + 8, LABEL_H + MARGIN + HH - 22
    draw.rectangle([bx0, by0, bx0 + bar_px, by0 + 7], fill=(0, 0, 0))
    draw.text((bx0, by0 - 15), "50 m", fill=(0, 0, 0), font=font_sm)

    out.save("docs/images/bois_dupont_BD_zoom.png", optimize=True)
    print(f"Saved docs/images/bois_dupont_BD_zoom.png  {TOTAL_W}x{TOTAL_H}")
    print(f"B: {b_oz['blanc_enclave_n']} blobs blancs enclave "
          f"({b_oz['blanc_enclave_ha']:.3f} ha) / {n_high} >= 50% / {n_low} < 50%")
    print(f"D: {d_oz['blanc_enclave_n']} blobs blancs enclave "
          f"({d_oz['blanc_enclave_ha']:.3f} ha) / {n_new} nouveaux")


if __name__ == "__main__":
    main()
