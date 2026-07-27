"""accessX analysis pipeline for the webapp backend.

Importable on its own: no FastAPI imports here. User-facing strings (labels,
warnings, errors) are in Dutch; code and comments are in English.
"""
from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd
from shapely.geometry import mapping, shape

import accessx as acx

import local_osm

# ---------------------------------------------------------------------------
# Paths and settings
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
CBS_PATH = REPO_ROOT / "data" / "nl_cbs" / "cbs_vk100_2020_vol.gpkg"

# Keep the OSMnx cache on a local disk, not on the network share.
ox.settings.cache_folder = str(
    Path(os.environ.get("LOCALAPPDATA", ".")) / "accessx_webapp_cache"
)
ox.settings.use_cache = True

METRIC_EPSG = 28992  # RD New
NL_BBOX = (3.2, 50.7, 7.3, 53.6)  # lon_min, lat_min, lon_max, lat_max
MAX_BUFFER_M = 2500.0

# ---------------------------------------------------------------------------
# Presets (see CONTRACT.md)
# ---------------------------------------------------------------------------

POI_GROUPS: Dict[str, Dict[str, Any]] = {
    "daily_needs": {
        "label": "Dagelijkse boodschappen",
        "tags": {
            "shop": ["supermarket", "bakery", "greengrocer", "butcher"],
            "amenity": ["marketplace"],
        },
    },
    "healthcare": {
        "label": "Gezondheidszorg",
        "tags": {"amenity": ["pharmacy", "doctors", "clinic", "hospital", "dentist"]},
    },
    "education": {
        "label": "Onderwijs",
        "tags": {"amenity": ["school", "kindergarten"]},
    },
    "parken_natuur": {
        "label": "Parken & natuur",
        "tags": {
            "leisure": ["park", "nature_reserve", "recreation_ground", "dog_park", "common"],
            "landuse": ["recreation_ground", "village_green"],
        },
    },
    "speeltuinen": {
        "label": "Speeltuinen",
        "tags": {"leisure": ["playground"]},
    },
    "volkstuinen": {
        "label": "Volkstuinen & moestuinen",
        "tags": {"landuse": ["allotments"]},
    },
    "public_transport": {
        "label": "OV-haltes",
        "tags": {
            "highway": ["bus_stop"],
            "railway": ["station", "tram_stop"],
            "amenity": ["bus_station"],
        },
    },
    "meeting": {
        "label": "Horeca & ontmoeten",
        "tags": {"amenity": ["cafe", "restaurant", "community_centre", "library"]},
    },
    "sports": {
        "label": "Sport",
        "tags": {"leisure": ["sports_centre", "fitness_centre", "swimming_pool"]},
    },
}

DEFAULTS: Dict[str, Any] = {
    "mode": "walk",
    "speed_kmh": 4.5,
    "max_minutes": 15,
    "hex_resolution": 9,
    "selected_groups": [
        "daily_needs",
        "healthcare",
        "education",
        "parken_natuur",
        "speeltuinen",
        "public_transport",
    ],
    "analyses": ["counts", "nearest", "hansen", "population", "2sfca", "equity"],
}

LIMITS: Dict[str, Any] = {"max_area_km2": 100, "warn_area_km2": 25}

ANALYSIS_KEYS = ["counts", "nearest", "hansen", "population", "2sfca", "equity"]

# Ordered stage definitions (key, Dutch label).
STAGES: List[Tuple[str, str]] = [
    ("hexgrid", "H3-hexgrid genereren"),
    ("network", "Straatnetwerk (OSM) laden"),
    ("cost", "Reistijdkosten toekennen"),
    ("pois", "Voorzieningen (OSM) ophalen"),
    ("population", "CBS-bevolking koppelen"),
    ("counts", "Bereikbare voorzieningen tellen"),
    ("nearest", "Dichtstbijzijnde voorziening"),
    ("hansen", "Hansen-bereikbaarheid"),
    ("sfca", "2SFCA (vraag/aanbod)"),
    ("equity", "Verdeling & Gini"),
]

CBS_COLS = [
    "aantal_inwoners",
    "aantal_inwoners_0_tot_15_jaar",
    "aantal_inwoners_15_tot_25_jaar",
    "aantal_inwoners_25_tot_45_jaar",
    "aantal_inwoners_45_tot_65_jaar",
    "aantal_inwoners_65_jaar_en_ouder",
]

