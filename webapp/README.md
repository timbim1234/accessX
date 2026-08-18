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

1. Teken een polygoon/rechthoek (max 250 km²), **of** zoek een gemeente/wijk/buurt
   in de zoekbalk (via PDOK) om die grens als analysegebied te laden.
2. Kies vervoerswijze (lopen/fietsen), minuten (X-minutenstad-drempel), voorzieningengroepen en analyses.
3. Klik **Analyseer gebied** en volg de voortgang per stap.
4. Bekijk resultaten: 15-minutenstad-KPI, choropleth per metric, POI-lagen,
   Gini-tabel + Lorenz-curves, isochronen per hex, en exporteer als GeoJSON/CSV.

### Extra functies

- **15-minutenstad-KPI** — bovenaan de resultaten: bevolkingsgewogen aandeel
  inwoners dat de drempels haalt (samengestelde score + volledig-voorzien-%, plus
  per voorziening een balk). Backend: `summary`-blok in het result.
- **Wat-als scenario** — zet de wat-als-modus aan en plaats fictieve voorzieningen
  op de kaart; "Herbereken met scenario" draait dezelfde analyse mét die punten.
  Schakel tussen "Scenario" en "Verschil t.o.v. basis" (divergente choropleth,
  blauw = beter bereikbaar) en zie de KPI-winst. Backend: `extra_pois` in
  `POST /api/analyze`.
- **Gebieden laden** — PDOK Locatieserver-proxy: `GET /api/geocode?q=` (suggesties)
  en `GET /api/area/{id}` (grens als GeoJSON + oppervlak). Gebiedslimiet staat op
  250 km² zodat een hele gemeente past.
- **Export** — vier knoppen onder "Exporteren":
  - **GeoPackage (.gpkg)** en **Shapefile (.zip)** gaan via de backend
    (`POST /api/jobs/{job_id}/export`, body `{format, isochrone}`) en bevatten
    drie lagen in **RD New (EPSG:28992)**: `hexes` (alle berekende waarden),
    `voorzieningen` (POI-punten) en `isochroon` (de ringen van het isochroon dat
    op dat moment op de kaart staat; de frontend stuurt dat mee omdat het niet
    in het jobresultaat zit). Lege lagen blijven weg.
  - **GeoJSON** en `;`-gescheiden **CSV** blijven client-side en bevatten alleen
    de hexes (WGS84, resp. zonder geometrie).

  Shapefile staat maar 10 tekens per veldnaam toe. `export.shorten_field_names`
  kort daarom af op het metriekvoorvoegsel — `n_` (aantal), `t_` (reistijd),
  `h_` (Hansen), `s_` (2SFCA), `bh_` (Hansen op vloeroppervlak) — plus een
  6-letterige groepscode, zodat `n_detkls`/`t_detkls`/`h_detkls` herkenbaar bij
  dezelfde categorie horen. Dat gebeurt ook als de volledige naam nét zou
  passen, anders staat `count_cafe` naast `n_dainee` in dezelfde tabel. De zip
  bevat een `velden.csv` die elke afkorting terugvertaalt en een `LEESMIJ.txt`.
  De isochroon-kolommen (`start_type`, `start_naam`, `start_hex`, `start_lon`,
  `start_lat`) zijn bewust ≤ 10 tekens en blijven dus onverkort.

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
# eenmalig / bij een data-update (heel NL, ~40 min, ~1 GB parquet):
C:\Users\tim\.venvs\accessx\Scripts\python.exe prepare_local_data.py `
  "$env:LOCALAPPDATA\accessx_webapp_cache\local_osm\netherlands-latest.osm.pbf"
```

`local_osm.build_graph_local` / `load_pois_local` filteren de parquet op de
getekende polygoon (pyarrow bbox-pushdown). Buiten de dekking van de parquet valt
de backend automatisch terug op OSMnx/Overpass.

De categorie zit in `pois.parquet` gebakken, dus na een wijziging in
`poi_groups.py` moet je opnieuw preppen. `meta.json` bevat daarom de lijst
categorieën waarmee de extract is gebouwd; `local_osm.missing_categories()`
vergelijkt die met de gevraagde selectie en de backend valt met een
waarschuwing terug op Overpass zolang de extract verouderd is.

## Vloeroppervlakte (BAG)

Analyse `bvo` koppelt elke voorziening aan een BAG-verblijfsobject via PDOK's
BAG-WFS (`backend/bag.py`, geen API-sleutel nodig). Levert:

- `bvo_m2`, `gebruiksdoel` en `doel_match` per voorziening in de POI-laag;
- `result["bvo"].per_group` — m² per categorie, met een uitschieterbestendige
  schatting (`m2_typisch` = aantal × mediaan) naast het rauwe totaal;
- `bvo_hansen_<groep>` per hex — bereikbaar vloeroppervlak: dezelfde
  Hansen-formule, maar met m² als gewicht in plaats van aantallen.

Koppelregel, in volgorde:

