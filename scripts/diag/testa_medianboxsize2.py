"""TEST A — medianboxsize2 = 5, 10, 16 (batch vegeonly=1).

makevege / makevegenew crashent en mode batch (fichiers intermédiaires par dalle
absents après le batch initial). Approche retenue : batch complet avec vegeonly=1,
qui régénère uniquement les tuiles *_vege.png sans recalculer le relief.

Paramètres fixes :
  medianboxsize=9  (inchangé)
  lightgreentone=160  (remapping dans notre merge)
  opacité template=50 %
  tout le reste inchangé

Usage :
    python scripts/diag/testa_medianboxsize2.py            # 3 tests + contrôle
    python scripts/diag/testa_medianboxsize2.py --ctrl     # contrôle seul
    python scripts/diag/testa_medianboxsize2.py --tests    # tests 5/10/16 seuls
"""
from __future__ import annotations
import argparse, pathlib, re, struct, time, logging
import numpy as np
from PIL import Image
import subprocess

ROOT    = pathlib.Path("e:/Vikazim/Ovector")
KP      = ROOT / "karttapullautin-x86_64-win.tar" / "pullauta.exe"
OUT_KP  = ROOT / "out_kp_grimbosq"
INI     = OUT_KP / "pullauta.ini"
IMGDIR  = ROOT / "docs" / "images"

LIGHTGREENTONE = 160
OPACITY        = 0.5
WIN_M          = 500
SCALE          = 10_000
DPI            = 300

WINDOWS = {
    "fen1_406": (448225, 6887720),
    "fen2_408": (448997, 6887939),
    "fen3_410": (449420, 6887239),
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pgw(p: pathlib.Path) -> tuple[float, float, float]:
    L = p.read_text().strip().splitlines()
    return abs(float(L[0])), float(L[4]), float(L[5])

def _wh(p: pathlib.Path) -> tuple[int, int]:
    with open(p, "rb") as f:
        f.read(16)
        w, h = struct.unpack(">II", f.read(8))
    return w, h

def set_ini_param(key: str, value: str) -> None:
    txt = INI.read_text(encoding="utf-8")
    txt = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", txt, flags=re.MULTILINE)
    INI.write_text(txt, encoding="utf-8")


# ── KP batch vegeonly ─────────────────────────────────────────────────────────

def run_batch_vegeonly() -> bool:
    """Lance KP en mode batch vegeonly=1.

    KP v2.12.1 skip les dalles dont le *.copc.laz.png existe déjà, même en
    vegeonly. Contournement : supprimer ces marqueurs avant le run (KP les
    recrée de toute façon pendant le traitement).

    vegeonly=1 est remis à 0 après le run quelle que soit l'issue.
    """
    markers = sorted(OUT_KP.glob("*.copc.laz.png"))
    for m in markers:
        m.unlink()
    log.info("  %d marqueur(s) .png supprimé(s)", len(markers))

    set_ini_param("vegeonly", "1")
    log.info("  batch vegeonly=1 …")
    t0 = time.time()
    r = subprocess.run([str(KP)], cwd=str(OUT_KP), capture_output=True, text=True)
    elapsed = time.time() - t0
    set_ini_param("vegeonly", "0")
    log.info("  → %.0f s  (rc=%d)", elapsed, r.returncode)

    if r.returncode != 0:
        log.error("STDOUT: %s", r.stdout[-800:])
        log.error("STDERR: %s", r.stderr[-800:])
        return False
    return True


# ── Mosaïque ──────────────────────────────────────────────────────────────────

def merge(lightgreentone: int = 200) -> pathlib.Path | None:
    tiles = sorted(OUT_KP.glob("*_vege.png"))
    if not tiles:
        return None
    info = []
    for t in tiles:
        pgw = t.with_suffix(".pgw")
        if not pgw.exists():
            continue
        res, tlx, tly = _pgw(pgw)
        w, h = _wh(t)
        info.append((t, res, tlx, tly, w, h))
    if not info:
        return None

    res_m = info[0][1]
    xmin  = min(tlx       for _, _, tlx, _,   _, _ in info)
    ymax  = max(tly       for _, _, _,   tly,  _, _ in info)
    xmax  = max(tlx + (w - 1) * res_m for _, _, tlx, _, w, _ in info)
    ymin  = min(tly - (h - 1) * res_m for _, _, _, tly, _, h in info)
    cw = round((xmax - xmin) / res_m) + 1
    ch = round((ymax - ymin) / res_m) + 1

    canvas = Image.new("RGB", (cw, ch), (255, 255, 255))
    for tp, _, tlx, tly, _, _ in info:
        col = round((tlx - xmin) / res_m)
        row = round((ymax - tly) / res_m)
        with Image.open(tp) as img:
            canvas.paste(img.convert("RGB"), (col, row))

    if lightgreentone != 200:
        arr = np.array(canvas, dtype=np.float32)
        is_green = (arr[:,:,1] > arr[:,:,0]) & (arr[:,:,1] > arr[:,:,2]) & (arr[:,:,0] < 248)
        factor = (255 - lightgreentone) / (255 - 200)
        for rgb_ch in (0, 2):   # R et B seulement — G reste à 255
            arr[:,:,rgb_ch] = np.where(
                is_green,
                (255 + (arr[:,:,rgb_ch] - 255) * factor).clip(0, 255),
                arr[:,:,rgb_ch],
            )
        canvas = Image.fromarray(arr.astype(np.uint8))

    out = OUT_KP / "vegetation.png"
    canvas.save(str(out), "PNG")
    (OUT_KP / "vegetation.pgw").write_text(
        f"{res_m}\n0.0\n0.0\n-{res_m}\n{xmin}\n{ymax}\n", encoding="utf-8"
    )
    log.info("  vegetation.png : %d×%d px", cw, ch)
    return out


# ── Fenêtres ──────────────────────────────────────────────────────────────────

def render_windows(label: str) -> None:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    veg  = OUT_KP / "vegetation.png"
    pgwf = OUT_KP / "vegetation.pgw"
    if not veg.exists():
        return
    res_m, tlx, tly = _pgw(pgwf)
    arr = np.array(Image.open(str(veg)).convert("RGB"))
    IMGDIR.mkdir(parents=True, exist_ok=True)
    fig_in = (WIN_M / SCALE * 1000) / 25.4   # 50 mm en pouces

    for wname, (cx, cy) in WINDOWS.items():
        half = WIN_M / 2.0
        col0 = max(0, int((cx - half - tlx) / res_m))
        col1 = min(arr.shape[1], int((cx + half - tlx) / res_m) + 1)
        row0 = max(0, int((tly - (cy + half)) / res_m))
        row1 = min(arr.shape[0], int((tly - (cy - half)) / res_m) + 1)
        crop = arr[row0:row1, col0:col1]
        rxmin = tlx + col0 * res_m
        rxmax = tlx + col1 * res_m
        rymax = tly - row0 * res_m
        rymin = tly - row1 * res_m
        fig, ax = plt.subplots(figsize=(fig_in, fig_in), dpi=DPI)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        ax.set_axis_off()
        ax.imshow(crop, extent=[rxmin, rxmax, rymin, rymax],
                  origin="upper", alpha=OPACITY, interpolation="nearest")
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_aspect("equal")
        out = IMGDIR / f"{wname}_{label}.png"
        fig.savefig(str(out), dpi=DPI, bbox_inches="tight", pad_inches=0)
        plt.close(fig)
        log.info("  %s", out.name)


# ── Vérification modification des tuiles ──────────────────────────────────────

def tiles_mtime_before() -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in sorted(OUT_KP.glob("*_vege.png"))}