CBS_RENAME = {
    "aantal_inwoners": "population",
    "aantal_inwoners_0_tot_15_jaar": "pop_0_15",
    "aantal_inwoners_15_tot_25_jaar": "pop_15_25",
    "aantal_inwoners_25_tot_45_jaar": "pop_25_45",
    "aantal_inwoners_45_tot_65_jaar": "pop_45_65",
    "aantal_inwoners_65_jaar_en_ouder": "pop_65plus",
}


class PipelineError(Exception):
    """Fatal pipeline error with a user-readable Dutch message."""


class NullReporter:
    """No-op stage reporter; jobs.py provides one that publishes job state."""

    def start(self, key: str) -> None:  # noqa: D102
        pass

    def done(self, key: str, seconds: float, detail: Optional[str] = None) -> None:  # noqa: D102
        pass

    def skip(self, key: str, detail: Optional[str] = None) -> None:  # noqa: D102
        pass

    def warn(self, message: str) -> None:  # noqa: D102
        pass


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def sanitize_json(obj: Any) -> Any:
    """Recursively replace NaN/+-inf with None and numpy scalars with Python types."""
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [sanitize_json(v) for v in obj.tolist()]
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _is_unserializable(value: Any) -> bool:
    return isinstance(value, (list, tuple, dict, set, np.ndarray))


def gdf_to_feature_collection(gdf: gpd.GeoDataFrame) -> dict:
    """GeoDataFrame (EPSG:4326) -> sanitized GeoJSON FeatureCollection dict.

    List-/tuple-like columns are dropped first; NaN/inf become null.
    """
    drop_cols = [
        c
        for c in gdf.columns
        if c != gdf.geometry.name and gdf[c].map(_is_unserializable).any()
    ]
    if drop_cols:
        gdf = gdf.drop(columns=drop_cols)
    fc = json.loads(gdf.to_json())
    return sanitize_json(fc)


# ---------------------------------------------------------------------------
# Request validation helpers (used by main.py; raise ValueError in Dutch)
# ---------------------------------------------------------------------------

def repair_geometry(shp: Any) -> Any:
    """Repair invalid (e.g. self-intersecting) geometries via the buffer(0) trick.

    Must be applied identically during validation and in the pipeline, so the
    area that was validated is the area that gets analysed.
    """
    if shp.is_empty or not shp.is_valid:
        shp = shp.buffer(0)
    return shp


def extract_geometry(polygon: Any) -> dict:
    """Accept a GeoJSON geometry or Feature and return the geometry dict."""
    if not isinstance(polygon, dict):
        raise ValueError("Ongeldige polygoon: verwacht een GeoJSON-object.")
    if polygon.get("type") == "Feature":
        polygon = polygon.get("geometry") or {}
    if polygon.get("type") not in ("Polygon", "MultiPolygon"):
        raise ValueError("Ongeldige polygoon: teken een (multi)polygoon op de kaart.")
    return polygon


def validate_polygon(geom: dict) -> Tuple[gpd.GeoDataFrame, float]:
    """Validate NL bbox + area. Returns (aoi in EPSG:4326, area_km2)."""
    try:
        shp = shape(geom)
    except Exception as exc:
        raise ValueError(f"Ongeldige polygoon: {exc}") from exc
    shp = repair_geometry(shp)
    if shp.is_empty:
        raise ValueError("Ongeldige polygoon: lege geometrie.")
    minx, miny, maxx, maxy = shp.bounds
    lon_min, lat_min, lon_max, lat_max = NL_BBOX
    if minx < lon_min or maxx > lon_max or miny < lat_min or maxy > lat_max:
        raise ValueError("Het getekende gebied ligt (deels) buiten Nederland.")
    aoi = gpd.GeoDataFrame(geometry=[shp], crs=4326)
    area_km2 = float(aoi.to_crs(METRIC_EPSG).area.sum()) / 1e6
    if area_km2 > LIMITS["max_area_km2"]:
        raise ValueError(
            f"Het gebied is {area_km2:.1f} km²; maximaal "
            f"{LIMITS['max_area_km2']} km² is toegestaan. Teken een kleiner gebied."
        )
    return aoi, area_km2


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _subsample(values: List[float], n: int = 100) -> List[float]:
    """Subsample a list to at most n points, keeping first and last."""
    vals = [float(v) for v in values]
    if len(vals) <= n:
        return vals
    idx = np.linspace(0, len(vals) - 1, n).round().astype(int)
    return [vals[i] for i in idx]