1. **Op adres** — `addr:street`/`addr:housenumber`/`addr:postcode` van de POI
   tegen het adres van het verblijfsobject. Dat wijst precies één unit aan; 93%
   van de kleinschalige detailhandel in OSM draagt een adres. De prep schrijft
   die tags mee in `pois.parquet` (`addr_*`-kolommen), de Overpass-route neemt
   ze rechtstreeks mee.
2. **Op ligging** voor de rest: de POI moet ín een BAG-pand liggen
   (buitenruimte hoort geen verblijfsobject te hebben), binnen dat pand wint een
   passend `gebruiksdoel`, en de toewijzing is één-op-één zodat niet twintig
   zaken in een winkelcentrum hetzelfde object claimen. Bij vergelijkbare
   afstand wint het specifiekste gebruiksdoel (`winkelfunctie` boven
   `winkelfunctie,woonfunctie`).

Verblijfsobjecten onder `bag.MIN_VBO_M2` doen niet mee: de BAG voert 1 m² op waar
de oppervlakte onbekend is. BAG levert gebruiksoppervlakte (NEN 2580);
`bag.GO_TO_BVO` rekent om naar BVO. Per categorie rapporteert de backend
`adres_pct` (hoe vaak exact gekoppeld) naast `zeker_pct` (gebruiksdoel plausibel).

PDOK's WFS weigert paginering voorbij ~50.000 records, dus `_fetch_tiled` splitst
de bbox in kwadranten tot elke tegel onder `bag.TILE_MAX` blijft — anders viel de
vloeroppervlakte juist in dichte binnensteden weg. Zo'n analyse doet tientallen
requests, dus `_get` herkanst transiente fouten (niet op 4xx). Boven
`bag.MAX_VBO` verblijfsobjecten stopt de koppeling met een waarschuwing en draait
de rest van de analyse gewoon door.

Gemeten over heel NL (15 min lopen, wijkniveau): Groningen-Binnenstad 47 s,
Maastricht-Binnenstad 26 s, Almere-Buiten 22 s, Zuilen 18 s.

## Groen binnen 300 m (3-30-300)

Analyse `groen300` meet per hex de **loopafstand over het netwerk tot de rand**
van het dichtstbijzijnde groengebied van minstens 0,5 ha, en rapporteert het
bevolkingsgewogen aandeel dat binnen 300 m zit.

Naar de rand, niet naar het middelpunt: bij een park van 20 ha ligt de centroïde
honderden meters van de ingang. `analysis.green_entry_points` bemonstert daarom
de omtrek van elk groenvlak (elke 25 m) en gebruikt die punten als "ingangen";
de bestaande routeerfunctie rekent daar de kortste loopafstand naartoe
(`cost_attr="length"`, dus in meters in plaats van minuten).

De groenvlakken staan als polygoon in `green.parquet`, apart van `pois.parquet`.
Toevoegen of verversen kan zonder de volledige prep:

```powershell
C:\Users\tim\.venvs\accessx\Scripts\python.exe prepare_local_data.py `
  "$env:LOCALAPPDATA\accessx_webapp_cache\local_osm\netherlands-latest.osm.pbf" --only groen
```

Wat telt als groen (`_GreenHandler.TAGS`) is een inhoudelijke keuze met
consequenties, gemeten op de NL-extract:

| meegenomen | 953.820 ha over 161.928 vlakken |
|---|---|
| bewust eruit: `landuse=meadow`/`grass`/`orchard` | met die erbij: 3,3 mln ha — bijna de hele landoppervlakte, waardoor elk plattelandsadres de norm haalt |
| bewust eruit: `nature_reserve` > 10.000 ha | dat zijn Waddenzee, Noordzeekustzone, IJsselmeer en Voordelta: 71% van alle reservaat-oppervlakte, en zeegebied waar je niet in wandelt. Ze dragen zelf geen water-tag, dus omvang is het enige onderscheid — een aanname, geen zekerheid |

De ha-totalen tellen overlappende vlakken (een bos binnen een reservaat) dubbel;
voor de afstandsmeting maakt dat niet uit.

## Voorzieningencategorieën

`backend/poi_groups.py` is de enige bron van waarheid — gebruikt door de
webapp-pipeline, de pbf-prep én `/api/presets`. De categorieën volgen de
CityMaker-functiemixlegenda (sectie `functiemix`), aangevuld met wat een
15-minutenstad-analyse nodig heeft maar daar niet in staat (sectie
`bereikbaarheid`).

Een categorie heeft een `match`-spec met vier bouwstenen:

| vorm | betekenis |
|---|---|
| `{"amenity": ["school"], "shop": True}` | OR over (key, waarde)-paren |
| `{"any": [spec, ...]}` | OR |
| `{"all": [spec, ...]}` | AND |
| `{"not": spec}` | NOT |

Zet bij `all` de selectiefste voorwaarde vooraan: `query_tags()` bouwt de
Overpass-query uit alleen het eerste kind (elke AND-voorwaarde is op zich al een
superset). Diezelfde wandeling levert de key-index waarmee de prep per object
maar een paar categorieën hoeft te evalueren in plaats van alle 25.

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
