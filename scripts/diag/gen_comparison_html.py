"""Génère une page HTML Leaflet comparant veg_406 pour les 4 résolutions Étape A.

Nécessite geopandas (conda base).
Sortie : output/etapeA_comparison.html
"""
from __future__ import annotations
import json
import pathlib
import sys

import geopandas as gpd

RESOLUTIONS = ["1m", "2m", "3m", "4m"]
ROOT = pathlib.Path(".")
OUT_HTML = ROOT / "output" / "etapeA_comparison.html"

COLORS = {"1m": "#e74c3c", "2m": "#f39c12", "3m": "#27ae60", "4m": "#2980b9"}
LABELS = {
    "1m": "1 m — σ=3px, med=9px",
    "2m": "2 m — σ=1.5px, med=5px",
    "3m": "3 m — σ=1px, med=3px",
    "4m": "4 m — σ=0.75px, med=3px",
}

layers_js = []
stats: dict[str, dict] = {}

for res in RESOLUTIONS:
    path = ROOT / f"output_etapeA_{res}" / "veg_406.geojson"
    if not path.exists():
        print(f"[ABSENT] {path}", flush=True)
        continue

    gdf = gpd.read_file(path).to_crs(epsg=4326)
    areas = gdf.geometry.area  # en m² après reprojection — approx
    # Recalculer les aires en EPSG:2154 pour l'affichage
    gdf_2154 = gpd.read_file(path)
    areas_m2 = gdf_2154.geometry.area

    stats[res] = {
        "count": len(gdf),
        "min_m2": float(areas_m2.min()),
        "p10_m2": float(areas_m2.quantile(0.10)),
        "median_m2": float(areas_m2.quantile(0.50)),
        "total_ha": float(areas_m2.sum() / 1e4),
    }

    geojson_str = gdf.to_json()
    color = COLORS[res]
    label = LABELS[res]

    js = f"""
    var layer_{res} = L.geoJSON({geojson_str}, {{
        style: function(f) {{
            return {{
                color: '{color}',
                weight: 1.2,
                opacity: 0.9,
                fillColor: '{color}',
                fillOpacity: 0.35
            }};
        }},
        onEachFeature: function(f, l) {{
            var a = f.properties.area_m2 ? f.properties.area_m2.toFixed(0) : '?';
            l.bindPopup('<b>Classe 406 — {res}</b><br>Area: ' + a + ' m²');
        }}
    }});
    layers['{res}'] = layer_{res};
    """
    layers_js.append(js)
    print(f"  {res}: {len(gdf)} polygones reprojetés", flush=True)

stats_rows = ""
for res in RESOLUTIONS:
    if res not in stats:
        continue
    s = stats[res]
    c = COLORS[res]
    stats_rows += f"""
    <tr>
        <td><span style="color:{c};font-weight:bold">{res}</span></td>
        <td>{s['count']}</td>
        <td>{s['min_m2']:.0f}</td>
        <td>{s['p10_m2']:.0f}</td>
        <td>{s['median_m2']:.0f}</td>
        <td>{s['total_ha']:.1f}</td>
    </tr>"""

toggle_btns = ""
for res in RESOLUTIONS:
    if res not in stats:
        continue
    c = COLORS[res]
    toggle_btns += f"""
    <button onclick="toggle('{res}')" id="btn_{res}"
        style="background:{c};color:white;border:none;padding:6px 12px;
               margin:3px;border-radius:4px;cursor:pointer;opacity:1;">{res}</button>"""

html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Étape A — Comparaison veg_406</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body {{ margin:0; font-family:sans-serif; }}
  #map {{ height:75vh; }}
  #panel {{ padding:10px 16px; background:#1a1a2e; color:#eee; }}
  #panel h3 {{ margin:4px 0 8px; font-size:14px; color:#aaa; letter-spacing:.05em; }}
  table {{ border-collapse:collapse; font-size:12px; width:100%; }}
  th,td {{ border:1px solid #444; padding:4px 8px; text-align:right; }}
  th {{ background:#2d2d4e; color:#bbb; text-align:center; }}
  td:first-child {{ text-align:left; }}
  #toggles {{ margin-bottom:8px; }}
</style>
</head>
<body>
<div id="panel">
  <h3>Étape A — veg_406 post-généralisation CO · Grimbosq</h3>
  <div id="toggles">
    {toggle_btns}
    <button onclick="toggleAll()" style="background:#555;color:white;border:none;
      padding:6px 12px;margin:3px;border-radius:4px;cursor:pointer;">Tout</button>
  </div>
  <table>
    <tr><th>Rés</th><th>count</th><th>min m²</th><th>p10 m²</th><th>med m²</th><th>total ha</th></tr>
    {stats_rows}
  </table>
</div>
<div id="map"></div>
<script>
  var map = L.map('map').setView([49.17, -0.37], 13);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '© OpenStreetMap contributors', maxZoom: 19
  }}).addTo(map);

  var layers = {{}};
  var active = {{}};
  {''.join(layers_js)}

  // Activer toutes les couches par défaut
  {chr(10).join(f"  layers['{res}'].addTo(map); active['{res}'] = true;" for res in RESOLUTIONS if res in stats)}

  // Ajuster la vue sur les données
  var allLayers = Object.values(layers);
  if (allLayers.length > 0) {{
    var bounds = allLayers[0].getBounds();
    allLayers.forEach(function(l) {{ bounds.extend(l.getBounds()); }});
    map.fitBounds(bounds, {{padding: [20, 20]}});
  }}

  function toggle(res) {{
    if (active[res]) {{
      map.removeLayer(layers[res]);
      active[res] = false;
      document.getElementById('btn_' + res).style.opacity = '0.35';
    }} else {{
      layers[res].addTo(map);
      active[res] = true;
      document.getElementById('btn_' + res).style.opacity = '1';
    }}
  }}

  function toggleAll() {{
    var anyActive = Object.values(active).some(function(v) {{ return v; }});
    {chr(10).join(f"    if (anyActive) map.removeLayer(layers['{res}']); else layers['{res}'].addTo(map); active['{res}'] = !anyActive;" for res in RESOLUTIONS if res in stats)}
    {chr(10).join(f"    document.getElementById('btn_{res}').style.opacity = anyActive ? '0.35' : '1';" for res in RESOLUTIONS if res in stats)}
  }}
</script>
</body>
</html>"""

OUT_HTML.parent.mkdir(exist_ok=True)
OUT_HTML.write_text(html, encoding="utf-8")
print(f"\nHTML -> {OUT_HTML}")
print(f"Ouvrir : file:///{OUT_HTML.resolve().as_posix()}")
