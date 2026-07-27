"""prepare_local_data.py -- eenmalige prep: Geofabrik .osm.pbf -> parquet.

Zet een lokale OSM-extract (bv. utrecht-latest.osm.pbf) om naar drie parquet-
bestanden + meta.json in de lokale data-map, zodat de webapp-backend het
straatnetwerk en de POI's uit lokale bestanden kan laden i.p.v. Overpass.

Usage:
    python prepare_local_data.py <pbf-pad> [--out-dir DIR]

Output (in out-dir, default %LOCALAPPDATA%/accessx_webapp_cache/local_osm):
    edges.parquet  nodes.parquet  pois.parquet  meta.json

Code and comments are English; user-facing CLI output is Dutch. No extra
dependencies beyond pyosmium / pyarrow / numpy / shapely (already installed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import osmium
import pyarrow as pa
import pyarrow.parquet as pq
import shapely.wkb

# Earth radius used by OSMnx (distance.great_circle) -- keep length parity.
EARTH_RADIUS_M = 6371009.0

# Row-group sizes: chosen so pyarrow predicate-pushdown on the bbox / location
# sort keys skips irrelevant groups at read time.
EDGES_ROW_GROUP = 64_000
NODES_ROW_GROUP = 256_000

# ---------------------------------------------------------------------------
# Way network filters -- parity with OSMnx 2.1.1 _overpass._get_network_filter.
#
# The Overpass "!~" operator is a regex SEARCH on the tag value, applied only
# when the tag exists. We replicate it exactly with re.search on unanchored
# patterns, so e.g. highway="motorway" is excluded by "motor" and foot="unknown"
# is excluded by "no" (contains the substring "no") -- deliberate parity, not a
# bug. A way is EXCLUDED from a mode if ANY of its rules matches.
# ---------------------------------------------------------------------------

_WALK_EXCLUDE: List[Tuple[str, str]] = [
    ("area", "yes"),
    ("access", "private"),
    (
        "highway",
        "abandoned|bus_guideway|construction|cycleway|motor|no|planned|"
        "platform|proposed|raceway|razed|rest_area|services",
    ),
    ("foot", "no"),
    ("service", "private"),
    ("sidewalk", "separate"),
    ("sidewalk:both", "separate"),
    ("sidewalk:left", "separate"),
    ("sidewalk:right", "separate"),
]

_BIKE_EXCLUDE: List[Tuple[str, str]] = [
    ("area", "yes"),
    ("access", "private"),
    (
        "highway",
        "abandoned|bus_guideway|construction|corridor|elevator|escalator|"
        "footway|motor|no|planned|platform|proposed|raceway|razed|rest_area|"
        "services|steps",
    ),
    ("bicycle", "no"),
    ("service", "private"),
]

_WALK_RULES = [(k, re.compile(p)) for k, p in _WALK_EXCLUDE]
_BIKE_RULES = [(k, re.compile(p)) for k, p in _BIKE_EXCLUDE]

# oneway value sets (exact match, not regex).
_ONEWAY_FWD = {"yes", "true", "1"}
_ONEWAY_REV = {"-1", "reverse"}


def _excluded(tags: Any, rules: List[Tuple[str, "re.Pattern[str]"]]) -> bool:
    """True if the way's tags trip any exclusion rule (Overpass !~ semantics)."""
    for key, pat in rules:
        if key in tags and pat.search(tags[key]):
            return True
    return False


def _oneway_bike(tags: Any) -> int:
    """0 = both directions, 1 = only u->v, -1 = only v->u.

    Simplification: oneway:bicycle / cycleway=opposite are NOT considered here;
    only the plain `oneway` tag. Walk is bidirectional regardless (OSMnx:
    bidirectional_network_types == ["walk"]).
    """
    v = tags.get("oneway")
    if v in _ONEWAY_FWD:
        return 1
    if v in _ONEWAY_REV:
        return -1
    return 0


