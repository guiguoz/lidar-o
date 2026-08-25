"""Render grimbosq.omap to a PNG suitable for the README."""
import xml.etree.ElementTree as ET
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection, LineCollection
import sys

NS = 'http://openorienteering.org/apps/mapper/xml/v2'

def t(name):
    return f'{{{NS}}}{name}'

# ISOM color palette (approximate RGB)
SYMBOL_STYLE = {
    # vegetation
    '406': dict(type='area', fc='#d8f5b4', ec='none', zorder=2),
    '408': dict(type='area', fc='#a4d982', ec='none', zorder=3),
    '410': dict(type='area', fc='#3dab3d', ec='none', zorder=4),
    '401': dict(type='area', fc='#ffffff', ec='none', zorder=1),
    '403': dict(type='area', fc='#e8facc', ec='none', zorder=2),
    # water
    '301.1': dict(type='area', fc='#aad3df', ec='none', zorder=2),
    '304': dict(type='line', color='#aad3df', lw=1.5, zorder=5),
    '310': dict(type='area', fc='#aad3df', ec='none', zorder=2),
    # man-made
    '502': dict(type='line', color='#d4a017', lw=2.5, zorder=6),
    '503': dict(type='line', color='#c8a260', lw=1.8, zorder=6),
    '505': dict(type='line', color='#c8a260', lw=0.8, zorder=6),
    '515': dict(type='line', color='#333333', lw=2.0, zorder=7),
    '516': dict(type='line', color='#333333', lw=0.8, zorder=5),
    '521': dict(type='area', fc='#999999', ec='#222222', lw=0.5, zorder=8),
    # relief (contours)
    '301': dict(type='line', color='#c87137', lw=0.5, zorder=5),
    '302': dict(type='line', color='#c87137', lw=1.0, zorder=5),
    '303': dict(type='line', color='#c87137', lw=0.5, ls='--', zorder=5),
}

def parse_coords(coords_el):
    """Return list of (x, y) from <coords><coord x=... y=.../>...</coords>."""
    pts = []
    for c in coords_el.findall(t('coord')):
        x = int(c.get('x', 0)) / 1000.0  # omap uses mm*1000 in map units
        y = int(c.get('y', 0)) / 1000.0
        pts.append((x, y))
    return pts

def main():
    omap_path = 'e:/Vikazim/Ovector/output/grimbosq.omap'
    out_path = 'e:/Vikazim/Ovector/docs/images/extrait_grimbosq.png'

    tree = ET.parse(omap_path)
    root = tree.getroot()
    barrier = root.find(t('barrier'))

    # Build symbol index: position -> code
    symbols_el = barrier.find(t('symbols'))
    sym_codes = {}  # index -> code string
    for i, sym in enumerate(symbols_el.findall(t('symbol'))):
        code = sym.get('code', '')
        sym_codes[i] = code

    print(f"Loaded {len(sym_codes)} symbols")

    # Collect all objects grouped by draw order
    parts_el = barrier.find(t('parts'))

    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    ax.set_aspect('equal')
    ax.set_facecolor('#f5f0e8')  # fond beige clair (terrain CO)
    ax.axis('off')

    areas = []   # (style, polygon_pts)
    lines = []   # (style, pts_list)

    for part in parts_el.findall(t('part')):
        for obj in part.findall(t('object')):
            sym_idx = int(obj.get('symbol', -1))
            if sym_idx < 0 or sym_idx not in sym_codes:
                continue
            code = sym_codes[sym_idx]
            style = SYMBOL_STYLE.get(code)
            if style is None:
                continue

            coords_el = obj.find(t('coords'))
            if coords_el is None:
                continue
            pts = parse_coords(coords_el)
            if len(pts) < 2:
                continue

            if style['type'] == 'area' and len(pts) >= 3:
                areas.append((style, pts))
            elif style['type'] == 'line':
                lines.append((style, pts))

    # Draw areas (sorted by zorder)
    areas.sort(key=lambda x: x[0].get('zorder', 1))
    for style, pts in areas:
        arr = np.array(pts)
        # Flip y (omap y increases downward, matplotlib upward)
        arr[:, 1] = -arr[:, 1]
        poly = MplPolygon(arr, closed=True,
                          facecolor=style.get('fc', 'none'),
                          edgecolor=style.get('ec', 'none'),
                          linewidth=style.get('lw', 0),
                          zorder=style.get('zorder', 1))
        ax.add_patch(poly)

    # Draw lines (sorted by zorder)
    lines.sort(key=lambda x: x[0].get('zorder', 5))
    for style, pts in lines:
        arr = np.array(pts)
        arr[:, 1] = -arr[:, 1]
        ax.plot(arr[:, 0], arr[:, 1],
                color=style.get('color', '#333333'),
                linewidth=style.get('lw', 1.0),
                linestyle=style.get('ls', '-'),
                zorder=style.get('zorder', 5),
                solid_capstyle='round')

    ax.autoscale_view()

    # Legend
    legend_elements = [
        mpatches.Patch(facecolor='#d8f5b4', label='406 slow run'),
        mpatches.Patch(facecolor='#a4d982', label='408 walk'),
        mpatches.Patch(facecolor='#3dab3d', label='410 fight'),
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=9,
              framealpha=0.85, edgecolor='#cccccc')

    plt.tight_layout(pad=0)
    plt.savefig(out_path, dpi=150, bbox_inches='tight',
                facecolor=fig.get_facecolor())
    print(f"Saved: {out_path}")

if __name__ == '__main__':
    main()
