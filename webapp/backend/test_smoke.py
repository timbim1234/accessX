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
import bag
import poi_groups as pg
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


def _pipeline_params(polygon: dict, **overrides) -> dict:
    """Build a params dict for a direct analysis.run_pipeline() call."""
    body = {
        "polygon": polygon,
        "mode": "walk",
        "speed_kmh": 4.5,
        "max_minutes": 15,
        "hex_resolution": 9,
        "poi_groups": list(analysis.DEFAULTS["selected_groups"]),
        "analyses": list(analysis.DEFAULTS["analyses"]),
        "beta": 0.15,
        "sfca_decay": "exp",
        "extra_pois": [],
    }
    body.update(overrides)
    geom = analysis.extract_geometry(body["polygon"])
    return {**body, "polygon_geom": geom, "request_echo": body}


def _sum_count(result: dict, group: str) -> int:
    """Sum count_<group> over all hex features (0 if the column is absent)."""
    col = f"count_{group}"
    total = 0
    for feat in result.get("hexes", {}).get("features", []):
        val = feat.get("properties", {}).get(col)
        if isinstance(val, (int, float)):
            total += int(val)
    return total


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

    # --- poi_groups: tag-matcher --------------------------------------------
    # De categorie wordt in pois.parquet gebakken, dus de matcher moet exact
    # doen wat de specs beloven. Let vooral op zwembad (particuliere tuinbaden
    # eruit) en het onderscheid basis- / voortgezet onderwijs.
    matcher_cases = [
        ({"shop": "bakery"}, {"detailhandel_kls", "daily_needs"}),
        ({"shop": "supermarket"}, {"detailhandel_grs", "daily_needs"}),
        ({"shop": "vacant"}, set()),
        ({"amenity": "school", "isced:level": "0;1"}, {"basis_onderwijs"}),
        ({"amenity": "school", "school": "secondary"}, {"voortgezet_onderwijs"}),
        ({"amenity": "school"}, {"onderwijs_overig"}),
        ({"leisure": "swimming_pool"}, set()),
        ({"leisure": "swimming_pool", "access": "private"}, set()),
        ({"leisure": "sports_centre", "sport": "swimming"}, {"sporthal", "zwembad"}),
        ({"leisure": "playground", "access": "private"}, set()),
        ({"healthcare": "physiotherapist"}, {"sociaal_medisch"}),
        ({"landuse": "forest"}, set()),
    ]
    wrong = [
        (tags, sorted(pg.match_groups(tags)), sorted(want))
        for tags, want in matcher_cases
        if set(pg.match_groups(tags)) != want
    ]
    check(
        f"poi_groups.match_groups: {len(matcher_cases)} tag-cases",
        not wrong,
        "" if not wrong else f"afwijkend: {wrong}",
    )

    # Pariteit scalair (prep-pad) vs. gevectoriseerd (Overpass-pad). Deze twee
    # moeten identiek beslissen: de een bakt de categorie in pois.parquet, de
    # ander bepaalt hem live uit de Overpass-respons.
    tag_rows = [tags for tags, _ in matcher_cases]
    tag_keys = sorted({k for t in tag_rows for k in t})
    frame = gpd.GeoDataFrame(
        {k: [t.get(k) for t in tag_rows] for k in tag_keys},
        geometry=[Point(0, 0)] * len(tag_rows),
        crs=4326,
    )
    mismatch = []
    for group, spec in analysis.POI_GROUPS.items():
        vec = analysis._matches_tags(frame, spec["match"]).tolist()
        sca = [group in pg.match_groups(t) for t in tag_rows]
        if vec != sca:
            mismatch.append((group, vec, sca))
    check(
        "matcher-pariteit: _matches_tags (vectorized) == match_groups (scalair)",
        not mismatch,
        "" if not mismatch else f"verschil in {[m[0] for m in mismatch]}",
    )

    # De Overpass-query moet een superset zijn: elke key uit een leaf-spec zit
    # erin, en negaties/AND-vervolgvoorwaarden verbreden hem niet (access mag
    # er bijvoorbeeld niet in staan, dat zou elk pad ophalen).
    qt = pg.query_tags(list(analysis.POI_GROUPS))
    check(
        "poi_groups.query_tags: superset zonder verbredende keys",
        "access" not in qt and qt.get("shop") is True and "amenity" in qt,
        f"keys={sorted(qt)}",
    )

    # --- bag: verblijfsobjecten filteren (offline) --------------------------
    # 1 m² is in de BAG de placeholder voor "oppervlakte onbekend"; die mag geen
    # voorziening worden. Puur woonfunctie hoort er ook niet in.
    def _vbo(opp, doel, **extra):
        props = {"identificatie": f"v{opp}", "pandidentificatie": "p1",
                 "oppervlakte": opp, "gebruiksdoel": doel}
        props.update(extra)
        return {"properties": props,
                "geometry": {"type": "Point", "coordinates": [134000.0, 455000.0]}}

    frame = bag._vbo_frame([
        _vbo(1, "winkelfunctie"),
        _vbo(8, "winkelfunctie"),
        _vbo(95, "winkelfunctie", postcode="3531 CS", openbare_ruimte="Kanaalstraat",
             huisnummer=45, huisletter="a"),
        _vbo(120, "woonfunctie"),
        _vbo(140, "winkelfunctie,woonfunctie"),
    ])
    opps = sorted(frame["go_m2"].tolist())
    check(
        "bag._vbo_frame: 1 m²-placeholders en pure woonfunctie eruit",
        opps == [95.0, 140.0],
        f"overgebleven oppervlakten={opps}",
    )
    check(
        "bag._vbo_frame: adres genormaliseerd + specificiteit geteld",
        frame.iloc[0]["postcode"] == "3531CS"
        and frame.iloc[0]["straat"] == "kanaalstraat"
        and frame.iloc[0]["huisletter"] == "A"
        and frame.iloc[0]["n_doelen"] == 1
        and frame.iloc[1]["n_doelen"] == 2,
        f"postcode={frame.iloc[0]['postcode']!r}, "
        f"n_doelen={frame['n_doelen'].tolist()}",
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
                ["daily_needs", "sociaal_medisch", "basis_onderwijs",
                 "parken_natuur", "public_transport"],
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

        # --- run_pipeline met bvo: BAG-koppeling (vereist netwerk) ----------
        # Contract van result["bvo"] controleren. Is PDOK onbereikbaar, dan
        # hoort de pipeline dóór te draaien met een waarschuwing i.p.v. te
        # falen -- ook dat is hier een geldige uitkomst.
        try:
            bvo_res = analysis.run_pipeline(
                _pipeline_params(
                    square(5.104, 52.0905, 0.002, 0.001),
                    poi_groups=["detailhandel_kls", "restaurant", "speeltuinen"],
                    analyses=["counts", "bvo"],
                )
            )["result"]
            payload = bvo_res.get("bvo")
            if payload is None:
                check(
                    "run_pipeline bvo: pipeline draait door zonder BAG",
                    any("BAG" in w or "vloeroppervlakte" in w.lower()
                        for w in bvo_res["meta"]["warnings"]),
                    f"warnings={bvo_res['meta']['warnings']}",
                )
            else:
                groups = {g["key"]: g for g in payload["per_group"]}
                # Buitenruimte hoort geen vloeroppervlakte te krijgen; dat is de
                # kern van de pand-poort in bag.attach_floor_area.
                buiten_leeg = groups.get("speeltuinen", {}).get("n_met_m2", 0) == 0
                gebouw_gevuld = groups.get("detailhandel_kls", {}).get("n_met_m2", 0) > 0
                check(
                    "run_pipeline bvo: m² voor gebouwen, geen m² voor buitenruimte",
                    {"per_group", "m2_totaal", "go_to_bvo"} <= set(payload)
                    and buiten_leeg
                    and gebouw_gevuld,
                    f"totaal={payload.get('m2_totaal')}, "
                    f"winkels={groups.get('detailhandel_kls', {}).get('n_met_m2')}, "
                    f"speeltuinen={groups.get('speeltuinen', {}).get('n_met_m2')}",
                )
                poi_props = [f["properties"] for f in bvo_res["pois"]["features"]]
                check(
                    "run_pipeline bvo: POI-laag draagt bvo_m2 + doel_match",
                    any(p.get("bvo_m2") for p in poi_props)
                    and all("doel_match" in p for p in poi_props),
                    f"{sum(1 for p in poi_props if p.get('bvo_m2'))}/{len(poi_props)} met m²",
                )
        except Exception as exc:  # noqa: BLE001
            check("run_pipeline bvo: geen fout", False, repr(exc))

        # --- run_pipeline: summary + wat-als scenario (extra_pois) ----------
        # Lokale OSM/CBS: draait offline in seconden. Basis vs. scenario.
        base_poly = square(5.09, 52.09, 0.006, 0.003)
        try:
            base_res = analysis.run_pipeline(
                _pipeline_params(base_poly, poi_groups=["daily_needs"],
                                 analyses=["counts", "equity"])
            )["result"]
            scen_res = analysis.run_pipeline(
                _pipeline_params(
                    base_poly, poi_groups=["daily_needs"],
                    analyses=["counts", "equity"],
                    extra_pois=[
                        {"lon": 5.089, "lat": 52.089, "category": "daily_needs"},
                        {"lon": 5.091, "lat": 52.091, "category": "daily_needs"},
                    ],
                )
            )["result"]
            base_count = _sum_count(base_res, "daily_needs")
            scen_count = _sum_count(scen_res, "daily_needs")
            summary = scen_res.get("summary")
            meta = scen_res.get("meta", {})
            check(
                "run_pipeline: summary aanwezig met verwachte keys",
                isinstance(summary, dict)
                and {"weighted", "population_total", "max_minutes", "per_group",
                     "composite_pct", "fully_served_pct"} <= set(summary)
                and isinstance(summary.get("per_group"), list),
                f"keys={sorted(summary) if isinstance(summary, dict) else summary}",
            )
            check(
                "run_pipeline: meta.n_extra_pois==2 en scenario True",
                meta.get("n_extra_pois") == 2 and meta.get("scenario") is True,
                f"n_extra_pois={meta.get('n_extra_pois')}, scenario={meta.get('scenario')}",
            )
            check(
                "run_pipeline: extra_pois verhoogt count_daily_needs",
                scen_count >= base_count and scen_count > 0,
                f"basis={base_count}, scenario={scen_count}",
            )
        except Exception as exc:  # noqa: BLE001
            check("run_pipeline summary/scenario: geen fout", False, repr(exc))
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
            and body.get("limits", {}).get("max_area_km2") == 250
            and body.get("limits", {}).get("warn_area_km2") == 40,
            f"status={r.status_code}, limits={body.get('limits')}",
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
                "GET /api/jobs/{id} -> 200 + geldige status + alle stages",
                r.status_code == 200
                and body.get("status") in {"queued", "running", "done", "error"}
                and len(body.get("stages", [])) == len(analysis.STAGES),
                f"status={r.status_code}, jobstatus={body.get('status')!r}, "
                f"stages={len(body.get('stages', []))}/{len(analysis.STAGES)}",
            )
            # Resultaat/uitkomst van de job zelf is hier NIET relevant (kan
            # falen door netwerk); we testen alleen de flow. Niet pollen.

        # --- onbekende job -> 404 --------------------------------------------
        r = client.get("/api/jobs/bestaatniet123")
        check("GET /api/jobs/<onbekend> -> 404", r.status_code == 404,
              f"status={r.status_code}")

        # --- scenario: onbekende/niet-geselecteerde groep -> 400 -------------
        r = client.post(
            "/api/analyze",
            json={"polygon": tiny, "poi_groups": ["daily_needs"],
                  "analyses": ["counts"],
                  "extra_pois": [{"lon": 4.9041, "lat": 52.3676,
                                  "category": "sociaal_medisch"}]},
        )
        check(
            "POST /api/analyze extra_pois niet-geselecteerde groep -> 400",
            r.status_code == 400
            and "niet-geselecteerde groep" in r.json().get("detail", ""),
            f"status={r.status_code}, detail={r.json().get('detail', '')!r}",
        )

        # --- scenario: te veel (>50) extra_pois -> 400 -----------------------
        r = client.post(
            "/api/analyze",
            json={"polygon": tiny, "poi_groups": ["daily_needs"],
                  "analyses": ["counts"],
                  "extra_pois": [{"lon": 4.9041, "lat": 52.3676,
                                  "category": "daily_needs"}] * 51},
        )
        check(
            "POST /api/analyze >50 extra_pois -> 400",
            r.status_code == 400,
            f"status={r.status_code}, detail={r.json().get('detail', '')!r}",
        )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) GEFAALD: {', '.join(FAILURES)}")
        return 1
    print("Alle checks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