def _merge_group_tags(selected: List[str]) -> Dict[str, Any]:
    """Union the OSM tag dicts of the selected groups into one query dict."""
    merged: Dict[str, Any] = {}
    for group in selected:
        for key, values in POI_GROUPS[group]["tags"].items():
            if values is True or merged.get(key) is True:
                merged[key] = True
                continue
            vals = [values] if isinstance(values, str) else list(values)
            merged[key] = sorted(set(merged.get(key, [])) | set(vals))
    return merged


def _matches_tags(features: gpd.GeoDataFrame, tags: Dict[str, Any]) -> pd.Series:
    """Boolean mask: rows matching any (key, value) pair of a group's tag dict."""
    mask = pd.Series(False, index=features.index)
    for key, values in tags.items():
        if key not in features.columns:
            continue
        col = features[key]
        if values is True:
            mask |= col.notna()
        else:
            vals = [values] if isinstance(values, str) else list(values)
            mask |= col.isin(vals)
    return mask


def fetch_pois_combined(
    aoi_wgs84: gpd.GeoDataFrame, selected: List[str]
) -> gpd.GeoDataFrame:
    """Fetch POIs for ALL groups in one Overpass query and categorize locally.

    accessx.get_pois_osm issues one Overpass query per (group, tag-key) pair;
    Overpass rate-limits consecutive queries, which made this stage take ~10
    minutes for five groups. One combined query + local tag matching returns
    the same features in a fraction of the time. Output schema matches
    get_pois_osm where the pipeline depends on it: id, name, category, geometry.
    """
    polygon = aoi_wgs84.geometry.union_all()
    merged = _merge_group_tags(selected)
    empty = gpd.GeoDataFrame(
        {"id": [], "name": [], "category": []}, geometry=[], crs=4326
    )
    try:
        feats = ox.features_from_polygon(polygon, tags=merged)
    except Exception as exc:
        if type(exc).__name__ == "InsufficientResponseError":
            return empty
        raise
    if len(feats) == 0:
        return empty

    feats = feats[feats.geometry.geom_type.isin(["Point", "Polygon", "MultiPolygon"])]
    if len(feats) == 0:
        return empty

    feats = feats.reset_index()
    # osmnx 2.x uses index levels (element, id); 1.x used (element_type, osmid).
    if "element" in feats.columns and "id" in feats.columns:
        osm_id = feats["element"].astype(str) + "/" + feats["id"].astype(str)
    elif "element_type" in feats.columns and "osmid" in feats.columns:
        osm_id = feats["element_type"].astype(str) + "/" + feats["osmid"].astype(str)
    else:
        osm_id = pd.Series(range(len(feats)), index=feats.index).astype(str)
    feats = feats.assign(**{"__poi_id": osm_id})
    if "name" not in feats.columns:
        feats["name"] = None

    parts = []
    for group in selected:
        sub = feats[_matches_tags(feats, POI_GROUPS[group]["tags"])]
        if len(sub) == 0:
            continue
        part = sub[["__poi_id", "name", "geometry"]].rename(columns={"__poi_id": "id"})
        part["category"] = group
        parts.append(part)
    if not parts:
        return empty
    out = pd.concat(parts, ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=4326)


