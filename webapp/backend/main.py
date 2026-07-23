"""FastAPI backend for the accessX test environment (X-minutenstad).

Start (from this directory):
    C:/Users/tim/.venvs/accessx/Scripts/python.exe -m uvicorn main:app --port 8000
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import analysis
from jobs import JobStore

try:
    ACCESSX_VERSION = version("accessx")
except PackageNotFoundError:
    ACCESSX_VERSION = "onbekend"

app = FastAPI(title="accessX webapp backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = JobStore()


class AnalyzeRequest(BaseModel):
    """Body of POST /api/analyze (see CONTRACT.md)."""

    polygon: dict
    mode: Literal["walk", "bike"] = "walk"
    speed_kmh: float = Field(default=4.5, gt=0)
    max_minutes: float = Field(default=15, ge=5, le=45)
    hex_resolution: Literal[8, 9, 10] = 9
    poi_groups: List[str] = Field(default_factory=lambda: list(analysis.DEFAULTS["selected_groups"]))
    analyses: List[str] = Field(default_factory=lambda: list(analysis.DEFAULTS["analyses"]))
    beta: float = Field(default=0.15, gt=0)
    sfca_decay: Literal["binary", "exp"] = "exp"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "accessx_version": ACCESSX_VERSION}


@app.get("/api/presets")
def presets() -> dict:
    return {
        "poi_groups": analysis.POI_GROUPS,
        "defaults": analysis.DEFAULTS,
        "limits": analysis.LIMITS,
    }


@app.post("/api/analyze", status_code=202)
def analyze(req: AnalyzeRequest) -> dict:
    try:
        geom = analysis.extract_geometry(req.polygon)
        _aoi, area_km2 = analysis.validate_polygon(geom)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not req.poi_groups:
        raise HTTPException(
            status_code=400, detail="Kies minimaal één voorzieningsgroep."
        )
    unknown_groups = [g for g in req.poi_groups if g not in analysis.POI_GROUPS]
    if unknown_groups:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekende voorzieningsgroep(en): {', '.join(unknown_groups)}.",
        )
    unknown_analyses = [a for a in req.analyses if a not in analysis.ANALYSIS_KEYS]
    if unknown_analyses:
        raise HTTPException(
            status_code=400,
            detail=f"Onbekende analyse(s): {', '.join(unknown_analyses)}.",
        )

    request_echo = req.model_dump()
    params = {
        **request_echo,
        "polygon_geom": geom,
        "area_km2": area_km2,
        "request_echo": request_echo,
    }
    job_id = store.create(params)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    status = store.public_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Onbekende job.")
    return status


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str) -> Any:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Onbekende job.")
    if job["status"] != "done":
        raise HTTPException(
            status_code=404,
            detail=f"Resultaat nog niet beschikbaar (status: {job['status']}).",
        )
    return job["result"]


@app.get("/api/jobs/{job_id}/isochrone")
def job_isochrone(
    job_id: str,
    hex_id: str = Query(..., description="hex_id uit het resultaat"),
    interval: Optional[float] = Query(default=None, description="Ringinterval in minuten"),
) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Onbekende job.")
    if job["status"] != "done" or job["graph"] is None or job["hexes_m"] is None:
        raise HTTPException(
            status_code=404,
            detail=f"Isochronen nog niet beschikbaar (status: {job['status']}).",
        )
    if interval is not None and interval <= 0:
        raise HTTPException(
            status_code=400, detail="interval moet groter dan 0 zijn."
        )
    max_minutes = float(job["params"]["max_minutes"])
    try:
        return analysis.compute_isochrone_rings(
            job["graph"], job["hexes_m"], hex_id, max_minutes, interval
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Onbekende hex_id: {hex_id}.") from exc
