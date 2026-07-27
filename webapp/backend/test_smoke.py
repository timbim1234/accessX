"""Smoke test voor de backend (geen pytest nodig).

Draai vanuit deze map:
    C:/Users/tim/.venvs/accessx/Scripts/python.exe test_smoke.py

Checkt: health, presets, validaties (buiten NL, te groot), 202-flow met een
piepkleine polygoon, jobstatus, en JSON-sanitatie (NaN/inf -> null).
De gestarte job wordt NIET tot 'done' gepolld (kan netwerk vereisen).
"""
from __future__ import annotations

import json
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, shape

import analysis
import local_osm
from main import app

from fastapi.testclient import TestClient

FAILURES: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    status = "OK  " if cond else "FAIL"
    line = f"{status} {name}"
    if extra:
        line += f" — {extra}"
    print(line)
    if not cond:
        FAILURES.append(name)


def square(lon: float, lat: float, dlon: float, dlat: float) -> dict:
    """GeoJSON Polygon rond (lon, lat) met halve breedte dlon/dlat."""
    return {
        "type": "Polygon",
        "coordinates": [[
            [lon - dlon, lat - dlat],
            [lon + dlon, lat - dlat],
            [lon + dlon, lat + dlat],
            [lon - dlon, lat + dlat],
            [lon - dlon, lat - dlat],
        ]],
    }