def run_pipeline(params: dict, rep: Optional[NullReporter] = None) -> dict:
    """Run the full accessX pipeline.

    `params` must contain: polygon_geom (GeoJSON geometry dict), mode, speed_kmh,
    max_minutes, hex_resolution, poi_groups, analyses, beta, sfca_decay, and
    request_echo (original request body for meta.params).

    Returns {"result": <contract dict>, "graph": <nx graph>, "hexes_m": <gdf 28992>}.
    """
    rep = rep or NullReporter()
    warnings_list: List[str] = []

    def warn(message: str) -> None:
        warnings_list.append(message)
        rep.warn(message)

    geom = params["polygon_geom"]
    mode = params["mode"]
    speed_kmh = float(params["speed_kmh"])
    max_minutes = float(params["max_minutes"])
    resolution = int(params["hex_resolution"])
    selected = list(params["poi_groups"])
    analyses = set(params["analyses"])
    beta = float(params["beta"])
    sfca_decay = params["sfca_decay"]

    timings: Dict[str, float] = {}

    # Same repair as validate_polygon: an invalid (self-intersecting) polygon
    # would otherwise reach h3/OSMnx raw and crash with a TopologyException.
    aoi = gpd.GeoDataFrame(geometry=[repair_geometry(shape(geom))], crs=4326)
    aoi_m = aoi.to_crs(METRIC_EPSG)
    area_km2 = float(aoi_m.area.sum()) / 1e6
    if area_km2 > LIMITS["warn_area_km2"]:
        warn(
            f"Groot gebied ({area_km2:.1f} km²): de analyse kan enkele "
            "minuten duren."
        )

    buffer_raw = max_minutes * speed_kmh * 1000.0 / 60.0
    buffer_m = min(buffer_raw, MAX_BUFFER_M)
    if buffer_raw > MAX_BUFFER_M:
        warn(
            f"Netwerkbuffer beperkt tot {MAX_BUFFER_M:.0f} m "
            f"(theoretisch bereik {buffer_raw:.0f} m); randeffecten mogelijk."
        )

    # --- Stage: hexgrid -----------------------------------------------------
    rep.start("hexgrid")
    t0 = time.perf_counter()
    try:
        hexes = acx.make_hex_grid(aoi, resolution=resolution)
    except Exception as exc:
        raise PipelineError(f"H3-hexgrid genereren mislukt: {exc}") from exc
    if hexes is None or len(hexes) == 0:
        raise PipelineError("Geen hexes gevonden binnen het gebied; teken een groter gebied.")
    timings["hexgrid"] = time.perf_counter() - t0
    rep.done("hexgrid", timings["hexgrid"], f"{len(hexes)} hexes")

    # Output accumulator (EPSG:4326) and metric hexes for routing.
    df_out = hexes[["hex_id", "geometry"]].copy()
    hexes_m = df_out.to_crs(METRIC_EPSG)

    # --- Stages: network+cost | pois | population (parallel) ----------------
    # These loading stages are independent and I/O-bound (OSM download,
    # Overpass, CBS read), so they run concurrently: wall-clock cost is the
    # slowest of the three instead of their sum. The stage reporter is
    # thread-safe (store lock in jobs.py); timings/warnings use distinct
    # keys/appends, which are safe under the GIL.
    need_pois = bool({"counts", "nearest", "hansen", "2sfca"} & analyses)
    need_pop = ("population" in analyses) or ("2sfca" in analyses)

    def task_network():
        """Build the network and add travel-time cost. Raises PipelineError (fatal)."""
        rep.start("network")
        t0 = time.perf_counter()
        net_type = "walk" if mode == "walk" else "bike"
        detail_suffix = ""
        g = None
        # Prefer the local OSM extract (build_network parity, no Overpass); it
        # buffers the AOI itself, so pass the unbuffered AOI + buffer_m.
        if local_osm.local_data_available():
            try:
                g = local_osm.build_graph_local(
                    aoi,
                    buffer_m=buffer_m,
                    network_type=net_type,
                    city_epsg=METRIC_EPSG,
                )
                detail_suffix = ", lokale extract"
            except Exception as exc:
                warn(
                    f"Lokale netwerk-extract mislukt ({exc}); terugval op Overpass."
                )
                g = None
        if g is None:
            try:
                g = acx.build_network(
                    aoi,
                    city_epsg=METRIC_EPSG,
                    buffer_m=buffer_m,
                    network_type=net_type,
                    undirected=(mode == "walk"),
                    simplify=False,
                )
            except Exception as exc:
                raise PipelineError(
                    f"Straatnetwerk laden vanaf OpenStreetMap mislukt: {exc}"
                ) from exc
        if g.number_of_nodes() == 0:
            raise PipelineError("Het straatnetwerk in dit gebied is leeg.")
        timings["network"] = time.perf_counter() - t0
        rep.done(
            "network",
            timings["network"],
            f"{g.number_of_nodes()} knopen, {g.number_of_edges()} kanten{detail_suffix}",
        )

        rep.start("cost")
        t0 = time.perf_counter()
        try:
            g = acx.add_time_cost_constant_speed(
                g, speed_kmh=speed_kmh, cost_col="time_min"
            )
        except Exception as exc:
            raise PipelineError(f"Reistijdkosten toekennen mislukt: {exc}") from exc
        timings["cost"] = time.perf_counter() - t0
        rep.done("cost", timings["cost"], f"{speed_kmh:g} km/u, kostenkolom time_min")
        return g

    def task_pois():
        """Fetch POIs (combined query, library fallback). Never raises."""
        rep.start("pois")
        t0 = time.perf_counter()
        detail_suffix = ""
        try:
            aoi_buf = aoi_m.copy()
            aoi_buf["geometry"] = aoi_buf.buffer(buffer_m)
            aoi_buf = aoi_buf.to_crs(4326)
            # Source order: local extract -> one combined Overpass query ->
            # accessx.get_pois_osm (slow). Warn on each fallback.
            p = None
            if local_osm.local_data_available():
                try:
                    p = local_osm.load_pois_local(aoi_buf, selected)
                    detail_suffix = ", lokale extract"
                except Exception as exc:
                    warn(
                        f"Lokale POI-extract mislukt ({exc}); "
                        "terugval op gecombineerde Overpass-query."
                    )
                    p = None
            if p is None:
                try:
                    p = fetch_pois_combined(aoi_buf, selected)
                    detail_suffix = ", 1 gecombineerde query"
                except Exception as exc:
                    warn(
                        f"Gecombineerde POI-query mislukt ({exc}); "
                        "terugval op accessx get_pois_osm (traag)."
                    )
                    p = acx.get_pois_osm(
                        aoi_buf,
                        poi_groups={k: POI_GROUPS[k]["tags"] for k in selected},
                        show_progress=False,
                    )
            timings["pois"] = time.perf_counter() - t0
            found = p is not None and len(p) > 0
            per_group = {g: 0 for g in selected}
            if found:
                counts_by_cat = p["category"].value_counts().to_dict()
                for g in selected:
                    per_group[g] = int(counts_by_cat.get(g, 0))
                rep.done(
                    "pois", timings["pois"], f"{len(p)} voorzieningen{detail_suffix}"
                )
            else:
                warn(
                    "Geen voorzieningen (OSM) gevonden in dit gebied; "
                    "voorzieningsanalyses worden overgeslagen."
                )
                rep.done("pois", timings["pois"], "0 voorzieningen")
            return p, found, per_group
        except Exception as exc:
            timings["pois"] = time.perf_counter() - t0
            warn(f"Voorzieningen ophalen mislukt ({exc}); afhankelijke analyses overgeslagen.")
            rep.skip("pois", detail="mislukt")
            return None, False, {g: 0 for g in selected}

    def task_population():
        """Read CBS grid and map to hexes. Never raises.

        Returns (pop_df_or_None, zeros, total, ok): `zeros` means the area has
        no CBS cells (water/uninhabited) and columns should be filled with 0.
        """
        rep.start("population")
        t0 = time.perf_counter()
        try:
            if not CBS_PATH.exists():
                raise FileNotFoundError(f"CBS-bestand niet gevonden: {CBS_PATH}")
            bbox = tuple(aoi_m.buffer(200).total_bounds)
            grid = gpd.read_file(str(CBS_PATH), bbox=bbox, columns=CBS_COLS)
            for c in CBS_COLS:
                # CBS uses negative sentinel values (e.g. -99997) for secret cells.
                grid[c] = (
                    pd.to_numeric(grid[c], errors="coerce").clip(lower=0).fillna(0)
                )
            if len(grid) == 0:
                timings["population"] = time.perf_counter() - t0
                warn(
                    "Geen CBS-bevolkingscellen in dit gebied (water/onbewoond); "
                    "bevolking op 0 gezet, 2SFCA en gewogen Gini overgeslagen."
                )
                rep.done("population", timings["population"], "0 cellen")
                return None, True, 0.0, False
            pop = acx.map_population_grid_to_hexes(
                hexes, grid, metric_crs=METRIC_EPSG, population_cols=CBS_COLS
            )
            pop = pop.rename(columns=CBS_RENAME)
            timings["population"] = time.perf_counter() - t0
            total = float(pop["population"].sum())
            rep.done(
                "population",
                timings["population"],
                f"{len(grid)} cellen, {total:.0f} inwoners",
            )
            return pop, False, total, total > 0
        except Exception as exc:
            timings["population"] = time.perf_counter() - t0
            warn(
                f"CBS-bevolking koppelen mislukt ({exc}); "
                "2SFCA en gewogen Gini overgeslagen."
            )
            rep.skip("population", detail="mislukt")
            return None, False, None, False

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_network = pool.submit(task_network)
        fut_pois = pool.submit(task_pois) if need_pois else None
        fut_pop = pool.submit(task_population) if need_pop else None
        if fut_pois is None:
            rep.skip("pois")
        if fut_pop is None:
            rep.skip("population")
        # pois/population tasks never raise; network errors (PipelineError)
        # propagate after the pool drains, so all stage states stay consistent.
        pois, have_pois, n_pois = (
            fut_pois.result() if fut_pois else (None, False, {g: 0 for g in selected})
        )
        if fut_pop is not None:
            pop_df, pop_zeros, population_total, has_pop = fut_pop.result()
        else:
            pop_df, pop_zeros, population_total, has_pop = None, False, None, False
        graph = fut_network.result()

    pois_m = pois.to_crs(METRIC_EPSG) if have_pois else None

    pop_out_cols: List[str] = []
    if pop_zeros:
        for c in CBS_COLS:
            df_out[CBS_RENAME[c]] = 0.0
        pop_out_cols = [CBS_RENAME[c] for c in CBS_COLS]
    elif pop_df is not None:
        pop_out_cols = [CBS_RENAME[c] for c in CBS_COLS]
        df_out = df_out.merge(
            pop_df[["hex_id"] + pop_out_cols], on="hex_id", how="left"
        )
        for c in pop_out_cols:
            df_out[c] = df_out[c].fillna(0.0)

    # --- Stage: counts ------------------------------------------------------
    counts_ran = False
    if "counts" in analyses:
        if have_pois:
            rep.start("counts")
            t0 = time.perf_counter()
            try:
                counts = acx.count_accessible_pois(
                    graph, hexes_m, pois_m, max_cost=max_minutes, cost_attr="time_min"
                )
                count_cols = [c for c in counts.columns if c.startswith("count_")]
                df_out = df_out.merge(
                    pd.DataFrame(counts[["hex_id"] + count_cols]), on="hex_id", how="left"
                )
                for g in selected:
                    col = f"count_{g}"
                    if col not in df_out.columns:
                        df_out[col] = 0
                    df_out[col] = df_out[col].fillna(0).astype(int)
                timings["counts"] = time.perf_counter() - t0
                counts_ran = True
                rep.done("counts", timings["counts"], f"{len(count_cols)} categorieën")
            except Exception as exc:
                timings["counts"] = time.perf_counter() - t0
                warn(f"Voorzieningen tellen mislukt ({exc}).")
                rep.skip("counts", detail="mislukt")
        else:
            rep.skip("counts", detail="geen voorzieningen")
    else:
        rep.skip("counts")

    # --- Stage: nearest -----------------------------------------------------
    nearest_ran = False
    if "nearest" in analyses:
        if have_pois:
            rep.start("nearest")
            t0 = time.perf_counter()
            try:
                nearest = acx.compute_nearest_poi_cost(
                    graph,
                    hexes_m,
                    pois_m,
                    max_cost=max_minutes,
                    cost_attr="time_min",
                    number_of_nearest=1,
                    output="wide",
                )
                cost_cols = [c for c in nearest.columns if c.startswith("nearest_cost_")]
                df_out = df_out.merge(
                    pd.DataFrame(nearest[["hex_id"] + cost_cols]), on="hex_id", how="left"
                )
                for g in selected:
                    col = f"nearest_cost_{g}_1"
                    if col not in df_out.columns:
                        df_out[col] = np.nan
                timings["nearest"] = time.perf_counter() - t0
                nearest_ran = True
                rep.done("nearest", timings["nearest"], f"{len(cost_cols)} categorieën")
            except Exception as exc:
                timings["nearest"] = time.perf_counter() - t0
                warn(f"Dichtstbijzijnde voorziening berekenen mislukt ({exc}).")
                rep.skip("nearest", detail="mislukt")
        else:
            rep.skip("nearest", detail="geen voorzieningen")
    else:
        rep.skip("nearest")

    # --- Stage: hansen ------------------------------------------------------
    if "hansen" in analyses:
        if have_pois:
            rep.start("hansen")
            t0 = time.perf_counter()
            try:
                hansen = acx.compute_hansen_accessibility(
                    graph, hexes_m, pois_m, max_cost=max_minutes,
                    cost_attr="time_min", beta=beta,
                )
                hansen_cols = [c for c in hansen.columns if c.startswith("hansen_")]
                df_out = df_out.merge(
                    pd.DataFrame(hansen[["hex_id"] + hansen_cols]), on="hex_id", how="left"
                )
                for g in selected:
                    col = f"hansen_{g}"
                    if col not in df_out.columns:
                        df_out[col] = 0.0
                if "hansen_total" not in df_out.columns:
                    df_out["hansen_total"] = 0.0
                timings["hansen"] = time.perf_counter() - t0
                rep.done("hansen", timings["hansen"], f"beta={beta:g}")
            except Exception as exc:
                timings["hansen"] = time.perf_counter() - t0
                warn(f"Hansen-bereikbaarheid berekenen mislukt ({exc}).")
                rep.skip("hansen", detail="mislukt")
        else:
            rep.skip("hansen", detail="geen voorzieningen")
    else:
        rep.skip("hansen")

    # --- Stage: sfca --------------------------------------------------------
    if "2sfca" in analyses:
        if have_pois and has_pop:
            rep.start("sfca")
            t0 = time.perf_counter()
            try:
                hexes_pop_m = hexes_m.merge(
                    pd.DataFrame(df_out[["hex_id", "population"]]), on="hex_id", how="left"
                )
                hexes_pop_m["population"] = hexes_pop_m["population"].fillna(0.0)
                sfca = acx.compute_2sfca_accessibility(
                    graph, hexes_pop_m, pois_m, max_cost=max_minutes,
                    cost_attr="time_min", demand_col="population",
                    decay=sfca_decay, beta=beta,
                )
                sfca_cols = [c for c in sfca.columns if c.startswith("sfca_")]
                df_out = df_out.merge(
                    pd.DataFrame(sfca[["hex_id"] + sfca_cols]), on="hex_id", how="left"
                )
                for g in selected:
                    col = f"sfca_{g}"
                    if col not in df_out.columns:
                        df_out[col] = 0.0
                if "sfca_total" not in df_out.columns:
                    df_out["sfca_total"] = 0.0
                timings["sfca"] = time.perf_counter() - t0
                rep.done("sfca", timings["sfca"], f"decay={sfca_decay}")
            except Exception as exc:
                timings["sfca"] = time.perf_counter() - t0
                warn(f"2SFCA berekenen mislukt ({exc}).")
                rep.skip("sfca", detail="mislukt")
        else:
            reason = "geen voorzieningen" if not have_pois else "geen bevolking"
            if have_pois and not has_pop:
                warn("2SFCA overgeslagen: geen bevolking in het gebied.")
            rep.skip("sfca", detail=reason)
    else:
        rep.skip("sfca")

    # --- Stage: equity ------------------------------------------------------
    equity_payload: Dict[str, Any] = {"gini": {}, "gini_weighted": False, "lorenz": {}}
    if "equity" in analyses:
        if counts_ran:
            rep.start("equity")
            t0 = time.perf_counter()
            try:
                plain = pd.DataFrame(df_out.drop(columns="geometry"))
                props_all = [g for g in (f"count_{x}" for x in selected) if g in plain.columns]
                weights = "population" if has_pop else None
                A, P, gini, _sorted_vals = acx.calculate_lorenz(
                    props_all, plain, weights=weights
                )
                lorenz_out = {
                    prop: {"P": _subsample(P[prop]), "A": _subsample(A[prop])}
                    for prop in props_all[:3]
                }
                equity_payload = {
                    "gini": {k: v for k, v in gini.items()},
                    "gini_weighted": bool(has_pop),
                    "lorenz": lorenz_out,
                }

                # Sufficiency thresholds: count_<g> >= 1 per selected group, plus
                # nearest_cost_<first group>_1 <= max_minutes when nearest ran.
                thresholds_ge = {f"count_{g}": 1 for g in selected}
                thresholds_le: Dict[str, float] = {}
                suff_input = plain.copy()
                if nearest_ran and selected:
                    near_col = f"nearest_cost_{selected[0]}_1"
                    if near_col in suff_input.columns:
                        thresholds_le[near_col] = max_minutes
                        # Unreachable (NaN) must not pass the <=-threshold via fillna(0).
                        suff_input[near_col] = suff_input[near_col].fillna(1e9)
                suff = acx.compute_sufficientarian_score(
                    suff_input,
                    thresholds_ge=thresholds_ge,
                    thresholds_le=thresholds_le or None,
                )
                suff_cols = [
                    c
                    for c in suff.columns
                    if c == "sufficient_score" or c.endswith("_sufficient")
                ]
                df_out = df_out.merge(
                    suff[["hex_id"] + suff_cols], on="hex_id", how="left"
                )
                timings["equity"] = time.perf_counter() - t0
                rep.done(
                    "equity", timings["equity"], f"Gini over {len(props_all)} metrieken"
                )
            except Exception as exc:
                timings["equity"] = time.perf_counter() - t0
                warn(f"Verdeling & Gini berekenen mislukt ({exc}).")
                rep.skip("equity", detail="mislukt")
        else:
            if "counts" in analyses:
                detail = "geen voorzieningen"
            else:
                detail = "vereist analyse 'counts'"
                warn("Verdeling & Gini overgeslagen: vereist de analyse 'counts'.")
            rep.skip("equity", detail=detail)
    else:
        rep.skip("equity")

    # --- Assemble result ----------------------------------------------------
    hexes_fc = gdf_to_feature_collection(df_out)

    if have_pois:
        keep = [c for c in ("id", "category", "name") if c in pois_m.columns]
        pois_pts = pois_m[keep].copy()
        if "name" not in pois_pts.columns:
            pois_pts["name"] = None
        pois_pts = gpd.GeoDataFrame(
            pois_pts, geometry=pois_m.geometry.centroid, crs=METRIC_EPSG
        ).to_crs(4326)
        pois_fc = gdf_to_feature_collection(pois_pts)
    else:
        pois_fc = {"type": "FeatureCollection", "features": []}

    meta = {
        "params": params.get("request_echo", {}),
        "area_km2": round(area_km2, 2),
        "n_hexes": int(len(df_out)),
        "n_pois": n_pois,
        "population_total": population_total,
        "population_cols": CBS_COLS if pop_out_cols else [],
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "warnings": list(warnings_list),
    }

    result = sanitize_json(
        {"hexes": hexes_fc, "pois": pois_fc, "equity": equity_payload, "meta": meta}
    )
    return {"result": result, "graph": graph, "hexes_m": hexes_m}


