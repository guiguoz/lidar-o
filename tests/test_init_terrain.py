"""Tests pour src/init_terrain.py, src/providers/france.py et src/check_terrain.py."""
import math
import pathlib

import pytest
import yaml

from src.init_terrain import (
    bbox_from_center,
    compute_convergence,
    deduce_crs,
    projected_to_wgs84,
    update_config_yaml,
    wgs84_to_projected,
    write_georef_xml,
)
from src.providers.france import list_tiles
from src.check_terrain import _coverage_pct, _ign_tile_extent, _tiles_union, cmd_check


# ── Convergence des méridiens ─────────────────────────────────────────────────

class TestConvergence:
    def test_grimbosq(self):
        # Grimbosq — ref_point (450000, 6888000) en EPSG:2154 (Lambert-93, conique)
        # Convergence exacte via get_factors() ≈ -2.48° (formule approchée sin(lat) donnait -2.58°)
        lat, lon = projected_to_wgs84(450000, 6888000, 2154)
        conv = compute_convergence(lat, lon, 2154)
        assert abs(conv - (-2.48)) < 0.05, f"Grimbosq : {conv:.3f}° attendu ≈ -2.48°"

    def test_kilemaed(self):
        # Kilemäed — ref_point (413000, 6483000) en EPSG:3301 (L-EST97, conique)
        # Convergence exacte via get_factors() ≈ -1.27°
        lat, lon = projected_to_wgs84(413000, 6483000, 3301)
        conv = compute_convergence(lat, lon, 3301)
        assert abs(conv - (-1.27)) < 0.05, f"Kilemäed : {conv:.3f}° attendu ≈ -1.27°"

    def test_east_of_central_meridian_is_positive(self):
        # Un point à l'est du méridien central doit avoir une convergence positive
        # France, est de Paris (lon = 6°, λ₀ = 3°)
        conv = compute_convergence(lat=48.0, lon=6.0, epsg=2154)
        assert conv > 0, f"Est du CM → convergence positive, obtenu {conv:.3f}"

    def test_west_of_central_meridian_is_negative(self):
        conv = compute_convergence(lat=48.0, lon=0.0, epsg=2154)
        assert conv < 0

    def test_on_central_meridian_is_zero(self):
        conv = compute_convergence(lat=48.0, lon=3.0, epsg=2154)
        assert abs(conv) < 1e-6


# ── Déduction de CRS ──────────────────────────────────────────────────────────

class TestDeduceCRS:
    def test_france(self):
        epsg, _ = deduce_crs(lat=49.043, lon=-0.421)
        assert epsg == 2154

    def test_estonia(self):
        epsg, _ = deduce_crs(lat=58.48, lon=22.51)
        assert epsg == 3301

    def test_switzerland(self):
        epsg, _ = deduce_crs(lat=46.9, lon=7.4)
        assert epsg == 2056

    def test_gb(self):
        epsg, _ = deduce_crs(lat=51.5, lon=-0.1)
        assert epsg == 27700

    def test_finland(self):
        epsg, _ = deduce_crs(lat=61.0, lon=25.0)
        assert epsg == 3067

    def test_utm_fallback_north(self):
        # Japon — hors table → UTM zone 54N
        epsg, name = deduce_crs(lat=35.0, lon=136.0)
        # zone = floor((136 + 180) / 6) + 1 = floor(316/6) + 1 = 52 + 1 = 53 + 1? Let me compute
        # (136 + 180) / 6 = 316/6 = 52.67 → floor = 52, zone = 53
        # No: int(52.67) + 1 = 52 + 1 = 53
        assert epsg == 32653
        assert "UTM" in name

    def test_utm_fallback_south(self):
        epsg, name = deduce_crs(lat=-33.9, lon=18.4)
        # South Africa, Cape Town: zone = int((18.4+180)/6)+1 = int(33.07)+1 = 33+1=34
        assert epsg == 32734
        assert "S" in name


