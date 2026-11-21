"""Build a small GeoJSON of German federal states (+ Luxembourg) from Natural Earth
(public domain), tagged with the TSO control area that covers most of each state.

TSO control areas do NOT follow state borders exactly (e.g. Hesse, Lower Saxony and
Bavaria are split between TenneT and Amprion). The mapping is a labelled approximation
for display; the load numbers themselves are the TSOs' own control-area totals.
"""

from __future__ import annotations

import json
from pathlib import Path

import shapefile
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

CONTROL_AREA = {
    "DE-BE": "DE_50HZ", "DE-BB": "DE_50HZ", "DE-HH": "DE_50HZ", "DE-MV": "DE_50HZ", "DE-SN": "DE_50HZ",
    "DE-ST": "DE_50HZ", "DE-TH": "DE_50HZ",
    "DE-BY": "DE_TENNET", "DE-HE": "DE_TENNET", "DE-NI": "DE_TENNET", "DE-SH": "DE_TENNET", "DE-HB": "DE_TENNET",
    "DE-NW": "DE_AMPRION", "DE-RP": "DE_AMPRION", "DE-SL": "DE_AMPRION", "LU": "DE_AMPRION",
    "DE-BW": "DE_TRANSNETBW",
}
SPLIT = {"DE-HE", "DE-NI", "DE-BY"}  # materially shared between control areas


def build_geojson(shp_path: Path, out: Path, tolerance: float = 0.01) -> dict:
    r = shapefile.Reader(str(shp_path))
    feats, lux = [], []
    for sr in r.iterShapeRecords():
        rec = sr.record.as_dict()
        if rec["adm0_a3"] == "LUX":
            lux.append(shape(sr.shape.__geo_interface__))
            continue
        if rec["adm0_a3"] != "DEU":
            continue
        code = rec["iso_3166_2"]
        geom = shape(sr.shape.__geo_interface__).simplify(tolerance, preserve_topology=True)
        feats.append({"type": "Feature", "geometry": mapping(geom),
                      "properties": {"code": code, "name": rec["name"], "control_area": CONTROL_AREA[code],
                                     "shared_control_area": code in SPLIT}})
    if lux:
        g = unary_union(lux).simplify(tolerance, preserve_topology=True)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"code": "LU", "name": "Luxembourg", "control_area": CONTROL_AREA["LU"],
                                     "shared_control_area": False}})
    gj = {"type": "FeatureCollection", "features": feats,
          "properties": {"source": "Natural Earth 1:10m admin-1 (public domain)",
                         "note": "Control-area assignment by dominant TSO per state; approximate."}}
    out.parent.mkdir(parents=True, exist_ok=True)

    def _round(o):
        if isinstance(o, float):
            return round(o, 4)
        if isinstance(o, (list, tuple)):
            return [_round(x) for x in o]
        if isinstance(o, dict):
            return {k: _round(v) for k, v in o.items()}
        return o

    out.write_text(json.dumps(_round(gj), separators=(",", ":")))
    return gj
