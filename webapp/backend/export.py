"""Export van een analyseresultaat naar GeoPackage of (gezipte) Shapefile.

De frontend exporteert GeoJSON/CSV zelf, maar GIS-pakketten (en CityMaker)
willen een GPKG of SHP. Die formaten kun je niet in de browser maken, dus
schrijft de backend ze met GDAL (via geopandas/pyogrio) uit hetzelfde
resultaat dat de job al in het geheugen heeft.

Drie lagen: `hexes` (alle berekende waarden), `voorzieningen` (de POI-punten)
en -- als de gebruiker er een open heeft staan -- `isochroon` (de ringen). Het
isochroon zit niet in het jobresultaat (dat wordt on-demand berekend), dus
stuurt de frontend het mee in de request; zo exporteer je exact wat er op de
kaart staat.

Alles wordt geschreven in RD New (EPSG:28992), de standaard voor NL-GIS.

Shapefile is een beperkt formaat: max 10 tekens per veldnaam en een bestand
per geometrietype. Daarom gaan de drie lagen als losse shapefiles in een zip,
worden de veldnamen afgekort (zie `shorten_field_names`) en zit er een
`velden.csv` bij die elke afkorting terugvertaalt. GeoPackage heeft die
beperkingen niet en houdt de volledige namen.
"""
from __future__ import annotations

import csv
import io
import math
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd

import analysis

EXPORT_EPSG = analysis.METRIC_EPSG  # RD New (28992)

# formaat -> (achtervoegsel bestandsnaam, mediatype)
FORMATS: Dict[str, Tuple[str, str]] = {
    "gpkg": (".gpkg", "application/geopackage+sqlite3"),
    "shp": ("_shp.zip", "application/zip"),
}

LAYER_HEXES = "hexes"
LAYER_POIS = "voorzieningen"
LAYER_ISO = "isochroon"

SHP_FIELD_MAX = 10  # dBase-limiet voor veldnamen

# Metriek-voorvoegsels afkorten tot 1-3 tekens, zodat er binnen de 10 tekens
# van een shapefile-veld altijd dezelfde 6-letterige groepscode past:
# `n_detkls`, `t_detkls` en `h_detkls` slaan zo herkenbaar op een categorie.
# (voorvoegsel, korte vorm, achtervoegsel dat weg mag)
_METRIC_PREFIXES: List[Tuple[str, str, str]] = [
    ("nearest_cost_", "t_", "_1"),  # t = tijd in minuten
    ("bvo_hansen_", "bh_", ""),
    ("count_", "n_", ""),
    ("hansen_", "h_", ""),
    ("sfca_", "s_", ""),
]
_GROUP_CODE_LEN = 6


class ExportError(Exception):
    """Fout met een Nederlandse melding voor de gebruiker."""


def _squeeze(text: str, n: int) -> str:
    """Kort `text` in tot n tekens; bij woorden (op _) elk woord evenveel.

    `voortgezet_onderwijs` -> `vooond`, `detailhandel_kls` -> `detkls`. Dat
    blijft leesbaar en houdt categorieen uit elkaar die op hetzelfde woord
    beginnen (`detailhandel_kls` vs. `detailhandel_grs`).
    """
    parts = [p for p in text.split("_") if p]
    if len(parts) <= 1:
        return text[:n]
    per = max(1, math.ceil(n / len(parts)))
    return "".join(p[:per] for p in parts)[:n]


def _unique(name: str, used: set, maxlen: int = SHP_FIELD_MAX) -> str:
    """Maak `name` uniek binnen `used` door er een volgnummer op te plakken."""
    if name not in used:
        return name
    i = 2
    while True:
        suffix = str(i)
        candidate = name[: maxlen - len(suffix)] + suffix
        if candidate not in used:
            return candidate
        i += 1


def shorten_field_names(columns: List[str]) -> Dict[str, str]:
    """Kolomnaam -> shapefile-veldnaam (max 10 tekens, uniek).

    Metriekkolommen gaan altijd via hun voorvoegsel (`count_daily_needs` ->
    `n_dainee`), ook als de volledige naam nog net binnen tien tekens past --
    anders staat `count_cafe` naast `n_dainee` in dezelfde attributentabel.
    Overige namen blijven heel, of worden afgekapt als ze te lang zijn.
    """
    mapping: Dict[str, str] = {}
    used: set = set()
    for col in columns:
        short = None
        for prefix, code, suffix in _METRIC_PREFIXES:
            if not col.startswith(prefix):
                continue
            rest = col[len(prefix):]
            if suffix and rest.endswith(suffix):
                rest = rest[: -len(suffix)]
            budget = min(_GROUP_CODE_LEN, SHP_FIELD_MAX - len(code))
            short = code + _squeeze(rest, budget)
            break
        if short is None:
            short = col if len(col) <= SHP_FIELD_MAX else col[:SHP_FIELD_MAX]
        short = _unique(short, used)
        used.add(short)
        mapping[col] = short
    return mapping