# ── Nommage des tuiles IGN ────────────────────────────────────────────────────

class TestIGNTiles:
    def test_grimbosq_6_tiles(self):
        bbox = (448000, 6886000, 450001, 6889001)
        tiles = list_tiles(bbox, "EPSG:2154")
        assert len(tiles) == 6, f"Attendu 6 tuiles, obtenu {len(tiles)}: {tiles}"
        names = {t.split("_")[2] + "/" + t.split("_")[3] for t in tiles}
        assert "0448/6887" in names
        assert "0449/6889" in names

    def test_grimbosq_x_tiles_are_448_and_449_only(self):
        bbox = (448000, 6886000, 450001, 6889001)
        tiles = list_tiles(bbox, "EPSG:2154")
        x_vals = {t.split("_")[2] for t in tiles}
        assert x_vals == {"0448", "0449"}, f"x attendus {{0448, 0449}}, obtenu {x_vals}"

    def test_grimbosq_y_tiles_are_6887_6888_6889(self):
        bbox = (448000, 6886000, 450001, 6889001)
        tiles = list_tiles(bbox, "EPSG:2154")
        y_vals = {t.split("_")[3] for t in tiles}
        assert y_vals == {"6887", "6888", "6889"}

    def test_port_en_bessin_3x2(self):
        # bbox Port-en-Bessin : 3×2 km
        bbox = (424000, 6920000, 427000, 6922000)
        tiles = list_tiles(bbox, "EPSG:2154")
        x_vals = {t.split("_")[2] for t in tiles}
        y_vals = {t.split("_")[3] for t in tiles}
        assert x_vals == {"0424", "0425", "0426"}
        assert y_vals == {"6921", "6922"}

    def test_tile_filename_format(self):
        bbox = (448000, 6886000, 449000, 6887000)
        tiles = list_tiles(bbox, "EPSG:2154")
        assert tiles == ["LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz"]

    def test_non_france_crs_returns_empty(self):
        bbox = (411888, 6481712, 414255, 6484028)
        assert list_tiles(bbox, "EPSG:3301") == []

    def test_sorted_output(self):
        bbox = (448000, 6886000, 450001, 6889001)
        tiles = list_tiles(bbox, "EPSG:2154")
        assert tiles == sorted(tiles)


# ── bbox_from_center (round-trip) ─────────────────────────────────────────────

class TestBboxFromCenter:
    def test_roundtrip_france(self):
        lat, lon = 49.043, -0.421
        bbox = bbox_from_center(lat, lon, 2000, 2154)
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        lat2, lon2 = projected_to_wgs84(cx, cy, 2154)
        # Round-trip à ±5 m (acceptable pour une bbox 2 km)
        dx, dy = wgs84_to_projected(lat2, lon2, 2154)
        dx_orig, dy_orig = wgs84_to_projected(lat, lon, 2154)
        assert abs(dx - dx_orig) < 5, f"x décalé de {abs(dx-dx_orig):.1f} m"
        assert abs(dy - dy_orig) < 5, f"y décalé de {abs(dy-dy_orig):.1f} m"

    def test_size_correct(self):
        bbox = bbox_from_center(49.0, 3.0, 2000, 2154)
        assert abs((bbox[2] - bbox[0]) - 2000) <= 1
        assert abs((bbox[3] - bbox[1]) - 2000) <= 1


# ── write_georef_xml ──────────────────────────────────────────────────────────

