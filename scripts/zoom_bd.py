"""Génère le zoom annoté B vs D pour le bois NE."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import json
from scipy import ndimage
import sys

sys.path.insert(0, ".")
from src.kp_raster import _rgb_lookup, read_ini_vege_params

FENETRE = dict(row0=0, row1=340, col0=550, col1=920)
mask = np.load("scripts/bois_NE_mask.npy")

with open("results_vege_abc.json") as f:
    r = json.load(f)


def load_shade_crop(png_path, ini_path):
    params = read_ini_vege_params(ini_path)
    lut = _rgb_lookup(params)
    img = Image.open(png_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    r_ch, g_ch, b_ch = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    packed = (
        r_ch.astype(np.uint32) * 65536
        + g_ch.astype(np.uint32) * 256
        + b_ch.astype(np.uint32)
    )
    shade = np.full(packed.shape, 255, dtype=np.uint8)
    for rgb, idx in lut.items():
        key = rgb[0] * 65536 + rgb[1] * 256 + rgb[2]
        shade[packed == key] = idx
    return shade[FENETRE["row0"]:FENETRE["row1"], FENETRE["col0"]:FENETRE["col1"]]


EXP_INI = {
    "B_med1-1_t01": "out_kp_bois_dupont/test/pullauta.ini",
    "D_med3-5_t01": "out_kp_bois_dupont/exp_d/pullauta.ini",
}
paths = {e["exp"]: e["decode"]["path"] for e in r["results"]}

b_shade = load_shade_crop(paths["B_med1-1_t01"], EXP_INI["B_med1-1_t01"])
d_shade = load_shade_crop(paths["D_med3-5_t01"], EXP_INI["D_med3-5_t01"])

KP_BLANC, KP_JAUNE = 0, 1


def get_interior_trous(shade, mask):
    nonvert = ((shade == KP_BLANC) | (shade == KP_JAUNE)) & mask
    labeled, n = ndimage.label(nonvert)
    border_mask = np.zeros_like(mask, dtype=bool)
    border_mask[0, :] = mask[0, :]
    border_mask[-1, :] = mask[-1, :]
    border_mask[:, 0] = mask[:, 0]
    border_mask[:, -1] = mask[:, -1]
    border_cc = set(np.unique(labeled[border_mask])) - {0}
    int_ids = [i + 1 for i in range(n) if (i + 1) not in border_cc]
    return labeled, int_ids


b_lab, b_int_ids = get_interior_trous(b_shade, mask)
d_lab, d_int_ids = get_interior_trous(d_shade, mask)

# Classify B trouées
b_conserved_ids, b_lost_ids = [], []
for cid in b_int_ids:
    px = b_lab == cid
    ov = (px & ((d_shade == KP_BLANC) | (d_shade == KP_JAUNE))).sum()
    if 100 * ov / px.sum() >= 50:
        b_conserved_ids.append(cid)
    else:
        b_lost_ids.append(cid)

# New D trouées (majority not from B)
d_new_ids = []
for cid in d_int_ids:
    px = d_lab == cid
    ov_b = (px & ((b_shade == KP_BLANC) | (b_shade == KP_JAUNE))).sum()
    if 100 * ov_b / px.sum() < 50:
        d_new_ids.append(cid)

print(
    f"B: {len(b_int_ids)} trouees interieures: {len(b_conserved_ids)} conservees, {len(b_lost_ids)} perdues"
)
print(f"D: {len(d_int_ids)} trouees interieures: {len(d_new_ids)} nouvelles")


def make_contour_map(labeled, ids):
    cc_map = np.isin(labeled, ids)
    padded = np.pad(cc_map, 1, constant_values=False)
    interior = (
        padded[1:-1, 1:-1]
        & padded[0:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, 0:-2]
        & padded[1:-1, 2:]
    )
    return cc_map & ~interior


def make_mask_contour(mask):
    padded = np.pad(mask, 1, constant_values=False)
    interior = (
        padded[1:-1, 1:-1]
        & padded[0:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, 0:-2]
        & padded[1:-1, 2:]
    )
    return mask & ~interior


SCALE = 3
H, W = mask.shape

mask_contour = make_mask_contour(mask)
b_conserved_contour = make_contour_map(b_lab, b_conserved_ids)
b_lost_contour = make_contour_map(b_lab, b_lost_ids)
d_new_contour = make_contour_map(d_lab, d_new_ids)


def overlay_contour(arr_rgb, contour, color, scale):
    img = Image.fromarray(arr_rgb).resize((W * scale, H * scale), Image.NEAREST)
    pix = np.array(img)
    ys, xs = np.where(contour)
    for y, x in zip(ys, xs):
        for dy in range(scale):
            for dx in range(scale):
                ry, rx = y * scale + dy, x * scale + dx
                if 0 <= ry < pix.shape[0] and 0 <= rx < pix.shape[1]:
                    pix[ry, rx] = color
    return Image.fromarray(pix)


def load_crop_rgb(path):
    img = Image.open(path).convert("RGB")
    arr = np.array(img)
    return arr[FENETRE["row0"]:FENETRE["row1"], FENETRE["col0"]:FENETRE["col1"]]


b_rgb = load_crop_rgb(paths["B_med1-1_t01"])
d_rgb = load_crop_rgb(paths["D_med3-5_t01"])

b_img = Image.fromarray(b_rgb).resize((W * SCALE, H * SCALE), Image.NEAREST)
d_img = Image.fromarray(d_rgb).resize((W * SCALE, H * SCALE), Image.NEAREST)

b_pix = np.array(b_img)
d_pix = np.array(d_img)

for y, x in zip(*np.where(mask_contour)):
    for dy in range(SCALE):
        for dx in range(SCALE):
            b_pix[y * SCALE + dy, x * SCALE + dx] = (255, 0, 0)
            d_pix[y * SCALE + dy, x * SCALE + dx] = (255, 0, 0)

for y, x in zip(*np.where(b_conserved_contour)):
    for dy in range(SCALE):
        for dx in range(SCALE):
            b_pix[y * SCALE + dy, x * SCALE + dx] = (0, 200, 0)

for y, x in zip(*np.where(b_lost_contour)):
    for dy in range(SCALE):
        for dx in range(SCALE):
            b_pix[y * SCALE + dy, x * SCALE + dx] = (220, 100, 0)

for y, x in zip(*np.where(d_new_contour)):
    for dy in range(SCALE):
        for dx in range(SCALE):
            d_pix[y * SCALE + dy, x * SCALE + dx] = (0, 180, 220)

b_img = Image.fromarray(b_pix)
d_img = Image.fromarray(d_pix)

try:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    font_sm = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
except Exception:
    font = font_sm = ImageFont.load_default()

WW, HH = W * SCALE, H * SCALE
MARGIN = 4
LABEL_H = 28
LEG_H = 22
TOTAL_W = WW * 2 + MARGIN * 3
TOTAL_H = HH + LABEL_H + MARGIN * 2 + LEG_H

out = Image.new("RGB", (TOTAL_W, TOTAL_H), (210, 210, 210))
out.paste(b_img, (MARGIN, LABEL_H + MARGIN))
out.paste(d_img, (WW + MARGIN * 2, LABEL_H + MARGIN))

draw = ImageDraw.Draw(out)
draw.text((MARGIN + 4, 7), "B  med1/1  thresold=0.1", fill=(0, 0, 0), font=font)
draw.text((WW + MARGIN * 2 + 4, 7), "D  med3/5  thresold=0.1", fill=(0, 0, 0), font=font)

ly = LABEL_H + MARGIN + HH + 4
draw.rectangle([MARGIN, ly + 3, MARGIN + 14, ly + 13], fill=(180, 180, 180), outline=(255, 0, 0))
draw.text((MARGIN + 18, ly + 1), "contour bois", fill=(200, 0, 0), font=font_sm)

draw.rectangle([120, ly + 3, 134, ly + 13], fill=(180, 180, 180), outline=(0, 200, 0))
draw.text((138, ly + 1), f"conservee ({len(b_conserved_ids)})", fill=(0, 140, 0), font=font_sm)

draw.rectangle([300, ly + 3, 314, ly + 13], fill=(180, 180, 180), outline=(220, 100, 0))
draw.text((318, ly + 1), f"perdue ({len(b_lost_ids)})", fill=(180, 70, 0), font=font_sm)

draw.rectangle([WW + MARGIN * 2 + 4, ly + 3, WW + MARGIN * 2 + 18, ly + 13], fill=(180, 180, 180), outline=(0, 180, 220))
draw.text((WW + MARGIN * 2 + 22, ly + 1), f"nouveau ({len(d_new_ids)})", fill=(0, 130, 180), font=font_sm)

bar_px = 50 * SCALE
bx0, by0 = MARGIN + 8, LABEL_H + MARGIN + HH - 22
draw.rectangle([bx0, by0, bx0 + bar_px, by0 + 7], fill=(0, 0, 0))
draw.text((bx0, by0 - 15), "50 m", fill=(0, 0, 0), font=font_sm)

out.save("docs/images/bois_dupont_BD_zoom.png", optimize=True)
print(f"Saved docs/images/bois_dupont_BD_zoom.png  {TOTAL_W}x{TOTAL_H}")