def _normalize(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Object-kolommen omzetten naar iets dat GDAL kan wegschrijven.

    Uit GeoJSON komen booleans en gemengde types als object-dtype terug; die
    weigert de driver. Booleans worden 0/1, gemengde kolommen tekst.
    """
    geom_col = gdf.geometry.name
    for col in gdf.columns:
        if col == geom_col or gdf[col].dtype != object:
            continue
        types = {type(v) for v in gdf[col].dropna()}
        if types <= {bool}:
            gdf[col] = gdf[col].map(
                lambda v: None if v is None else int(v)
            ).astype("Int64")
        elif types - {str}:
            gdf[col] = gdf[col].map(lambda v: None if v is None else str(v))
    return gdf


def _fc_to_gdf(fc: Optional[dict]) -> Optional[gpd.GeoDataFrame]:
    """GeoJSON FeatureCollection (4326) -> GeoDataFrame in RD New, of None."""
    features = (fc or {}).get("features") or []
    features = [f for f in features if isinstance(f, dict) and f.get("geometry")]
    if not features:
        return None
    gdf = gpd.GeoDataFrame.from_features(features, crs=4326)
    return _normalize(gdf.to_crs(EXPORT_EPSG))


def _isochrone_to_gdf(isochrone: Optional[dict]) -> Optional[gpd.GeoDataFrame]:
    """Isochroon-payload -> ringen met het vertrekpunt als attributen."""
    if not isinstance(isochrone, dict):
        return None
    gdf = _fc_to_gdf(isochrone.get("rings"))
    if gdf is None:
        return None
    # Namen bewust <= 10 tekens, zodat ze ook in een shapefile onverkort
    # overeind blijven.
    origin = isochrone.get("origin") or {}
    gdf["start_type"] = origin.get("type") or "onbekend"
    if origin.get("label"):
        gdf["start_naam"] = str(origin["label"])
    hex_id = origin.get("hex_id") or isochrone.get("hex_id")
    if hex_id:
        gdf["start_hex"] = str(hex_id)
    if origin.get("lon") is not None and origin.get("lat") is not None:
        gdf["start_lon"] = float(origin["lon"])
        gdf["start_lat"] = float(origin["lat"])
    return gdf


def _layers(
    result: dict, isochrone: Optional[dict]
) -> List[Tuple[str, gpd.GeoDataFrame]]:
    """De te exporteren lagen; lege lagen blijven weg."""
    layers: List[Tuple[str, gpd.GeoDataFrame]] = []
    for name, gdf in (
        (LAYER_HEXES, _fc_to_gdf((result or {}).get("hexes"))),
        (LAYER_POIS, _fc_to_gdf((result or {}).get("pois"))),
        (LAYER_ISO, _isochrone_to_gdf(isochrone)),
    ):
        if gdf is not None and len(gdf):
            layers.append((name, gdf))
    return layers


def _write_gpkg(layers: List[Tuple[str, gpd.GeoDataFrame]]) -> bytes:
    """Alle lagen in een GeoPackage; volledige veldnamen blijven behouden."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.gpkg"
        for name, gdf in layers:
            gdf.to_file(path, layer=name, driver="GPKG")
        return path.read_bytes()


_README = """accessX export
==============

Coordinatenstelsel: RD New (EPSG:28992).

Lagen (elk een eigen shapefile):
  hexes.shp          hexgrid met alle berekende waarden per hex
  voorzieningen.shp  de gevonden voorzieningen als punt
  isochroon.shp      de ringen van het getoonde isochroon (alleen aanwezig als
                     er bij het exporteren een isochroon open stond)

Shapefile staat maximaal 10 tekens per veldnaam toe, dus lange kolomnamen zijn
afgekort. velden.csv (;-gescheiden) vertaalt elke afkorting terug naar de
volledige naam. Voorvoegsels: n_ = aantal, t_ = reistijd in minuten,
h_ = Hansen, s_ = 2SFCA, bh_ = Hansen op vloeroppervlak. Wil je de volledige
namen behouden, exporteer dan als GeoPackage.
"""


def _write_shp_zip(layers: List[Tuple[str, gpd.GeoDataFrame]]) -> bytes:
    """Elke laag als losse shapefile in een zip, met veldnamenlijst erbij."""
    rows: List[Tuple[str, str, str]] = [("laag", "veldnaam", "volledige_naam")]
    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, gdf in layers:
            columns = [c for c in gdf.columns if c != gdf.geometry.name]
            mapping = shorten_field_names(columns)
            gdf.rename(columns=mapping).to_file(
                folder / f"{name}.shp", driver="ESRI Shapefile", encoding="UTF-8"
            )
            rows.extend(
                (name, short, full)
                for full, short in mapping.items()
                if short != full
            )

        fields = io.StringIO(newline="")
        writer = csv.writer(fields, delimiter=";", lineterminator="\r\n")
        writer.writerows(rows)
        # utf-8-sig: BOM zodat Excel NL de tekens goed leest, net als de
        # CSV-export in de frontend.
        (folder / "velden.csv").write_text(
            fields.getvalue(), encoding="utf-8-sig", newline=""
        )
        (folder / "LEESMIJ.txt").write_text(_README, encoding="utf-8")

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(folder.iterdir()):
                zf.write(path, arcname=path.name)
    return buffer.getvalue()


def build_export(
    result: dict,
    isochrone: Optional[dict],
    fmt: str,
    basename: str,
) -> Tuple[bytes, str, str]:
    """Bouw het exportbestand. Geeft (bytes, bestandsnaam, mediatype) terug."""
    if fmt not in FORMATS:
        raise ExportError(f"Onbekend exportformaat: {fmt}.")
    try:
        layers = _layers(result, isochrone)
    except Exception as exc:  # noqa: BLE001 - onverwachte geometrie in de payload
        raise ExportError(f"Kon de exportlagen niet opbouwen: {exc}") from exc
    if not layers:
        raise ExportError("Er is niets te exporteren: het resultaat is leeg.")
    try:
        data = _write_gpkg(layers) if fmt == "gpkg" else _write_shp_zip(layers)
    except Exception as exc:  # noqa: BLE001 - GDAL-fouten leesbaar doorgeven
        raise ExportError(
            f"Wegschrijven van het exportbestand mislukte: {exc}"
        ) from exc
    suffix, mediatype = FORMATS[fmt]
    return data, f"{basename}{suffix}", mediatype
