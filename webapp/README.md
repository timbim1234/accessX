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
| Netwerk | lokale extract (`local_osm.build_graph_local`, pariteit met `build_network`, `simplify=False`); terugval op OSMnx/Overpass buiten dekking | lokale NL-parquet (zie hieronder) |
| Voorzieningen | lokale extract (`local_osm.load_pois_local`) → gecombineerde Overpass-query (`fetch_pois_combined`) → `get_pois_osm` | lokale NL-parquet; anders OSM Overpass |
| Bevolking | `map_population_grid_to_hexes` | CBS 100 m-grid (`data/nl_cbs/…`, lokaal, incl. leeftijdsgroepen) |
| Tellen | `count_accessible_pois` | — |
| Dichtstbijzijnde | `compute_nearest_poi_cost` | — |
| Hansen | `compute_hansen_accessibility` | — |
| 2SFCA | `compute_2sfca_accessibility` (vraag = CBS-inwoners) | — |
| Verdeling | `calculate_lorenz` (Gini) + `compute_sufficientarian_score` | — |
| Isochronen | `calculate_isochrones` (on-demand per hex) | — |

## Lokale OSM-extract (heel Nederland)

Netwerk én voorzieningen komen uit lokale parquet-bestanden i.p.v. Overpass, dus
een verse analyse draait overal in Nederland in seconden. Bestanden staan in
`%LOCALAPPDATA%\accessx_webapp_cache\local_osm\` (edges/nodes/pois.parquet +
meta.json), gegenereerd uit een Geofabrik-extract:

```powershell
# eenmalig / bij een data-update (heel NL, ~19 min, ~1 GB parquet):
C:\Users\tim\.venvs\accessx\Scripts\python.exe prepare_local_data.py `
  "$env:LOCALAPPDATA\accessx_webapp_cache\local_osm\netherlands-latest.osm.pbf"
```

`local_osm.build_graph_local` / `load_pois_local` filteren de parquet op de
getekende polygoon (pyarrow bbox-pushdown). Buiten de dekking van de parquet valt
de backend automatisch terug op OSMnx/Overpass. De lokale data is gebakken met de
huidige `POI_GROUPS`; na een categorie-wijziging opnieuw preppen.

Huidige extract: `netherlands-latest.osm.pbf` → 13,3M edges, 12M nodes, 159.624 POIs.

## Prestaties

De drie datalaadstappen (netwerk, voorzieningen, CBS) draaien parallel. Gemeten
via het lokale pad:

| Scenario | Totaal | Netwerk | Voorzieningen |
|---|---|---|---|
| Vers gebied, overal in NL (3,4 km², 7 groepen) | ~15–20 s | ~6–9 s (lokaal) | ~0,05 s (lokaal) |
| Buiten dekking (terugval Overpass) | ~1,5–4,5 min | OSM-download | 1 gecombineerde query |
| POI-stap oud → lokaal | 550–780 s → **~0,05 s** | — | — |

De resterende ~7 s netwerk-tijd zit in `ox.project_graph` + `to_undirected` op
~25k knopen (pariteit met accessX). Voor productie in CityMaker kun je per
gemeente/regio een voorgeprojecteerd netwerk cachen om ook dat weg te nemen.

## Bekende beperkingen (testomgeving)

- Eén analysejob tegelijk; jobs blijven in het geheugen tot herstart.
- Teksten van de teken-werkbalk (leaflet-draw) zijn Engels.
