"""Interface graphique Lidar'O — tkinter. Aucune logique métier ici."""
from __future__ import annotations

import logging
import pathlib
import queue
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import tkinter.scrolledtext as st

import yaml

from gui.worker import Done, PipelineWorker, Progress

log = logging.getLogger(__name__)

_CELL_PX = 48
_COLOR_PRESENT = "#4caf50"
_COLOR_MISSING = "#f44336"
_COLOR_UNKNOWN = "#9e9e9e"
_COLOR_BG = "#fafafa"


class LidarOApp:
    """Interface principale Lidar'O."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Lidar'O")
        self.root.configure(bg=_COLOR_BG)

        self._cfg: dict = {}
        self._terrain_var = tk.StringVar()
        self._lidar_dir: pathlib.Path | None = None
        self._bdtopo_path: pathlib.Path | None = None
        self._kp_binary: pathlib.Path | None = None
        self._tiles: list[pathlib.Path] = []
        self._tile_extents: dict[pathlib.Path, tuple | None] = {}
        self._worker: PipelineWorker | None = None
        self._queue: queue.Queue = queue.Queue()

        self._build_ui()
        self._load_config()
        self._check_kp()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg=_COLOR_BG, padx=8, pady=8)
        top.pack(fill=tk.X)

        tk.Label(top, text="Terrain :", bg=_COLOR_BG).pack(side=tk.LEFT)
        self._terrain_entry = tk.Entry(top, textvariable=self._terrain_var, width=20)
        self._terrain_entry.pack(side=tk.LEFT, padx=4)

        tk.Button(top, text="Charger LiDAR…", command=self._load_lidar).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Charger BD TOPO…", command=self._load_bdtopo).pack(side=tk.LEFT, padx=4)

        mid = tk.Frame(self.root, bg=_COLOR_BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)

        canvas_frame = tk.LabelFrame(mid, text="Dalles LiDAR", bg=_COLOR_BG)
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas = tk.Canvas(canvas_frame, width=300, height=200, bg="#eeeeee")
        self._canvas.pack(fill=tk.BOTH, expand=True)

        right = tk.Frame(mid, bg=_COLOR_BG, padx=8)
        right.pack(side=tk.LEFT, fill=tk.Y)

        tk.Label(right, text="État BD TOPO :", bg=_COLOR_BG).pack(anchor=tk.W)
        self._bdtopo_label = tk.Label(right, text="— non chargée", bg=_COLOR_BG, fg="#888")
        self._bdtopo_label.pack(anchor=tk.W)

        tk.Label(right, text="Karttapullautin :", bg=_COLOR_BG).pack(anchor=tk.W, pady=(8, 0))
        self._kp_label = tk.Label(right, text="recherche…", bg=_COLOR_BG, fg="#888")
        self._kp_label.pack(anchor=tk.W)

        bottom = tk.Frame(self.root, bg=_COLOR_BG, padx=8, pady=4)
        bottom.pack(fill=tk.X)

        self._run_btn = tk.Button(
            bottom, text="Générer la carte",
            command=self._run_pipeline,
            state=tk.DISABLED,
            bg="#1976d2", fg="white",
        )
        self._run_btn.pack(side=tk.LEFT)

        self._cancel_btn = tk.Button(
            bottom, text="Annuler",
            command=self._cancel_pipeline,
            state=tk.DISABLED,
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=4)

        self._status_label = tk.Label(bottom, text="", bg=_COLOR_BG)
        self._status_label.pack(side=tk.LEFT, padx=8)

        log_frame = tk.LabelFrame(self.root, text="Journal", bg=_COLOR_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._log_text = st.ScrolledText(log_frame, height=10, state=tk.DISABLED, font=("Courier", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)

    def _load_config(self) -> None:
        config_path = pathlib.Path("config.yaml")
        if config_path.exists():
            self._cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        else:
            self._cfg = {}

    def _log(self, msg: str) -> None:
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, msg + "\n")
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _load_lidar(self) -> None:
        directory = fd.askdirectory(title="Sélectionner le répertoire LiDAR")
        if not directory:
            return
        lidar_dir = pathlib.Path(directory)
        tiles = list(lidar_dir.glob("*.copc.laz")) + list(lidar_dir.glob("*.laz"))
        if not tiles:
            mb.showwarning("LiDAR", f"Aucun fichier .laz dans {lidar_dir}")
            return

        self._lidar_dir = lidar_dir
        self._tiles = sorted(tiles)
        self._log(f"LiDAR : {len(tiles)} fichier(s) chargé(s) depuis {lidar_dir}")

        try:
            from src.check_terrain import _tile_extent
            self._tile_extents = {f: _tile_extent(f) for f in self._tiles}
        except Exception as exc:
            log.warning("Extents non calculés : %s", exc)
            self._tile_extents = {f: None for f in self._tiles}

        self._draw_grid()
        self._refresh_run_button()

    def _draw_grid(self) -> None:
        """Dessine la grille des dalles sur le canvas."""
        self._canvas.delete("all")
        if not self._tiles:
            return

        try:
            from src.check_terrain import _ign_tile_extent, _IGN_RE
        except ImportError:
            return

        ign_map: dict[tuple[int, int], bool] = {}
        for f in self._tiles:
            m = _IGN_RE.search(f.name)
            if m:
                ign_map[(int(m.group(1)), int(m.group(2)))] = True

        if not ign_map:
            self._canvas.create_text(
                150, 100, text=f"{len(self._tiles)} dalles\n(nommage non IGN)",
                justify=tk.CENTER,
            )
            return

        xs = sorted({k[0] for k in ign_map})
        ys = sorted({k[1] for k in ign_map}, reverse=True)

        cw = self._canvas.winfo_reqwidth()
        ch = self._canvas.winfo_reqheight()
        cell_w = min(_CELL_PX, (cw - 4) // max(len(xs), 1))
        cell_h = min(_CELL_PX, (ch - 4) // max(len(ys), 1))

        for ci, x in enumerate(xs):
            for ri, y in enumerate(ys):
                color = _COLOR_PRESENT if (x, y) in ign_map else _COLOR_MISSING
                x0 = 2 + ci * cell_w
                y0 = 2 + ri * cell_h
                self._canvas.create_rectangle(x0, y0, x0 + cell_w - 2, y0 + cell_h - 2, fill=color, outline="")

    def _load_bdtopo(self) -> None:
        path = fd.askopenfilename(
            title="Sélectionner le fichier BD TOPO",
            filetypes=[("GeoPackage", "*.gpkg"), ("Archive 7z", "*.7z"), ("Tous", "*.*")],
        )
        if not path:
            return
        bdtopo_path = pathlib.Path(path)

        if bdtopo_path.suffix == ".7z":
            self._log(f"BD TOPO : archive 7z détectée — extraction non prise en charge depuis l'UI")
            self._log(f"  Utiliser : python main.py setup <terrain>")
            return

        if not bdtopo_path.exists():
            mb.showerror("BD TOPO", f"Fichier introuvable : {bdtopo_path}")
            return

        self._bdtopo_path = bdtopo_path
        self._log(f"BD TOPO : {bdtopo_path.name}")

        try:
            import fiona
            layers = fiona.listlayers(str(bdtopo_path))
            self._bdtopo_label.config(text=f"✓ {bdtopo_path.name}", fg="#4caf50")
            self._log(f"  {len(layers)} couche(s) disponible(s)")
        except ImportError:
            self._bdtopo_label.config(text=f"✓ {bdtopo_path.name} (non validé)", fg="#ff9800")
        except Exception as exc:
            self._bdtopo_label.config(text=f"⚠ erreur lecture", fg="#f44336")
            self._log(f"  Erreur : {exc}")

        self._refresh_run_button()

    def _check_kp(self) -> None:
        try:
            from src.kp_install import KP_PINNED_VERSION, locate_binary, read_binary_version
            binary = locate_binary(self._cfg)
            if binary is None:
                self._kp_label.config(text="✗ absent", fg="#f44336")
                return
            version = read_binary_version(binary)
            if version == KP_PINNED_VERSION:
                self._kp_label.config(text=f"✓ v{version}", fg="#4caf50")
            else:
                self._kp_label.config(text=f"⚠ v{version} (attendu v{KP_PINNED_VERSION})", fg="#ff9800")
            self._kp_binary = binary
        except Exception as exc:
            self._kp_label.config(text=f"⚠ erreur : {exc}", fg="#f44336")

    def _refresh_run_button(self) -> None:
        ready = bool(self._lidar_dir and self._tiles)
        self._run_btn.config(state=tk.NORMAL if ready else tk.DISABLED)

    def _ensure_terrain_in_config(self, terrain: str) -> bool:
        """Crée le terrain dans config.yaml depuis les dalles si absent. Retourne False si échec."""
        if (self._cfg.get("terrains") or {}).get(terrain):
            return True

        if not self._tiles:
            mb.showerror("Terrain", "Charger des dalles LiDAR avant de lancer.")
            return False

        try:
            from src.check_terrain import _ign_tile_extent, _tile_extent, _tiles_union
            extents = [_ign_tile_extent(f.name) or _tile_extent(f) for f in self._tiles]
            valid = [e for e in extents if e]
            if not valid:
                mb.showerror(
                    "Terrain",
                    "Impossible de déduire l'emprise depuis les dalles.\n"
                    "Utiliser : python main.py init " + terrain + " --center lat lon",
                )
                return False

            bbox = _tiles_union(valid)
            ign_names = [f for f in self._tiles if _ign_tile_extent(f.name)]
            epsg = 2154 if ign_names else 4326

            config_path = pathlib.Path("config.yaml")
            assets_dir = pathlib.Path("assets")

            from src.init_terrain import patch_terrain_yaml, update_config_yaml, write_georef_xml
            update_config_yaml(terrain, bbox, epsg, config_path)
            write_georef_xml(terrain, bbox, epsg, assets_dir)

            fields: dict[str, str] = {}
            if self._lidar_dir:
                fields["lidar_dir"] = str(self._lidar_dir).replace("\\", "/")
            if self._bdtopo_path:
                fields["bdtopo_path"] = str(self._bdtopo_path).replace("\\", "/")
            if self._kp_binary:
                fields["kp_binary"] = str(self._kp_binary).replace("\\", "/")
            if fields:
                patch_terrain_yaml(terrain, fields, config_path)

            self._load_config()
            self._log(
                f"Terrain '{terrain}' créé : bbox {[int(v) for v in bbox]}  CRS EPSG:{epsg}"
            )
            return True

        except Exception as exc:
            mb.showerror("Terrain", f"Création du terrain échouée :\n{exc}")
            return False

    def _run_pipeline(self) -> None:
        terrain = self._terrain_var.get().strip()
        if not terrain:
            mb.showwarning("Terrain", "Saisir un nom de terrain")
            return

        if not self._ensure_terrain_in_config(terrain):
            return

        self._run_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(state=tk.NORMAL)
        self._status_label.config(text="Exécution en cours…")
        self._log(f"=== Lancement pipeline — terrain '{terrain}' ===")

        lidar_dir = self._lidar_dir

        def _run() -> None:
            import sys as _sys
            _sys.argv = ["main.py", terrain, "--tiles-dir", str(lidar_dir)]
            from main import _cmd_run
            _cmd_run()

        self._worker = PipelineWorker(self._queue)
        self._worker.start(_run)
        self.root.after(100, self._update_ui)

    def _cancel_pipeline(self) -> None:
        if self._worker and self._worker.is_running:
            self._worker.cancel()
            self._log("Annulation demandée…")

    def _update_ui(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                if isinstance(msg, Progress):
                    self._status_label.config(
                        text=f"[{msg.step_idx}/{msg.total_steps}] {msg.step}"
                    )
                    self._log(f"  {msg.step} : {msg.message}")
                elif isinstance(msg, Done):
                    if msg.success:
                        self._status_label.config(text="Terminé ✓")
                        self._log("=== Pipeline terminé avec succès ===")
                    else:
                        self._status_label.config(text="Erreur")
                        self._log(f"=== ERREUR : {msg.error} ===")
                    self._run_btn.config(state=tk.NORMAL)
                    self._cancel_btn.config(state=tk.DISABLED)
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._update_ui)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = LidarOApp()
    app.run()


if __name__ == "__main__":
    main()