class TestWriteGeorefXML:
    def test_creates_valid_file(self, tmp_path):
        bbox = (448000, 6886000, 450000, 6889000)
        path = write_georef_xml("test", bbox, 2154, tmp_path)
        assert path.exists()
        text = path.read_text()
        assert "<georeferencing" in text
        assert "<ref_point x=" in text

    def test_reloadable_by_load_georef(self, tmp_path):
        from src.omap_writer import load_georef
        bbox = (448000, 6886000, 450000, 6889000)
        path = write_georef_xml("test", bbox, 2154, tmp_path)
        geo = load_georef(path)
        assert geo.scale == 10000
        assert geo.ref_x == 449000  # centre arrondi au millier
        assert geo.ref_y == 6888000

    def test_declination_is_convergence_not_magnetic(self, tmp_path):
        bbox = (448000, 6886000, 450000, 6889000)
        write_georef_xml("test", bbox, 2154, tmp_path)
        text = (tmp_path / "georef_test.xml").read_text()
        # Should have negative declination for west-France point
        import re
        m = re.search(r'declination="([^"]+)"', text)
        assert m is not None
        val = float(m.group(1))
        assert val < 0, f"Point ouest de France → convergence négative, obtenu {val}"


# ── update_config_yaml ────────────────────────────────────────────────────────