def _haversine_m(
    lon1: np.ndarray, lat1: np.ndarray, lon2: np.ndarray, lat2: np.ndarray
) -> np.ndarray:
    """Vectorized great-circle distance in metres between coordinate pairs."""
    lon1 = np.radians(lon1)
    lat1 = np.radians(lat1)
    lon2 = np.radians(lon2)
    lat2 = np.radians(lat2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def _match_groups(tags: Any, poi_groups: Dict[str, Dict[str, Any]]) -> List[str]:
    """Return every POI group whose tag dict matches these tags.

    Same semantics as analysis._matches_tags: a key must be present and its
    value present in the group's value list (or values is True = key present).
    One feature can match multiple groups.
    """
    matched: List[str] = []
    for group, spec in poi_groups.items():
        for key, values in spec["tags"].items():
            if key in tags:
                val = tags[key]
                if values is True or val in values:
                    matched.append(group)
                    break
    return matched


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


class _NetworkHandler(osmium.SimpleHandler):
    """Collect one edge row per consecutive node pair of every kept highway way.

    No simplification (parity with OSMnx simplify=False). Node coordinates come
    straight from the way nodes (locations=True), so we also collect exactly the
    nodes that occur in kept ways -- no separate node pass needed.
    """

    def __init__(self) -> None:
        super().__init__()
        self.u: List[int] = []
        self.v: List[int] = []
        self.lon1: List[float] = []
        self.lat1: List[float] = []
        self.lon2: List[float] = []
        self.lat2: List[float] = []
        self.highway: List[str] = []
        self.walk: List[bool] = []
        self.bike: List[bool] = []
        self.oneway: List[int] = []
        self.nodes: Dict[int, Tuple[float, float]] = {}

    def way(self, w: Any) -> None:  # noqa: D401 (osmium callback)
        tags = w.tags
        if "highway" not in tags:
            return
        walk_ok = not _excluded(tags, _WALK_RULES)
        bike_ok = not _excluded(tags, _BIKE_RULES)
        if not (walk_ok or bike_ok):
            return
        hw = tags.get("highway")
        ob = _oneway_bike(tags)

        prev: Optional[Tuple[int, float, float]] = None
        for nd in w.nodes:
            loc = nd.location
            if not loc.valid():
                # Missing node location (e.g. clipped at the extract boundary):
                # break the segment chain so we never span the gap.
                prev = None
                continue
            cur = (nd.ref, loc.lon, loc.lat)
            self.nodes[cur[0]] = (cur[1], cur[2])
            if prev is not None and prev[0] != cur[0]:
                self.u.append(prev[0])
                self.v.append(cur[0])
                self.lon1.append(prev[1])
                self.lat1.append(prev[2])
                self.lon2.append(cur[1])
                self.lat2.append(cur[2])
                self.highway.append(hw)
                self.walk.append(walk_ok)
                self.bike.append(bike_ok)
                self.oneway.append(ob)
            prev = cur


class _PoiHandler(osmium.SimpleHandler):
    """Collect POIs from tagged nodes and assembled areas.

    Defining an `area` callback makes pyosmium run the area assembler in a
    two-pass scan (closed ways with matching tags AND multipolygon relations
    become areas). Point nodes come through the `node` callback. Open (non-area)
    ways with matching tags are intentionally skipped -- they are rare for these
    POI groups and skipping them also avoids double-counting closed ways that
    already arrive as areas (dedup by construction: node ids, way areas and
    relation areas never collide).
    """

    def __init__(self, poi_groups: Dict[str, Dict[str, Any]]) -> None:
        super().__init__()
        self.groups = poi_groups
        self.wkbfab = osmium.geom.WKBFactory()
        self.ids: List[str] = []
        self.names: List[Optional[str]] = []
        self.cats: List[str] = []
        self.xs: List[float] = []
        self.ys: List[float] = []

    def _emit(
        self, osm_id: str, name: Optional[str], x: float, y: float, matched: List[str]
    ) -> None:
        for g in matched:
            self.ids.append(osm_id)
            self.names.append(name)
            self.cats.append(g)
            self.xs.append(x)
            self.ys.append(y)

    def node(self, n: Any) -> None:  # noqa: D401 (osmium callback)
        matched = _match_groups(n.tags, self.groups)
        if not matched:
            return
        loc = n.location
        if not loc.valid():
            return
        self._emit(f"node/{n.id}", n.tags.get("name"), loc.lon, loc.lat, matched)

    def area(self, a: Any) -> None:  # noqa: D401 (osmium callback)
        matched = _match_groups(a.tags, self.groups)
        if not matched:
            return
        try:
            wkb = self.wkbfab.create_multipolygon(a)
            geom = shapely.wkb.loads(bytes.fromhex(wkb))
        except Exception:
            # Broken / unassemblable geometry -- skip this feature.
            return
        if geom.is_empty:
            return
        cent = geom.centroid
        if cent.is_empty:
            return
        osm_id = f"way/{a.orig_id()}" if a.from_way() else f"relation/{a.orig_id()}"
        self._emit(osm_id, a.tags.get("name"), float(cent.x), float(cent.y), matched)


# ---------------------------------------------------------------------------
# Parquet writers
# ---------------------------------------------------------------------------


def _write_edges(h: _NetworkHandler, out_dir: Path) -> int:
    lon1 = np.asarray(h.lon1, dtype=np.float64)
    lat1 = np.asarray(h.lat1, dtype=np.float64)
    lon2 = np.asarray(h.lon2, dtype=np.float64)
    lat2 = np.asarray(h.lat2, dtype=np.float64)

    length = _haversine_m(lon1, lat1, lon2, lat2)
    minx = np.minimum(lon1, lon2).astype(np.float32)
    maxx = np.maximum(lon1, lon2).astype(np.float32)
    miny = np.minimum(lat1, lat2).astype(np.float32)
    maxy = np.maximum(lat1, lat2).astype(np.float32)

    u = np.asarray(h.u, dtype=np.int64)
    v = np.asarray(h.v, dtype=np.int64)
    walk = np.asarray(h.walk, dtype=bool)
    bike = np.asarray(h.bike, dtype=bool)
    oneway = np.asarray(h.oneway, dtype=np.int8)

    # Sort on (round(minx,1), round(miny,1)) for bbox predicate-pushdown.
    kx = np.round(minx.astype(np.float64), 1)
    ky = np.round(miny.astype(np.float64), 1)
    order = np.lexsort((ky, kx))  # primary key = kx

    table = pa.table(
        {
            "u": u,
            "v": v,
            "length": length,
            "highway": pa.array(h.highway, type=pa.string()),
            "walk_ok": walk,
            "bike_ok": bike,
            "oneway_bike": oneway,
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
        }
    ).take(pa.array(order))

    pq.write_table(table, str(out_dir / "edges.parquet"), row_group_size=EDGES_ROW_GROUP)
    return table.num_rows


def _write_nodes(nodes: Dict[int, Tuple[float, float]], out_dir: Path) -> int:
    n = len(nodes)
    ids = np.fromiter(nodes.keys(), dtype=np.int64, count=n)
    xs = np.fromiter((c[0] for c in nodes.values()), dtype=np.float64, count=n)
    ys = np.fromiter((c[1] for c in nodes.values()), dtype=np.float64, count=n)

    kx = np.round(xs, 1)
    ky = np.round(ys, 1)
    order = np.lexsort((ky, kx))

    table = pa.table({"id": ids, "x": xs, "y": ys}).take(pa.array(order))
    pq.write_table(table, str(out_dir / "nodes.parquet"), row_group_size=NODES_ROW_GROUP)
    return table.num_rows


def _write_pois(h: _PoiHandler, out_dir: Path) -> int:
    xs = np.asarray(h.xs, dtype=np.float64)
    ys = np.asarray(h.ys, dtype=np.float64)

    kx = np.round(xs, 1)
    ky = np.round(ys, 1)
    order = np.lexsort((ky, kx))

    table = pa.table(
        {
            "id": pa.array(h.ids, type=pa.string()),
            "name": pa.array(h.names, type=pa.string()),
            "category": pa.array(h.cats, type=pa.string()),
            "x": xs,
            "y": ys,
        }
    ).take(pa.array(order))

    pq.write_table(table, str(out_dir / "pois.parquet"))
    return table.num_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_out_dir() -> Path:
    """Same resolution as local_osm.LOCAL_OSM_DIR so both point at one dir."""
    env = os.environ.get("ACCESSX_LOCAL_OSM")
    raw = env if env else "%LOCALAPPDATA%/accessx_webapp_cache/local_osm"
    return Path(os.path.expandvars(raw))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="prepare_local_data.py",
        description=(
            "Zet een lokale Geofabrik .osm.pbf om naar edges/nodes/pois parquet "
            "+ meta.json voor de accessX-webapp-backend."
        ),
    )
    p.add_argument("pbf", help="Pad naar de .osm.pbf (bv. utrecht-latest.osm.pbf)")
    p.add_argument(
        "--out-dir",
        default=None,
        help=(
            "Uitvoermap (default: %%LOCALAPPDATA%%/accessx_webapp_cache/local_osm "
            "of $ACCESSX_LOCAL_OSM)"
        ),
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    pbf = Path(args.pbf)
    if not pbf.is_file():
        print(f"FOUT: pbf-bestand niet gevonden: {pbf}", file=sys.stderr)
        return 2

    out_dir = Path(os.path.expandvars(args.out_dir)) if args.out_dir else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import POI_GROUPS from analysis.py as the single source of truth. Done
    # here (not at module import) so --help stays cheap and independent of the
    # heavy geopandas/osmnx/accessx stack.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from analysis import POI_GROUPS  # noqa: E402

    print(f"Prep gestart voor: {pbf}")
    print(f"Uitvoermap:        {out_dir}")
    t_start = time.perf_counter()

    # --- Network pass -----------------------------------------------------
    print("Netwerk uitlezen (ways -> edges/nodes)...")
    t0 = time.perf_counter()
    nh = _NetworkHandler()
    nh.apply_file(str(pbf), locations=True, idx="flex_mem")
    t_net = time.perf_counter() - t0
    print(f"  ways verwerkt in {t_net:.1f}s: {len(nh.u)} segmenten, {len(nh.nodes)} knopen")

    t0 = time.perf_counter()
    n_edges = _write_edges(nh, out_dir)
    n_nodes = _write_nodes(nh.nodes, out_dir)
    print(f"  edges.parquet + nodes.parquet geschreven in {time.perf_counter() - t0:.1f}s")
    del nh  # free the large edge/node buffers before the POI pass

    # --- POI pass ---------------------------------------------------------
    print("POI's uitlezen (nodes + areas)...")
    t0 = time.perf_counter()
    ph = _PoiHandler(POI_GROUPS)
    ph.apply_file(str(pbf), locations=True, idx="flex_mem")
    t_poi = time.perf_counter() - t0
    print(f"  POI-features verwerkt in {t_poi:.1f}s: {len(ph.ids)} rijen")

    t0 = time.perf_counter()
    n_pois = _write_pois(ph, out_dir)
    print(f"  pois.parquet geschreven in {time.perf_counter() - t0:.1f}s")
    del ph

    # --- meta.json --------------------------------------------------------
    meta = {
        "source": pbf.name,
        "prepared": datetime.now().astimezone().isoformat(timespec="seconds"),
        "n_edges": int(n_edges),
        "n_nodes": int(n_nodes),
        "n_pois": int(n_pois),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    total = time.perf_counter() - t_start
    print("Klaar.")
    print(f"  n_edges={n_edges}  n_nodes={n_nodes}  n_pois={n_pois}")
    print(f"  netwerk-pass={t_net:.1f}s  poi-pass={t_poi:.1f}s  totaal={total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
