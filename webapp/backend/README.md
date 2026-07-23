# accessX webapp — backend

FastAPI-backend voor de X-minutenstad-testomgeving. Zie `../../..`-root voor de
accessX-library en `CONTRACT.md` (scratchpad) voor het API-contract.

## Starten

Vanuit deze map (`webapp/backend/`):

```powershell
C:/Users/tim/.venvs/accessx/Scripts/python.exe -m uvicorn main:app --port 8000
```

De API draait dan op `http://localhost:8000`. De frontend-dev-server (Vite,
poort 5173) proxyt `/api` hierheen; CORS voor `http://localhost:5173` en
`http://127.0.0.1:5173` staat ook open.

## Endpoints (kort)

- `GET /api/health` — status + accessx-versie
- `GET /api/presets` — voorzieningsgroepen, defaults en limieten
- `POST /api/analyze` — start een analysejob (202 + `job_id`)
- `GET /api/jobs/{job_id}` — voortgang per stage
- `GET /api/jobs/{job_id}/result` — volledig resultaat (alleen bij `done`)
- `GET /api/jobs/{job_id}/isochrone?hex_id=...&interval=5` — isochronen per hex

## Smoke-test

```powershell
C:/Users/tim/.venvs/accessx/Scripts/python.exe test_smoke.py
```

Test health/presets/validaties/202-flow zonder een volledige analyse af te
wachten (de gestarte mini-job mag falen door netwerk; dat is geen testfout).

## Opmerkingen

- Jobs draaien één tegelijk, in-memory (weg na herstart van de server).
- OSM-data (netwerk + voorzieningen) komt live van OpenStreetMap; de
  OSMnx-cache staat lokaal in `%LOCALAPPDATA%/accessx_webapp_cache`.
- CBS-bevolking komt uit `../../data/nl_cbs/cbs_vk100_2020_vol.gpkg`
  (100×100 m grid, EPSG:28992).