class TestUpdateConfigYaml:
    def _base_config(self, tmp_path: pathlib.Path) -> pathlib.Path:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("terrains:\n  grimbosq:\n    bbox: [1,2,3,4]\n    crs: EPSG:2154\n")
        return cfg

    def test_adds_new_terrain(self, tmp_path):
        cfg = self._base_config(tmp_path)
        update_config_yaml("my_forest", (448000, 6886000, 450000, 6889000), 2154, cfg)
        loaded = yaml.safe_load(cfg.read_text())
        assert "my_forest" in loaded["terrains"]
        assert loaded["terrains"]["my_forest"]["crs"] == "EPSG:2154"

    def test_refuses_existing_without_force(self, tmp_path):
        cfg = self._base_config(tmp_path)
        with pytest.raises(ValueError, match="existe déjà"):
            update_config_yaml("grimbosq", (1, 2, 3, 4), 2154, cfg)

    def test_force_overwrites_existing(self, tmp_path):
        cfg = self._base_config(tmp_path)
        new_bbox = (9000, 9000, 9999, 9999)
        update_config_yaml("grimbosq", new_bbox, 2154, cfg, force=True)
        loaded = yaml.safe_load(cfg.read_text())
        assert loaded["terrains"]["grimbosq"]["bbox"] == list(new_bbox)

    def test_preserves_existing_comments(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("# mon commentaire\nterrains:\n  grimbosq:\n    bbox: [1,2,3,4]\n")
        update_config_yaml("new_t", (1, 2, 3, 4), 2154, cfg)
        assert "# mon commentaire" in cfg.read_text()


# ── Coverage check ────────────────────────────────────────────────────────────

class TestCoverageCheck:
    def test_full_coverage(self):
        bbox = (448000, 6886000, 450000, 6889000)
        tiles_ext = (448000, 6886000, 450000, 6889000)
        assert _coverage_pct(bbox, tiles_ext) == pytest.approx(100.0)

    def test_zero_coverage(self):
        bbox = (448000, 6886000, 450000, 6889000)
        tiles_ext = (460000, 6900000, 462000, 6902000)
        assert _coverage_pct(bbox, tiles_ext) == pytest.approx(0.0)

    def test_50_percent_coverage(self):
        bbox = (424000, 6920000, 427000, 6922000)  # 3×2 km = 6 km²
        # Tiles shifted 1 km north (Port-en-Bessin bug scenario)
        tiles_ext = (424000, 6921000, 427000, 6923000)  # couvre y 6921–6923
        cov = _coverage_pct(bbox, tiles_ext)
        # Intersection: x=424–427, y=6921–6922 → 3×1 km = 3 km²
        # Coverage = 3/6 = 50 %
        assert cov == pytest.approx(50.0)

    def test_ign_tile_extent_parsing(self):
        ext = _ign_tile_extent("LHD_FXX_0448_6887_PTS_LAMB93_IGN69.copc.laz")
        assert ext == (448000, 6886000, 449000, 6887000)

    def test_ign_tile_extent_non_ign(self):
        assert _ign_tile_extent("myfile.laz") is None

    def test_tiles_union(self):
        extents = [
            (448000, 6886000, 449000, 6887000),
            (449000, 6886000, 450000, 6887000),
        ]
        union = _tiles_union(extents)
        assert union == (448000, 6886000, 450000, 6887000)


# ── cmd_check (integration) ───────────────────────────────────────────────────

class TestCmdCheck:
    def _make_cfg(self, bbox=(424000, 6920000, 427000, 6922000), crs="EPSG:2154"):
        return {"terrains": {"test_t": {"bbox": list(bbox), "crs": crs}}}

    def test_skip_check_always_ok(self, tmp_path):
        cfg = self._make_cfg()
        result = cmd_check("test_t", cfg, tmp_path, skip_check=True)
        assert result is True

    def test_fails_no_tiles(self, tmp_path):
        (tmp_path / "LIDAR").mkdir()
        cfg = self._make_cfg()
        result = cmd_check("test_t", cfg, tmp_path)
        assert result is False

    def test_fails_missing_georef(self, tmp_path):
        lidar = tmp_path / "LIDAR"
        lidar.mkdir()
        # Tile that covers bbox fully
        (lidar / "LHD_FXX_0424_6921_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0424_6922_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0425_6921_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0425_6922_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0426_6921_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0426_6922_PTS_LAMB93_IGN69.copc.laz").write_text("")
        cfg = self._make_cfg()
        # No georef XML → should fail
        result = cmd_check("test_t", cfg, tmp_path)
        assert result is False

    def test_fails_low_coverage(self, tmp_path):
        lidar = tmp_path / "LIDAR"
        lidar.mkdir()
        assets = tmp_path / "assets"
        assets.mkdir()
        # Write valid georef XML
        (assets / "georef_test_t.xml").write_text(
            '<georeferencing scale="10000" auxiliary_scale_factor="1.0" declination="0.0">'
            '<projected_crs id="EPSG"><spec language="PROJ.4">+init=epsg:2154</spec>'
            '<parameter>2154</parameter><ref_point x="425000" y="6921000"/></projected_crs>'
            '<geographic_crs id="Geographic coordinates">'
            '<spec language="PROJ.4">+proj=latlong +datum=WGS84</spec>'
            '<ref_point_deg lat="49.0" lon="-0.5"/></geographic_crs></georeferencing>'
        )
        # Tile shifted 1 km north (Port-en-Bessin bug): covers y 6922-6924, not 6920-6922
        (lidar / "LHD_FXX_0424_6923_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0425_6923_PTS_LAMB93_IGN69.copc.laz").write_text("")
        (lidar / "LHD_FXX_0426_6923_PTS_LAMB93_IGN69.copc.laz").write_text("")
        cfg = self._make_cfg()
        result = cmd_check("test_t", cfg, tmp_path)
        # 0% overlap → error
        assert result is False

    def test_passes_with_correct_tiles_and_georef(self, tmp_path):
        from src.init_terrain import write_georef_xml

        lidar = tmp_path / "LIDAR"
        lidar.mkdir()
        assets = tmp_path / "assets"
        assets.mkdir()

        bbox = (424000, 6920000, 427000, 6922000)
        write_georef_xml("test_t", bbox, 2154, assets)

        for tile in ["LHD_FXX_0424_6921_PTS_LAMB93_IGN69.copc.laz",
                     "LHD_FXX_0424_6922_PTS_LAMB93_IGN69.copc.laz",
                     "LHD_FXX_0425_6921_PTS_LAMB93_IGN69.copc.laz",
                     "LHD_FXX_0425_6922_PTS_LAMB93_IGN69.copc.laz",
                     "LHD_FXX_0426_6921_PTS_LAMB93_IGN69.copc.laz",
                     "LHD_FXX_0426_6922_PTS_LAMB93_IGN69.copc.laz"]:
            (lidar / tile).write_text("")

        cfg = self._make_cfg(bbox=bbox)
        result = cmd_check("test_t", cfg, tmp_path)
        assert result is True