# ---------------------------------------------------------------------------
# Isochrones (on demand, after a job is done)
# ---------------------------------------------------------------------------

def compute_isochrone_rings(
    graph: Any,
    hexes_m: gpd.GeoDataFrame,
    hex_id: str,
    max_minutes: float,
    interval: Optional[float] = None,
) -> dict:
    """Compute isochrone rings from a single hex. Raises KeyError for unknown hex_id.

    Returns {"hex_id": ..., "rings": FeatureCollection} with per-feature property
    "threshold" (minutes), sorted large -> small so small rings render on top.
    """
    sel = hexes_m[hexes_m["hex_id"] == hex_id]
    if len(sel) == 0:
        raise KeyError(hex_id)
    graph_crs = graph.graph.get("crs", METRIC_EPSG)
    sel = sel.to_crs(graph_crs)
    iso = acx.calculate_isochrones(
        graph,
        sel,
        max_cost=max_minutes,
        interval_size=interval,
        cost_attr="time_min",
        city_epsg=METRIC_EPSG,
        method="edges",
    )
    row = iso.iloc[0]
    prefix = "geom_time_min_"
    thr_geoms = []
    for col in iso.columns:
        if not col.startswith(prefix):
            continue
        geom = row[col]
        if geom is None or (hasattr(geom, "is_empty") and geom.is_empty):
            continue
        threshold = float(col[len(prefix):].replace("p", "."))
        thr_geoms.append((threshold, geom))
    thr_geoms.sort(key=lambda item: -item[0])

    features = []
    for threshold, geom in thr_geoms:
        geom_4326 = gpd.GeoSeries([geom], crs=iso.crs).to_crs(4326).iloc[0]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "threshold": int(threshold)
                    if float(threshold).is_integer()
                    else threshold
                },
                "geometry": mapping(geom_4326),
            }
        )
    rings = {"type": "FeatureCollection", "features": features}
    return sanitize_json({"hex_id": hex_id, "rings": rings})
