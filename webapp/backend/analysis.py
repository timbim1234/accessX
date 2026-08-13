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
import shapely
from shapely.geometry import Point, mapping, shape

import accessx as acx

import bag
import local_osm
import poi_groups as pg

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


def point_in_nl(lon: float, lat: float) -> bool:
    """Ligt dit punt binnen de NL-bounding box? Grove check, geen landsgrens."""
    lon_min, lat_min, lon_max, lat_max = NL_BBOX
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max
MAX_BUFFER_M = 2500.0

# ---------------------------------------------------------------------------
# Presets (see CONTRACT.md)
# ---------------------------------------------------------------------------

# Categorieen en de tag-matcher staan in poi_groups.py, zodat de pbf-prep
# (prepare_local_data.py) exact dezelfde definities gebruikt zonder de zware
# geopandas/osmnx-stack te importeren.
POI_GROUPS: Dict[str, Dict[str, Any]] = pg.POI_GROUPS
SECTIONS: List[Dict[str, str]] = pg.SECTIONS

DEFAULTS: Dict[str, Any] = {
    "mode": "walk",
    "speed_kmh": 4.5,
    "max_minutes": 15,
    "hex_resolution": 9,
    "selected_groups": list(pg.DEFAULT_SELECTED),
    "analyses": [
        "counts", "nearest", "hansen", "population", "2sfca", "equity", "bvo",
        "groen300",
    ],
}

LIMITS: Dict[str, Any] = {"max_area_km2": 250, "warn_area_km2": 40}

# Een BAG-vloeroppervlakte boven dit veelvoud van de categoriemediaan telt als
# uitschieter: meestal een compleet complex dat als één verblijfsobject is
# geregistreerd. Wordt gerapporteerd, niet weggefilterd.
BVO_OUTLIER_FACTOR = 10.0

# --- 300 m-norm voor groen (3-30-300) ---------------------------------------
# De norm: iedere woning binnen 300 m van een park of groengebied. Gemeten als
# loopafstand over het netwerk naar de RAND van het groen -- niet hemelsbreed en
# niet naar het middelpunt. Bij een park van 20 ha ligt de centroide honderden
# meters van de ingang; dan meet je iets anders dan de norm bedoelt.
GREEN_DISTANCE_M = 300.0
#: Ondergrens oppervlakte: een berm is geen park. 0,5 ha is gangbaar.
GREEN_MIN_AREA_M2 = 5_000.0
#: Om de hoeveel meter een punt op de rand van een groenvlak wordt gezet. Die
#: punten zijn de "ingangen" waarnaar de loopafstand wordt gemeten.
GREEN_EDGE_STEP_M = 25.0
#: Plafond per vlak, zodat een bos van 500 ha niet duizenden punten oplevert.
GREEN_MAX_POINTS_PER_AREA = 200
#: Zoekvenster: verder dan dit hoeft niet gemeten te worden voor een 300 m-norm.
GREEN_MAX_SEARCH_M = 1_500.0

ANALYSIS_KEYS = [
    "counts", "nearest", "hansen", "population", "2sfca", "equity", "bvo",
    "groen300",
]

