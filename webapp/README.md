# accessX testlab — webapp

Testomgeving om accessX te evalueren: teken een polygoon op de kaart van Nederland,
en de accessX-analyses (X-minutenstad) draaien automatisch op dat gebied.

## Starten

**Backend** (FastAPI, poort 8000) — vanuit `webapp/backend/`:

```powershell
cd U:\GitHub\accessX\webapp\backend
C:\Users\tim\.venvs\accessx\Scripts\python.exe -m uvicorn main:app --port 8000
```

**Frontend** (Vite dev-server, poort 5173) — vanuit `webapp/frontend/`:

```powershell
cd U:\GitHub\accessX\webapp\frontend
npm install   # eenmalig
npm run dev
```

Open daarna **http://localhost:5173**.

> Let op: start de frontend vanaf de gekoppelde `U:`-schijf, niet via een
> `\\CAFY01\...`-UNC-pad — cmd.exe (dat npm-scripts uitvoert) ondersteunt geen
> UNC-werkmappen.

De venv is aangemaakt met: `python -m venv C:\Users\tim\.venvs\accessx` gevolgd door
`pip install -e <repo-root> fastapi "uvicorn[standard]"`.

## Gebruik

1. Teken een polygoon of rechthoek (knoppen rechtsboven in de kaart), max 100 km².
2. Kies vervoerswijze (lopen/fietsen), minuten (X-minutenstad-drempel), voorzieningengroepen en analyses.
3. Klik **Analyseer gebied** en volg de voortgang per stap.
4. Bekijk resultaten: choropleth per metric, POI-lagen, Gini-tabel + Lorenz-curves,
   en isochronen per hex (toggle "Isochroon bij klik").

## Wat draait er per analyse?

| Stap | accessX-functie | Data |
|---|---|---|
| Hexgrid | `make_hex_grid` (H3, res 8–10) | — |
| Netwerk | `build_network` + `add_time_cost_constant_speed` | OSM (OSMnx, gecachet in `%LOCALAPPDATA%\accessx_webapp_cache`) |
| Voorzieningen | eigen gecombineerde Overpass-query (`fetch_pois_combined` in `analysis.py`), zelfde categorisering als `get_pois_osm`; valt bij fouten terug op `get_pois_osm` | OSM Overpass (1 query voor alle groepen, ~15 s i.p.v. minuten) |
| Bevolking | `map_population_grid_to_hexes` | CBS 100 m-grid (`data/nl_cbs/…`, lokaal, incl. leeftijdsgroepen) |
| Tellen | `count_accessible_pois` | — |
| Dichtstbijzijnde | `compute_nearest_poi_cost` | — |
| Hansen | `compute_hansen_accessibility` | — |
| 2SFCA | `compute_2sfca_accessibility` (vraag = CBS-inwoners) | — |
| Verdeling | `calculate_lorenz` (Gini) + `compute_sufficientarian_score` | — |
| Isochronen | `calculate_isochrones` (on-demand per hex) | — |

## Prestaties

De drie datalaadstappen (netwerk, voorzieningen, CBS) draaien parallel; de
voorzieningen komen met één gecombineerde Overpass-query binnen. Gemeten:

| Scenario | Totaal | Zwaarste stap |
|---|---|---|
| Vers gebied (3,4 km², 5 groepen) | ~1,5–4,5 min | OSM-netwerkdownload (Overpass, wisselend belast) |
| Zelfde gebied opnieuw (cache) | ~20 s | analyses zelf (~10 s) |
| POI-stap oud → nieuw | 550–780 s → **0,2–15 s** | — |

De resterende bottleneck is de OSM-netwerkdownload bij een vers gebied. Wil je
dat ook structureel oplossen, gebruik dan een lokale OSM-extract (bijv.
Geofabrik NL-pbf) of een voorgeladen landelijk netwerk i.p.v. Overpass.

## Bekende beperkingen (testomgeving)

- Eén analysejob tegelijk; jobs blijven in het geheugen tot herstart.
- Teksten van de teken-werkbalk (leaflet-draw) zijn Engels.
