"""Request-time access to a locally prepared OSM extract.

Reads the parquet files produced by ``prepare_local_data.py`` and builds an
OSMnx-compatible graph and a POI GeoDataFrame for an AOI, so a fresh analysis
runs in seconds without hitting Overpass. If the local data is missing or a
build fails, callers fall back to the existing Overpass paths.

User-facing strings (raised errors) are in Dutch; code and comments are English.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as pds
import shapely

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LOCAL_OSM_DIR = Path(
    os.path.expandvars(
        os.environ.get(
            "ACCESSX_LOCAL_OSM",
            "%LOCALAPPDATA%/accessx_webapp_cache/local_osm",
        )
    )
)

_EDGES_FILE = "edges.parquet"
_NODES_FILE = "nodes.parquet"
_POIS_FILE = "pois.parquet"
_GREEN_FILE = "green.parquet"
_META_FILE = "meta.json"

# Extra margin (degrees) added to the query bbox so edges/nodes straddling the
# AOI boundary are still loaded. ~500 m at Dutch latitudes.
_BBOX_MARGIN_DEG = 0.005

METRIC_EPSG_DEFAULT = 28992  # RD New

# ---------------------------------------------------------------------------
# Lazy module caches (init guarded by a lock; reads are GIL-safe afterwards)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_edges_dataset: Optional[pds.Dataset] = None
_nodes_dataset: Optional[pds.Dataset] = None
_pois_df: Optional[pd.DataFrame] = None


def _dir() -> Path:
    return LOCAL_OSM_DIR


def local_data_available() -> bool:
    """True iff all three parquet files and meta.json are present."""
    d = _dir()
    return all(
        (d / name).is_file()
        for name in (_EDGES_FILE, _NODES_FILE, _POIS_FILE, _META_FILE)
    )


def read_meta() -> dict:
    """Return the meta.json contents (or {} if unreadable)."""
    try:
        with open(_dir() / _META_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def missing_categories(selected: List[str]) -> List[str]:
    """Selected categories that this extract was not prepared for.

    The category is baked into pois.parquet at prep time, so an extract built
    before a POI_GROUPS change silently returns 0 POIs for any new category.
    Callers use this to fall back to Overpass instead. An extract without a
    "categories" key in meta.json predates this check and is treated as stale
    for every category.
    """
    known = read_meta().get("categories")
    if not isinstance(known, list):
        return list(selected)
    return [c for c in selected if c not in set(known)]


def _get_edges_dataset() -> pds.Dataset:
    global _edges_dataset
    if _edges_dataset is None:
        with _lock:
            if _edges_dataset is None:
                _edges_dataset = pds.dataset(
                    str(_dir() / _EDGES_FILE), format="parquet"
                )
    return _edges_dataset


def _get_nodes_dataset() -> pds.Dataset:
    global _nodes_dataset
    if _nodes_dataset is None:
        with _lock:
            if _nodes_dataset is None:
                _nodes_dataset = pds.dataset(
                    str(_dir() / _NODES_FILE), format="parquet"
                )
    return _nodes_dataset


def _get_pois_df() -> pd.DataFrame:
    global _pois_df
    if _pois_df is None:
        with _lock:
            if _pois_df is None:
                # POIs are small; keep the whole set in RAM as a DataFrame.
                _pois_df = pd.read_parquet(str(_dir() / _POIS_FILE))
    return _pois_df


def green_data_available() -> bool:
    return (_dir() / _GREEN_FILE).is_file()


def load_green_local(
    aoi_buf_wgs84: gpd.GeoDataFrame, min_area_m2: float = 5_000.0
) -> gpd.GeoDataFrame:
    """Groenvlakken (polygonen) die de AOI raken, uit de lokale extract.

    Anders dan bij POI's blijft de vorm bewaard: voor de 300 m-norm telt de
    afstand tot de rand van het park, niet tot het middelpunt.
    """
    path = _dir() / _GREEN_FILE
    if not path.is_file():
        return gpd.GeoDataFrame({"soort": [], "area_m2": []}, geometry=[], crs=4326)

    polygon = aoi_buf_wgs84.geometry.union_all()
    minx, miny, maxx, maxy = polygon.bounds
    tbl = pds.dataset(str(path), format="parquet").to_table(
        columns=["wkb", "soort", "area_m2"],
        filter=(
            (pc.field("minx") <= maxx)
            & (pc.field("maxx") >= minx)
            & (pc.field("miny") <= maxy)
            & (pc.field("maxy") >= miny)
            & (pc.field("area_m2") >= float(min_area_m2))
        ),
    )
    if tbl.num_rows == 0:
        return gpd.GeoDataFrame({"soort": [], "area_m2": []}, geometry=[], crs=4326)

    geoms = shapely.from_wkb(tbl.column("wkb").to_pylist())
    gdf = gpd.GeoDataFrame(
        {
            "soort": tbl.column("soort").to_pylist(),
            "area_m2": tbl.column("area_m2").to_pylist(),
        },
        geometry=list(geoms),
        crs=4326,
    )
    # De bbox-filter is een grove voorselectie; nu de echte doorsnede.
    return gdf[gdf.geometry.intersects(polygon)].reset_index(drop=True)


def reset_caches() -> None:
    """Drop cached datasets/DataFrame (e.g. after the data dir was refreshed)."""
    global _edges_dataset, _nodes_dataset, _pois_df
    with _lock:
        _edges_dataset = None
        _nodes_dataset = None
        _pois_df = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _buffered_polygon(
    aoi_wgs84: gpd.GeoDataFrame, buffer_m: float, city_epsg: int
):
    """The AOI buffered by buffer_m (in city_epsg), returned as a WGS84 polygon.

    The buffer is applied in the metric CRS exactly like the pipeline /
    accessx.build_network does, then taken back to WGS84. This polygon is the
    exact clip boundary that ``ox.graph_from_polygon`` uses, so clipping local
    nodes to it gives node/edge parity with the Overpass build.
    """
    aoi = aoi_wgs84
    if buffer_m and buffer_m > 0:
        aoi_m = aoi_wgs84.to_crs(city_epsg)
        aoi_m = aoi_m.copy()
        aoi_m["geometry"] = aoi_m.buffer(buffer_m)
        aoi = aoi_m.to_crs(4326)
    return aoi.geometry.union_all()


def _query_bbox(
    poly_buf, margin: float = _BBOX_MARGIN_DEG
) -> Tuple[float, float, float, float]:
    """Bbox (lon/lat) of the buffered polygon, widened by a small margin.

    Used only to drive the parquet predicate-pushdown filters (a cheap
    superset load). The exact clip to ``poly_buf`` is done afterwards so the
    margin never inflates the final graph.
    """
    minx, miny, maxx, maxy = poly_buf.bounds
    return (
        float(minx) - margin,
        float(miny) - margin,
        float(maxx) + margin,
        float(maxy) + margin,
    )


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def build_graph_local(
    aoi_wgs84: gpd.GeoDataFrame,
    buffer_m: float,
    network_type: str,
    city_epsg: int = METRIC_EPSG_DEFAULT,
):
    """Build an OSMnx-compatible graph for the AOI from the local extract.

    Mirrors ``accessx.build_network(..., simplify=False)``: unsimplified edges,
    isolates removed, projected to ``city_epsg``; for walk the graph is
    collapsed to an undirected MultiGraph (walk is bidirectional). For bike a
    directed MultiDiGraph is returned honouring per-edge oneway direction.

    Raises ValueError (Dutch) on an empty result so the caller can fall back.
    """
    if network_type not in ("walk", "bike"):
        raise ValueError(f"Onbekend netwerktype: {network_type!r}.")

    # The buffered polygon is the exact clip boundary used by
    # accessx.build_network via ox.graph_from_polygon (truncate_by_edge=False:
    # nodes strictly inside the polygon are kept). We load a slightly larger
    # bbox for predicate-pushdown, then clip nodes to this polygon so the
    # node/edge count matches the Overpass build instead of a larger rectangle.
    poly_buf = _buffered_polygon(aoi_wgs84, buffer_m, city_epsg)
    minx, miny, maxx, maxy = _query_bbox(poly_buf)

    # --- edges: bbox overlap + walkable/bikeable ---------------------------
    ok_col = "walk_ok" if network_type == "walk" else "bike_ok"
    edge_filter = (
        (pc.field("minx") <= maxx)
        & (pc.field("maxx") >= minx)
        & (pc.field("miny") <= maxy)
        & (pc.field("maxy") >= miny)
        & (pc.field(ok_col) == True)  # noqa: E712 (pyarrow needs ==, not `is`)
    )
    edges_tbl = _get_edges_dataset().to_table(
        columns=["u", "v", "length", "highway", "oneway_bike"],
        filter=edge_filter,
    )

    # --- nodes: x/y within bbox -> id -> (x, y) ----------------------------
    node_filter = (
        (pc.field("x") >= minx)
        & (pc.field("x") <= maxx)
        & (pc.field("y") >= miny)
        & (pc.field("y") <= maxy)
    )
    nodes_tbl = _get_nodes_dataset().to_table(
        columns=["id", "x", "y"], filter=node_filter
    )
    node_ids = nodes_tbl.column("id").to_pylist()
    node_xs = nodes_tbl.column("x").to_pylist()
    node_ys = nodes_tbl.column("y").to_pylist()
    # Clip to the buffered polygon (parity with graph_from_polygon): keep only
    # nodes strictly inside it. Edges with an endpoint outside get dropped
    # below because their node id is then absent from node_xy.
    if node_ids:
        inside = shapely.contains_xy(poly_buf, node_xs, node_ys)
        node_xy: Dict[int, Tuple[float, float]] = {
            node_ids[k]: (node_xs[k], node_ys[k])
            for k in range(len(node_ids))
            if inside[k]
        }
    else:
        node_xy = {}

    # --- assemble MultiDiGraph --------------------------------------------
    us = edges_tbl.column("u").to_pylist()
    vs = edges_tbl.column("v").to_pylist()
    lengths = edges_tbl.column("length").to_pylist()
    highways = edges_tbl.column("highway").to_pylist()
    oneways = edges_tbl.column("oneway_bike").to_pylist()

    G = nx.MultiDiGraph()
    G.graph["crs"] = "EPSG:4326"

    is_walk = network_type == "walk"
    for eid in range(len(us)):
        u = us[eid]
        v = vs[eid]
        pu = node_xy.get(u)
        pv = node_xy.get(v)
        if pu is None or pv is None:
            # Endpoint outside the loaded node window -> drop the edge.
            continue
        if u not in G:
            G.add_node(u, x=pu[0], y=pu[1])
        if v not in G:
            G.add_node(v, x=pv[0], y=pv[1])
        length = float(lengths[eid])
        hw = highways[eid]
        # osmid is required by osmnx.convert.to_undirected to detect the
        # reverse-direction duplicate of a segment; both directions of one
        # segment share eid so they collapse to a single undirected edge.
        if is_walk:
            G.add_edge(u, v, osmid=eid, length=length, highway=hw)
            G.add_edge(v, u, osmid=eid, length=length, highway=hw)
        else:
            ow = oneways[eid]
            if ow == 1:  # u -> v only
                G.add_edge(u, v, osmid=eid, length=length, highway=hw)
            elif ow == -1:  # v -> u only
                G.add_edge(v, u, osmid=eid, length=length, highway=hw)
            else:  # 0 (or unexpected) -> both directions
                G.add_edge(u, v, osmid=eid, length=length, highway=hw)
                G.add_edge(v, u, osmid=eid, length=length, highway=hw)

    # Remove isolated nodes, mirroring build_network(remove_isolates=True).
    G.remove_nodes_from(list(nx.isolates(G)))

    if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
        raise ValueError(
            "Lokale extract leverde een leeg straatnetwerk op voor dit gebied."
        )

    # Project to the metric CRS, then collapse walk to undirected.
    G = ox.projection.project_graph(G, to_crs=city_epsg)
    if is_walk:
        G = ox.convert.to_undirected(G)
    return G


# ---------------------------------------------------------------------------
# POIs
# ---------------------------------------------------------------------------

def _empty_pois() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": [], "name": [], "category": []}, geometry=[], crs=4326
    )


def load_pois_local(
    aoi_buf_wgs84: gpd.GeoDataFrame, selected: List[str]
) -> gpd.GeoDataFrame:
    """POIs within the (already buffered) AOI polygon, filtered to `selected`.

    Output schema matches ``analysis.fetch_pois_combined``: columns id, name,
    category and a point geometry in EPSG:4326. Returns an empty GeoDataFrame
    with that schema when nothing matches.
    """
    df = _get_pois_df()
    if df is None or len(df) == 0:
        return _empty_pois()

    # Match fetch_pois_combined: an empty selection yields no POIs.
    df = df[df["category"].isin(list(selected))]
    if len(df) == 0:
        return _empty_pois()

    polygon = aoi_buf_wgs84.geometry.union_all()
    if polygon.is_empty:
        return _empty_pois()

    minx, miny, maxx, maxy = polygon.bounds
    # Cheap bbox prefilter before the exact point-in-polygon test.
    bbox_mask = (
        (df["x"] >= minx)
        & (df["x"] <= maxx)
        & (df["y"] >= miny)
        & (df["y"] <= maxy)
    )
    sub = df[bbox_mask]
    if len(sub) == 0:
        return _empty_pois()

    xs = sub["x"].to_numpy()
    ys = sub["y"].to_numpy()
    inside = shapely.contains_xy(polygon, xs, ys)
    sub = sub[inside]
    if len(sub) == 0:
        return _empty_pois()

    data = {
        "id": sub["id"].to_numpy(),
        "name": sub["name"].to_numpy() if "name" in sub.columns else None,
        "category": sub["category"].to_numpy(),
    }
    # Adres doorgeven als de extract het heeft (prep van vóór de adres-koppeling
    # levert deze kolommen niet); bag.py koppelt daarop de vloeroppervlakte.
    for src, dst in (
        ("addr_street", "addr:street"),
        ("addr_housenumber", "addr:housenumber"),
        ("addr_postcode", "addr:postcode"),
    ):
        if src in sub.columns:
            data[dst] = sub[src].to_numpy()
    out = gpd.GeoDataFrame(
        data,
        geometry=gpd.points_from_xy(sub["x"].to_numpy(), sub["y"].to_numpy()),
        crs=4326,
    )
    return out