# Ordered stage definitions (key, Dutch label).
STAGES: List[Tuple[str, str]] = [
    ("hexgrid", "H3-hexgrid genereren"),
    ("network", "Straatnetwerk (OSM) laden"),
    ("cost", "Reistijdkosten toekennen"),
    ("pois", "Voorzieningen (OSM) ophalen"),
    ("bag", "Vloeroppervlakte (BAG) koppelen"),
    ("population", "CBS-bevolking koppelen"),
    ("counts", "Bereikbare voorzieningen tellen"),
    ("nearest", "Dichtstbijzijnde voorziening"),
    ("hansen", "Hansen-bereikbaarheid"),
    ("sfca", "2SFCA (vraag/aanbod)"),
    ("groen300", "Groen binnen 300 m"),
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
    if not (point_in_nl(minx, miny) and point_in_nl(maxx, maxy)):
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


def _matches_tags(features: gpd.GeoDataFrame, spec: Dict[str, Any]) -> pd.Series:
    """Boolean mask for a poi_groups match-spec, vectorized over a GeoDataFrame.

    Mirrors poi_groups.matches() exactly (any/all/not + leaf), so the Overpass
    path and the local-extract path categorize identically. A key that OSMnx
    did not return as a column yields an all-False leaf, which is correct: no
    feature can carry a tag that is absent from the response.
    """
    if "any" in spec:
        mask = pd.Series(False, index=features.index)
        for sub in spec["any"]:
            mask |= _matches_tags(features, sub)
        return mask
    if "all" in spec:
        mask = pd.Series(True, index=features.index)
        for sub in spec["all"]:
            mask &= _matches_tags(features, sub)
        return mask
    if "not" in spec:
        return ~_matches_tags(features, spec["not"])

    mask = pd.Series(False, index=features.index)
    for key, values in spec.items():
        if key not in features.columns:
            continue
        col = features[key]
        if values is True:
            mask |= col.notna()
        else:
            vals = [values] if isinstance(values, str) else list(values)
            mask |= col.isin(vals)
    return mask


def green_entry_points(green_m: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Punten op de rand van elk groenvlak, als 'ingangen' voor de 300 m-norm.

    De afstand tot een park hoort te worden gemeten tot waar je het binnengaat.
    Door de omtrek te bemonsteren en die punten als voorziening aan te bieden,
    rekent de bestaande routeerfunctie precies dat uit: de loopafstand tot het
    dichtstbijzijnde punt op de rand.

    `green_m` moet in een metrisch CRS staan (stappen zijn in meters).
    """
    xs: List[float] = []
    ys: List[float] = []
    for geom in green_m.geometry:
        if geom is None or geom.is_empty:
            continue
        rings = []
        if geom.geom_type == "Polygon":
            rings = [geom.exterior]
        elif geom.geom_type == "MultiPolygon":
            rings = [g.exterior for g in geom.geoms]
        for ring in rings:
            omtrek = float(ring.length)
            if omtrek <= 0:
                continue
            n = int(min(GREEN_MAX_POINTS_PER_AREA, max(4, omtrek // GREEN_EDGE_STEP_M)))
            for t in np.linspace(0.0, omtrek, n, endpoint=False):
                p = ring.interpolate(float(t))
                xs.append(p.x)
                ys.append(p.y)
    if not xs:
        return gpd.GeoDataFrame(
            {"id": [], "category": []}, geometry=[], crs=green_m.crs
        )
    return gpd.GeoDataFrame(
        {"id": [f"green/{i}" for i in range(len(xs))], "category": ["groen"] * len(xs)},
        geometry=gpd.points_from_xy(xs, ys),
        crs=green_m.crs,
    )


def _dedup_point_in_area(part: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Drop area features of one category that contain a point of that category.

    A school is often mapped twice: as a node AND as the building/grounds
    polygon. Both match the same category, so counts and 2SFCA supply are
    inflated (measured on the NL extract: 28% of school nodes sit inside a
    school area). The node is the more precise representation, so the
    enclosing area is dropped. Points are never merged with each other -- two
    GPs in one building are genuinely two facilities.
    """
    if len(part) < 2:
        return part
    is_point = part.geometry.geom_type == "Point"
    pts = part.geometry[is_point]
    areas = part.geometry[~is_point]
    if len(pts) == 0 or len(areas) == 0:
        return part
    tree = shapely.STRtree(pts.to_numpy())
    area_arr = areas.to_numpy()
    drop_positions = {
        i for i in range(len(area_arr))
        if len(tree.query(area_arr[i], predicate="contains")) > 0
    }
    if not drop_positions:
        return part
    drop_index = areas.index[sorted(drop_positions)]
    return part.drop(index=drop_index)


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
    merged = pg.query_tags(selected)
    try:
        feats = ox.features_from_polygon(polygon, tags=merged)
    except Exception as exc:
        if type(exc).__name__ == "InsufficientResponseError":
            return _empty_pois()
        raise
    return categorize_features(feats, selected)


def _empty_pois() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"id": [], "name": [], "category": []}, geometry=[], crs=4326)