def check_tiles_modified(before: dict[str, float]) -> bool:
    after = {str(p): p.stat().st_mtime for p in sorted(OUT_KP.glob("*_vege.png"))}
    changed = [p for p in before if after.get(p, 0) > before[p]]
    if changed:
        log.info("  %d tuile(s) modifiée(s)", len(changed))
        return True
    log.warning("  AUCUNE tuile modifiée — batch n'a pas touché les vege.png")
    return False


# ── Phase de test ─────────────────────────────────────────────────────────────

def run_phase(label: str, mbs2: int, base_ini: str) -> None:
    log.info("\n=== %s (medianboxsize2=%d) ===", label, mbs2)
    set_ini_param("medianboxsize2", str(mbs2))
    before = tiles_mtime_before()
    ok = run_batch_vegeonly()
    if not ok:
        log.error("batch vegeonly échoué — arrêt")
        return
    if not check_tiles_modified(before):
        log.warning("Les tuiles n'ont pas changé — résultats non fiables pour ce test")
    merge(lightgreentone=LIGHTGREENTONE)
    render_windows(label)
    (OUT_KP / f"pullauta_{label}.ini").write_text(
        INI.read_text(encoding="utf-8"), encoding="utf-8"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctrl",  action="store_true", help="test de contrôle seul")
    parser.add_argument("--tests", action="store_true", help="tests 5/10/16 seuls")
    args = parser.parse_args()

    run_ctrl  = args.ctrl  or not (args.ctrl or args.tests)
    run_tests = args.tests or not (args.ctrl or args.tests)

    base_ini = INI.read_text(encoding="utf-8")
    (OUT_KP / "pullauta_baseline.ini").write_text(base_ini, encoding="utf-8")
    log.info("Ini baseline sauvegardé")

    try:
        # ── Test de contrôle : medianboxsize2=16 (fort contraste vs baseline=1)
        if run_ctrl:
            run_phase("ctrl_med9_mbs2_16", mbs2=16, base_ini=base_ini)

        # ── Tests A : medianboxsize2 = 5, 10, 16
        if run_tests:
            for mbs2 in (5, 10, 16):
                run_phase(f"testa_med9_{mbs2}", mbs2=mbs2, base_ini=base_ini)

    finally:
        INI.write_text(base_ini, encoding="utf-8")
        log.info("Ini baseline restauré")


if __name__ == "__main__":
    main()