def main() -> int:
    # --- JSON-sanitatie -----------------------------------------------------
    sanitized = analysis.sanitize_json(
        {"a": float("nan"), "b": [1.0, float("inf")], "c": {"d": float("-inf")}}
    )
    check(
        "sanitize_json: NaN/inf -> null",
        sanitized == {"a": None, "b": [1.0, None], "c": {"d": None}},
        repr(sanitized),
    )

    # Expliciet met een (Geo)DataFrame met NaN én inf, zoals in de spec gevraagd.
    gdf = gpd.GeoDataFrame(
        {
            "hex_id": ["a", "b"],
            "x": [1.5, np.nan],
            "y": [np.inf, -np.inf],
            "lst": [[1], [2]],
        },
        geometry=[Point(4.9, 52.37), Point(4.91, 52.37)],
        crs=4326,
    )
    fc = analysis.gdf_to_feature_collection(gdf)
    props = [f["properties"] for f in fc["features"]]
    strict = json.dumps(fc)  # strikte JSON mag geen NaN/Infinity-literals bevatten
    check(
        "gdf_to_feature_collection: NaN/inf -> null, list-kolom gedropt",
        props[0].get("x") == 1.5
        and props[1].get("x") is None
        and props[0].get("y") is None
        and props[1].get("y") is None
        and all("lst" not in p for p in props)
        and "NaN" not in strict
        and "Infinity" not in strict,
        repr(props),
    )

    # Zelfdoorsnijdende polygoon (bowtie): validatie én pipeline moeten dezelfde
    # gerepareerde geometrie gebruiken (buffer(0)); rauwe invalid geometrie
    # crashte eerder in make_hex_grid met een TopologyException.
    bowtie = {
        "type": "Polygon",
        "coordinates": [[
            [4.90, 52.360], [4.92, 52.372], [4.90, 52.372],
            [4.92, 52.360], [4.90, 52.360],
        ]],
    }
    repaired = analysis.repair_geometry(shape(bowtie))
    check(
        "repair_geometry: bowtie -> valide geometrie met oppervlak",
        repaired.is_valid and repaired.area > 0,
        f"is_valid={repaired.is_valid}, area={repaired.area:.6g}",
    )

    # --- lokale OSM-extract -------------------------------------------------
    avail = local_osm.local_data_available()
    check(
        "local_osm.local_data_available() -> bool",
        isinstance(avail, bool),
        f"available={avail}",
    )
    if avail:
        # Mini-bbox binnen provincie Utrecht (Utrecht-West).
        mini = square(5.085, 52.0925, 0.005, 0.0025)
        aoi_buf = gpd.GeoDataFrame(geometry=[shape(mini)], crs=4326)
        try:
            pois = local_osm.load_pois_local(
                aoi_buf,
                ["daily_needs", "healthcare", "education",
                 "open_space", "public_transport"],
            )
            cols_ok = {"id", "name", "category"}.issubset(set(pois.columns))
            crs_ok = pois.crs is not None and str(pois.crs).endswith("4326")
            check(
                "load_pois_local: GeoDataFrame met juiste kolommen (Utrecht-mini)",
                isinstance(pois, gpd.GeoDataFrame) and cols_ok and crs_ok,
                f"n={len(pois)}, cols={list(pois.columns)}, crs={pois.crs}",
            )
        except Exception as exc:  # noqa: BLE001
            check("load_pois_local: geen fout", False, repr(exc))
    else:
        print("SKIP local_osm data-checks — geen lokale data aanwezig")

    with TestClient(app) as client:
        # --- health ---------------------------------------------------------
        r = client.get("/api/health")
        body = r.json() if r.status_code == 200 else {}
        check(
            "GET /api/health -> 200 + accessx_version",
            r.status_code == 200
            and body.get("status") == "ok"
            and bool(body.get("accessx_version")),
            f"status={r.status_code}, body={body}",
        )

        # --- presets --------------------------------------------------------
        r = client.get("/api/presets")
        body = r.json() if r.status_code == 200 else {}
        check(
            "GET /api/presets -> 200 + verwachte keys",
            r.status_code == 200
            and set(body) >= {"poi_groups", "defaults", "limits"}
            and "daily_needs" in body.get("poi_groups", {})
            and body.get("limits", {}).get("max_area_km2") == 100,
            f"status={r.status_code}",
        )

        # --- polygoon buiten NL -> 400 ---------------------------------------
        r = client.post(
            "/api/analyze",
            json={"polygon": square(2.35, 48.85, 0.01, 0.01),  # Parijs
                  "poi_groups": ["daily_needs"]},
        )
        check(
            "POST /api/analyze buiten NL -> 400",
            r.status_code == 400,
            f"status={r.status_code}, detail={r.json().get('detail', '')!r}",
        )

        # --- te groot oppervlak (zo'n beetje heel NL) -> 400 ------------------
        r = client.post(
            "/api/analyze",
            json={"polygon": square(5.25, 52.15, 1.9, 1.3),
                  "poi_groups": ["daily_needs"]},
        )
        check(
            "POST /api/analyze te groot -> 400",
            r.status_code == 400,
            f"status={r.status_code}, detail={r.json().get('detail', '')!r}",
        )

        # --- minimale payload, piepkleine polygoon (~100x100 m) -> 202 --------
        tiny = square(4.9041, 52.3676, 0.00075, 0.00045)  # Amsterdam centrum
        r = client.post(
            "/api/analyze",
            json={"polygon": tiny, "poi_groups": ["daily_needs"],
                  "analyses": ["counts"]},
        )
        body = r.json() if r.status_code == 202 else {}
        job_id = body.get("job_id")
        check(
            "POST /api/analyze piepklein -> 202 + job_id",
            r.status_code == 202 and bool(job_id),
            f"status={r.status_code}, body={body}",
        )

        # --- jobstatus onmiddellijk opvraagbaar -------------------------------
        if job_id:
            r = client.get(f"/api/jobs/{job_id}")
            body = r.json() if r.status_code == 200 else {}
            check(
                "GET /api/jobs/{id} -> 200 + geldige status + 10 stages",
                r.status_code == 200
                and body.get("status") in {"queued", "running", "done", "error"}
                and len(body.get("stages", [])) == 10,
                f"status={r.status_code}, jobstatus={body.get('status')!r}",
            )
            # Resultaat/uitkomst van de job zelf is hier NIET relevant (kan
            # falen door netwerk); we testen alleen de flow. Niet pollen.

        # --- onbekende job -> 404 --------------------------------------------
        r = client.get("/api/jobs/bestaatniet123")
        check("GET /api/jobs/<onbekend> -> 404", r.status_code == 404,
              f"status={r.status_code}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) GEFAALD: {', '.join(FAILURES)}")
        return 1
    print("Alle checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