def categorize_features(
    feats: gpd.GeoDataFrame, selected: List[str]
) -> gpd.GeoDataFrame:
    """Assign categories to raw OSM features and reduce them to points.

    Shared by the combined-query path and the accessx fallback so both apply
    the same match-specs, the same node/area dedup and the same point output
    as the local-extract path (local_osm.load_pois_local).
    """
    if feats is None or len(feats) == 0:
        return _empty_pois()

    feats = feats[feats.geometry.geom_type.isin(["Point", "Polygon", "MultiPolygon"])]
    if len(feats) == 0:
        return _empty_pois()

    feats = feats.reset_index()
    # osmnx 2.x uses index levels (element, id); 1.x used (element_type, osmid).
    if "element" in feats.columns and "id" in feats.columns:
        osm_id = feats["element"].astype(str) + "/" + feats["id"].astype(str)
    elif "element_type" in feats.columns and "osmid" in feats.columns:
        osm_id = feats["element_type"].astype(str) + "/" + feats["osmid"].astype(str)
    elif "osm_type" in feats.columns and "osmid" in feats.columns:
        # accessx.get_pois_osm output (fallback path).
        osm_id = feats["osm_type"].astype(str) + "/" + feats["osmid"].astype(str)
    else:
        osm_id = pd.Series(range(len(feats)), index=feats.index).astype(str)
    feats = feats.assign(**{"__poi_id": osm_id})
    if "name" not in feats.columns:
        feats["name"] = None

    # Adreskolommen meenemen als OSM ze levert: bag.py koppelt de
    # vloeroppervlakte daar bij voorkeur op, in plaats van op afstand.
    addr_cols = [
        c
        for c in ("addr:street", "addr:housenumber", "addr:postcode")
        if c in feats.columns
    ]

    parts = []
    for group in selected:
        if group not in POI_GROUPS:
            continue
        sub = feats[_matches_tags(feats, POI_GROUPS[group]["match"])]
        if len(sub) == 0:
            continue
        part = sub[["__poi_id", "name", *addr_cols, "geometry"]].rename(
            columns={"__poi_id": "id"}
        )
        part = gpd.GeoDataFrame(part, geometry="geometry", crs=feats.crs)
        part = _dedup_point_in_area(part)
        part["category"] = group
        parts.append(part)
    if not parts:
        return _empty_pois()

    out = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), geometry="geometry", crs=4326
    )
    # Areas -> centroid, so downstream stages see one point per facility and
    # both POI sources (Overpass / local extract) behave identically.
    is_area = out.geometry.geom_type != "Point"
    if is_area.any():
        # shapely.centroid on the array, not GeoSeries.centroid: the latter
        # warns about centroids in a geographic CRS. The local extract does the
        # same planar centroid in WGS84, so this keeps both paths identical.
        out.loc[is_area, "geometry"] = shapely.centroid(
            out.loc[is_area, "geometry"].to_numpy()
        )
    return out


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
    need_pois = bool({"counts", "nearest", "hansen", "2sfca", "bvo"} & analyses)
    need_pop = ("population" in analyses) or ("2sfca" in analyses)
    need_bvo = "bvo" in analyses

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
                stale = local_osm.missing_categories(selected)
                if stale:
                    warn(
                        "De lokale OSM-extract is voorbereid zonder de categorie(en) "
                        f"{', '.join(stale)}; terugval op Overpass. Draai "
                        "prepare_local_data.py opnieuw om dit te verhelpen."
                    )
                else:
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
                    # One query per OSM key instead of one combined query, then
                    # the same local categorization: get_pois_osm cannot express
                    # the any/all/not specs itself, so it only fetches the
                    # superset (columns="all" keeps the tag columns we match on).
                    raw = acx.get_pois_osm(
                        aoi_buf,
                        osm_tags=pg.query_tags(selected),
                        show_progress=False,
                        columns="all",
                    )
                    p = categorize_features(raw, selected)
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
            if found and need_bvo:
                p = _attach_bvo(p)
            elif need_bvo:
                rep.skip("bag", detail="geen voorzieningen")
            else:
                rep.skip("bag")
            return p, found, per_group
        except Exception as exc:
            timings["pois"] = time.perf_counter() - t0
            warn(f"Voorzieningen ophalen mislukt ({exc}); afhankelijke analyses overgeslagen.")
            rep.skip("pois", detail="mislukt")
            rep.skip("bag", detail="geen voorzieningen")
            return None, False, {g: 0 for g in selected}

    def _attach_bvo(p: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Add BAG floor-area columns to the POIs. Never raises.

        Runs inside task_pois so the PDOK round-trip overlaps with the network
        build. On failure the POIs come back unchanged and every m2-metric is
        simply absent -- the rest of the analysis is unaffected.
        """
        rep.start("bag")
        t0 = time.perf_counter()
        try:
            p = bag.attach_floor_area(p)
            timings["bag"] = time.perf_counter() - t0
            with_m2 = int(p["bvo_m2"].notna().sum())
            total_m2 = float(p["bvo_m2"].sum(skipna=True))
            rep.done(
                "bag",
                timings["bag"],
                f"{with_m2} van {len(p)} voorzieningen, {total_m2:,.0f} m² BVO".replace(
                    ",", "."
                ),
            )
        except bag.BagError as exc:
            timings["bag"] = time.perf_counter() - t0
            warn(f"{exc} De analyse draait door zonder vloeroppervlakte.")
            rep.skip("bag", detail="mislukt")
        except Exception as exc:
            timings["bag"] = time.perf_counter() - t0
            warn(
                f"Vloeroppervlakte (BAG) koppelen mislukt ({exc}); "
                "de analyse draait door zonder m²."
            )
            rep.skip("bag", detail="mislukt")
        return p

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

    # --- Scenario: merge fictitious ("what-if") POIs ------------------------
    # Extra POIs from a what-if request are concatenated into `pois` BEFORE the
    # metric reprojection, so they flow through counts/nearest/hansen/2sfca just
    # like real ones. They keep an id "scenario/<i>" so the frontend can tell
    # them apart, and are NOT added to meta.n_pois (which stays the OSM count).
    n_extra_pois = 0
    if params.get("extra_pois"):
        scenario_rows: List[dict] = []
        for i, item in enumerate(params.get("extra_pois") or []):
            if not isinstance(item, dict):
                continue
            category = item.get("category")
            if category not in selected:
                continue
            try:
                lon = float(item["lon"])
                lat = float(item["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            scenario_rows.append(
                {
                    "id": f"scenario/{i}",
                    "name": "Scenario",
                    "category": category,
                    "geometry": Point(lon, lat),
                }
            )
        if scenario_rows:
            scenario_gdf = gpd.GeoDataFrame(
                scenario_rows, geometry="geometry", crs=4326
            )
            n_extra_pois = len(scenario_gdf)
            if have_pois and pois is not None and len(pois) > 0:
                pois = gpd.GeoDataFrame(
                    pd.concat([pois, scenario_gdf], ignore_index=True),
                    geometry="geometry",
                    crs=4326,
                )
            else:
                pois = scenario_gdf
                have_pois = True

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

    # --- Bereikbaar vloeroppervlak (m2, afstandsgewogen) --------------------
    # Zelfde Hansen-formule als hierboven, maar elke voorziening telt mee voor
    # haar vloeroppervlak in plaats van als "1". Antwoord op "hoeveel m2
    # voorziening is er vanaf hier binnen bereik", waar count_<groep> alleen
    # "hoeveel stuks" zegt. Alleen categorieen met daadwerkelijk m2 doen mee --
    # een speeltuin heeft geen vloeroppervlak en zou een lege kolom opleveren.
    bvo_groups: List[str] = []
    if need_bvo and have_pois and "bvo_m2" in pois_m.columns:
        with_area = pois_m[pois_m["bvo_m2"].fillna(0) > 0]
        bvo_groups = [g for g in selected if g in set(with_area["category"])]
        if bvo_groups:
            t0 = time.perf_counter()
            try:
                hansen_bvo = acx.compute_hansen_accessibility(
                    graph,
                    hexes_m,
                    with_area,
                    max_cost=max_minutes,
                    cost_attr="time_min",
                    beta=beta,
                    poi_weight_col="bvo_m2",
                    default_poi_weight=0.0,
                )
                rename = {
                    f"hansen_{g}": f"bvo_hansen_{g}"
                    for g in bvo_groups
                    if f"hansen_{g}" in hansen_bvo.columns
                }
                keep_cols = ["hex_id"] + list(rename)
                df_out = df_out.merge(
                    pd.DataFrame(hansen_bvo[keep_cols]).rename(columns=rename),
                    on="hex_id",
                    how="left",
                )
                for g in bvo_groups:
                    col = f"bvo_hansen_{g}"
                    if col in df_out.columns:
                        df_out[col] = df_out[col].fillna(0.0)
                timings["bvo_hansen"] = time.perf_counter() - t0
            except Exception as exc:
                timings["bvo_hansen"] = time.perf_counter() - t0
                warn(f"Bereikbaar vloeroppervlak berekenen mislukt ({exc}).")
                bvo_groups = []

    # --- Stage: groen binnen 300 m (3-30-300) -------------------------------
    groen_payload: Optional[Dict[str, Any]] = None
    if "groen300" in analyses:
        rep.start("groen300")
        t0 = time.perf_counter()
        try:
            aoi_groen = aoi_m.copy()
            # Ruim zoeken: groen net buiten het gebied telt gewoon mee voor wie
            # aan de rand woont.
            aoi_groen["geometry"] = aoi_groen.buffer(GREEN_MAX_SEARCH_M)
            green = local_osm.load_green_local(
                aoi_groen.to_crs(4326), min_area_m2=GREEN_MIN_AREA_M2
            )
            if len(green) == 0:
                raise ValueError(
                    "geen groenvlakken in de lokale extract (draai "
                    "prepare_local_data.py --only groen)"
                )
            green_m = green.to_crs(METRIC_EPSG)
            entries = green_entry_points(green_m)
            if len(entries) == 0:
                raise ValueError("groenvlakken zonder bruikbare rand")

            near_groen = acx.compute_nearest_poi_cost(
                graph,
                hexes_m,
                entries,
                max_cost=GREEN_MAX_SEARCH_M,
                cost_attr="length",  # meters, niet minuten
                number_of_nearest=1,
                output="wide",
            )
            col = next(
                (c for c in near_groen.columns if c.startswith("nearest_cost_")), None
            )
            if col is None:
                raise ValueError("routeren naar groen leverde geen kolom op")
            df_out = df_out.merge(
                pd.DataFrame(near_groen[["hex_id", col]]).rename(
                    columns={col: "groen_afstand_m"}
                ),
                on="hex_id",
                how="left",
            )
            binnen = pd.to_numeric(df_out["groen_afstand_m"], errors="coerce")
            df_out["groen_binnen_300m"] = (binnen <= GREEN_DISTANCE_M).astype(int)

            # Bevolkingsgewogen aandeel: de norm gaat over inwoners, niet hexes.
            if has_pop and "population" in df_out.columns:
                w = pd.to_numeric(df_out["population"], errors="coerce").fillna(0.0)
            else:
                w = pd.Series(1.0, index=df_out.index)
            w_sum = float(w.sum())
            pct = (
                round(100.0 * float(w[df_out["groen_binnen_300m"] == 1].sum()) / w_sum, 1)
                if w_sum > 0
                else 0.0
            )
            mediaan = float(binnen.median()) if binnen.notna().any() else None
            groen_payload = {
                "norm_m": GREEN_DISTANCE_M,
                "min_area_m2": GREEN_MIN_AREA_M2,
                "pct_binnen_norm": pct,
                "gewogen": bool(has_pop),
                "mediaan_afstand_m": round(mediaan, 0) if mediaan is not None else None,
                "n_groenvlakken": int(len(green)),
                "groen_ha": round(float(green["area_m2"].sum()) / 10_000.0, 1),
                "buiten_bereik": int(binnen.isna().sum()),
            }
            timings["groen300"] = time.perf_counter() - t0
            rep.done(
                "groen300",
                timings["groen300"],
                f"{pct:.0f}% binnen {GREEN_DISTANCE_M:.0f} m, "
                f"{len(green)} groenvlakken",
            )
        except Exception as exc:
            timings["groen300"] = time.perf_counter() - t0
            warn(f"Groen binnen 300 m berekenen mislukt ({exc}).")
            rep.skip("groen300", detail="mislukt")
    else:
        rep.skip("groen300")

    # --- Stage: equity ------------------------------------------------------
    equity_payload: Dict[str, Any] = {"gini": {}, "gini_weighted": False, "lorenz": {}}
    equity_ran = False
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
                equity_ran = True
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

    # --- Summary: 15-minute-city KPI (only when counts ran) -----------------
    # Population-weighted when CBS population is available, otherwise per hex.
    summary: Optional[Dict[str, Any]] = None
    if counts_ran:
        plain_sum = pd.DataFrame(df_out.drop(columns="geometry"))
        n_hexes_sum = len(plain_sum)
        if has_pop and "population" in plain_sum.columns:
            weights = (
                pd.to_numeric(plain_sum["population"], errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype=float)
            )
        else:
            weights = np.ones(n_hexes_sum, dtype=float)
        weight_sum = float(weights.sum())

        def _weighted_pct(mask: np.ndarray) -> float:
            if weight_sum <= 0:
                return 0.0
            return round(100.0 * float(weights[mask].sum()) / weight_sum, 1)

        per_group_sum: List[Dict[str, Any]] = []
        for g in selected:
            col = f"count_{g}"
            if col not in plain_sum.columns:
                continue
            counts_arr = (
                pd.to_numeric(plain_sum[col], errors="coerce").fillna(0).to_numpy()
            )
            per_group_sum.append(
                {
                    "key": g,
                    "label": POI_GROUPS[g]["label"],
                    "pct": _weighted_pct(counts_arr >= 1),
                }
            )

        composite_pct: Optional[float] = None
        fully_served_pct: Optional[float] = None
        if equity_ran and "sufficient_score" in plain_sum.columns:
            suff_arr = (
                pd.to_numeric(plain_sum["sufficient_score"], errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype=float)
            )
            if weight_sum > 0:
                composite_pct = round(
                    100.0 * float((weights * suff_arr).sum()) / weight_sum, 1
                )
            else:
                composite_pct = 0.0
            fully_served_pct = _weighted_pct(suff_arr >= 1.0 - 1e-9)

        summary = {
            "weighted": bool(has_pop),
            "population_total": (
                round(float(population_total), 1)
                if (has_pop and population_total is not None)
                else float(n_hexes_sum)
            ),
            "max_minutes": (
                int(max_minutes) if float(max_minutes).is_integer() else max_minutes
            ),
            "per_group": per_group_sum,
            "composite_pct": composite_pct,
            "fully_served_pct": fully_served_pct,
        }

    # --- BAG floor area per category ----------------------------------------
    # `m2_totaal` telt gedeelde verblijfsobjecten precies een keer (bvo_m2 is
    # al aandeel-gecorrigeerd); `m2_mediaan` is de waarde per voorziening. `zeker_pct` zegt
    # welk deel is gekoppeld aan een verblijfsobject waarvan het gebruiksdoel
    # bij de categorie past -- de rest is alleen op afstand toegewezen.
    bvo_payload: Optional[Dict[str, Any]] = None
    if need_bvo and have_pois and "bvo_m2" in pois_m.columns:
        per_group_bvo: List[Dict[str, Any]] = []
        for g in selected:
            sub = pois_m[pois_m["category"] == g]
            if len(sub) == 0:
                continue
            has_m2 = sub["bvo_m2"].notna()
            vals = sub.loc[has_m2, "bvo_m2"]
            mediaan = float(vals.median()) if len(vals) else None
            # Grote complexen staan in de BAG soms als één verblijfsobject
            # (Hoog Catharijne: 94.598 m² GO). Zo'n registratie belandt bij de
            # ene voorziening die er toevallig in valt en domineert dan het
            # totaal. Daarom naast `m2_totaal` ook een uitschieterbestendige
            # schatting (aantal × mediaan) plus het aantal uitschieters, in
            # plaats van zulke objecten stilletjes weg te filteren.
            n_uitschieters = (
                int((vals > BVO_OUTLIER_FACTOR * mediaan).sum())
                if mediaan and mediaan > 0
                else 0
            )
            per_group_bvo.append(
                {
                    "key": g,
                    "label": POI_GROUPS[g]["label"],
                    "n": int(len(sub)),
                    "n_met_m2": int(has_m2.sum()),
                    "m2_totaal": round(float(sub["bvo_m2"].sum(skipna=True)), 0),
                    "m2_typisch": (
                        round(mediaan * len(vals), 0) if mediaan is not None else None
                    ),
                    "m2_mediaan": round(mediaan, 0) if mediaan is not None else None,
                    "n_uitschieters": n_uitschieters,
                    "zeker_pct": (
                        round(float(sub.loc[has_m2, "doel_match"].mean()) * 100, 1)
                        if has_m2.any()
                        else 0.0
                    ),
                    # Op adres gekoppeld = exact de geregistreerde unit; de rest
                    # is op ligging binnen het pand gekozen en dus een schatting.
                    "adres_pct": (
                        round(float(sub.loc[has_m2, "via_adres"].mean()) * 100, 1)
                        if has_m2.any() and "via_adres" in sub.columns
                        else 0.0
                    ),
                }
            )
        uniek = pois_m.drop_duplicates(subset="id") if "id" in pois_m.columns else pois_m
        bvo_payload = {
            "per_group": per_group_bvo,
            "m2_totaal": round(float(uniek["bvo_m2"].sum(skipna=True)), 0),
            "go_to_bvo": round(bag.GO_TO_BVO, 4),
            "hansen_groups": bvo_groups,
        }

    # --- Assemble result ----------------------------------------------------
    hexes_fc = gdf_to_feature_collection(df_out)

    if have_pois:
        keep = [
            c
            for c in ("id", "category", "name", "bvo_m2", "gebruiksdoel", "doel_match")
            if c in pois_m.columns
        ]
        pois_pts = pois_m[keep].copy()
        if "name" not in pois_pts.columns:
            pois_pts["name"] = None
        # Flag scenario POIs (id "scenario/<i>") so the frontend can render
        # them distinctly from real OSM POIs.
        if "id" in pois_pts.columns:
            pois_pts["scenario"] = (
                pois_pts["id"].astype(str).str.startswith("scenario/")
            )
        else:
            pois_pts["scenario"] = False
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
        "n_extra_pois": int(n_extra_pois),
        "scenario": bool(n_extra_pois > 0),
        "population_total": population_total,
        "population_cols": CBS_COLS if pop_out_cols else [],
        "timings_s": {k: round(v, 2) for k, v in timings.items()},
        "warnings": list(warnings_list),
    }

    result = sanitize_json(
        {
            "hexes": hexes_fc,
            "pois": pois_fc,
            "equity": equity_payload,
            "bvo": bvo_payload,
            "groen": groen_payload,
            "summary": summary,
            "meta": meta,
        }
    )
    return {"result": result, "graph": graph, "hexes_m": hexes_m}


# ---------------------------------------------------------------------------
# Isochrones (on demand, after a job is done)
# ---------------------------------------------------------------------------

def compute_isochrone_rings(
    graph: Any,
    hexes_m: gpd.GeoDataFrame,
    max_minutes: float,
    interval: Optional[float] = None,
    *,
    hex_id: Optional[str] = None,
    point: Optional[Tuple[float, float]] = None,
    label: Optional[str] = None,
) -> dict:
    """Isochroonringen vanaf een hex of vanaf een los punt (lon/lat in WGS84).

    Een voorziening is net zo goed een vertrekpunt als een hex: "wat ligt er
    binnen 15 minuten lopen vanaf déze school" is een andere vraag dan vanaf de
    hex eromheen, en accessx.calculate_isochrones accepteert punten net zo goed
    als vlakken.

    Raises KeyError voor een onbekende hex_id, ValueError als er geen bruikbare
    oorsprong is meegegeven.

    Returns {"origin": {...}, "rings": FeatureCollection} met per feature de
    property "threshold" (minuten), groot -> klein gesorteerd zodat de kleine
    ringen bovenop renderen.
    """
    graph_crs = graph.graph.get("crs", METRIC_EPSG)
    if hex_id is not None:
        sel = hexes_m[hexes_m["hex_id"] == hex_id]
        if len(sel) == 0:
            raise KeyError(hex_id)
        sel = sel.to_crs(graph_crs)
        origin = {"type": "hex", "hex_id": hex_id, "label": label}
    elif point is not None:
        lon, lat = point
        sel = gpd.GeoDataFrame(
            {"hex_id": ["punt"]}, geometry=[Point(float(lon), float(lat))], crs=4326
        ).to_crs(graph_crs)
        origin = {
            "type": "punt",
            "lon": float(lon),
            "lat": float(lat),
            "label": label,
        }
    else:
        raise ValueError("Geef een hex_id of een punt (lon/lat) als vertrekpunt.")
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
    # hex_id blijft als losse sleutel staan voor bestaande frontend-code.
    return sanitize_json({"hex_id": hex_id, "origin": origin, "rings": rings})
