"""BAG-koppeling: vloeroppervlakte (m2) bij OSM-voorzieningen.

OSM weet WAT een voorziening is (bakker vs. kledingwinkel, huisarts vs. fysio),
maar niet hoe groot ze is: `beds` staat op 5 objecten in heel NL en
`building:levels` op 629. De BAG weet het omgekeerde: elk verblijfsobject heeft
een exacte oppervlakte en een gebruiksdoel, maar geen specifieke functie. Deze
module koppelt beide via PDOK's BAG-WFS.

Koppelregel (gemeten op Utrecht-West, zie webapp/README.md):
 1. Een POI krijgt alleen oppervlakte als hij IN een BAG-pand ligt. Zonder die
    poort koppelt een "dichtstbijzijnde verblijfsobject binnen 25 m" ook parken,
    speeltuinen en haltes aan het eerste schuurtje in de buurt (14-16% valse
    treffers gemeten).
 2. Binnen dat pand wint het dichtstbijzijnde verblijfsobject dat NIET puur
    woonfunctie is.
 3. Delen meerdere POI's hetzelfde verblijfsobject, dan legt `vbo_share` vast
    met hoeveel, en `bvo_m2` bevat al dat aandeel -- sommeren telt de meters
    precies een keer.

Let op: BAG levert **gebruiksoppervlakte** (GO, NEN 2580), niet BVO. De
omrekening naar bruto vloeroppervlak gebeurt met GO_TO_BVO; controleer die
factor tegen de definitie die in de programmering wordt gehanteerd.

User-facing strings (waarschuwingen/fouten) zijn Nederlands; code en commentaar
Engels/Nederlands gemengd conform de rest van de backend.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import shape

PDOK_BAG_WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
RD_EPSG = 28992

_PAGE = 1000
_TIMEOUT_S = 120
_RETRIES = 2
_RETRY_PAUSE_S = 1.5

# PDOK weigert paginering voorbij ~50.000 records (HTTP 400 op startIndex).
# Een bbox met meer objecten wordt daarom opgesplitst in kwadranten tot elk
# stuk eronder blijft. Zonder dat viel de vloeroppervlakte weg in precies de
# gebieden waar ze het interessantst is: dichte binnensteden.
TILE_MAX = 40_000
_MAX_TILE_DEPTH = 6

# Totaalplafond over alle tegels samen: daarboven wordt het aantal requests
# (1 per 1000 objecten) onredelijk voor een interactieve analyse.
MAX_VBO = 250_000

#: BVO = GO x deze factor. 1/0,85 voor utiliteitsbouw; pas aan als de
#: programmering een andere GO/BVO-verhouding hanteert.
GO_TO_BVO = 1.0 / 0.85

#: Gebruiksdoelen die als "niet-wonen" tellen (alles behalve pure woonfunctie).
_WOON = "woonfunctie"

#: Een verblijfsobject dat meer dan dit aandeel van alle niet-woon-oppervlakte
#: in zijn pand beslaat terwijl er nog minstens CONTAINER_MIN_VBO andere in
#: datzelfde pand zitten, is de registratie van het complex als geheel (een
#: winkelcentrum) en niet van een losse zaak. Zulke objecten worden
#: overgeslagen; anders erfde een cafe in Hoog Catharijne het hele complex.
#: Een groot solitair gebouw (een IKEA) heeft geen tientallen buren en blijft
#: dus gewoon meedoen.
CONTAINER_SHARE = 0.4
CONTAINER_MIN_VBO = 4

#: Verblijfsobjecten kleiner dan dit tellen niet mee. De BAG voert 1 m² op waar
#: de oppervlakte niet bekend of niet betekenisvol is, en bergingen/meterkasten
#: staan er net zo klein in. Zo'n object aan een winkel hangen levert een getal
#: op dat er gegarandeerd naast zit -- liever geen m² dan 1 m².
MIN_VBO_M2 = 12.0

#: Verwacht BAG-gebruiksdoel per POI-categorie. Zit er in hetzelfde pand een
#: verblijfsobject met een passend gebruiksdoel, dan wint dat van het puur
#: dichtstbijzijnde -- anders kreeg een supermarkt de kantoorunit ernaast.
#: Categorieen die hier NIET in staan krijgen geen vloeroppervlakte: dat zijn
#: de buitenruimte-categorieen (park, speeltuin, halte, volkstuin) die geen
#: verblijfsobject horen te hebben.
EXPECTED_DOEL: Dict[str, Tuple[str, ...]] = {
    "detailhandel_kls": ("winkelfunctie",),
    "detailhandel_grs": ("winkelfunctie",),
    "daily_needs": ("winkelfunctie",),
    "kantoor": ("kantoorfunctie",),
    "bedrijven": ("industriefunctie",),
    "sociaal_medisch": ("gezondheidszorgfunctie",),
    "basis_onderwijs": ("onderwijsfunctie",),
    "voortgezet_onderwijs": ("onderwijsfunctie",),
    "onderwijs_overig": ("onderwijsfunctie",),
    # Kinderdagverblijven zijn in het Bouwbesluit bijeenkomstfunctie, maar
    # worden ook als onderwijsfunctie geregistreerd.
    "kinderopvang": ("bijeenkomstfunctie", "onderwijsfunctie"),
    "hotel": ("logiesfunctie",),
    "sporthal": ("sportfunctie",),
    "fitness": ("sportfunctie",),
    "zwembad": ("sportfunctie",),
    "sport_buiten": ("sportfunctie",),
    # Horeca is bijeenkomstfunctie, maar staat in de praktijk vaak als
    # winkelfunctie geregistreerd; beide tellen als passend.
    "restaurant": ("bijeenkomstfunctie", "winkelfunctie"),
    "cafe": ("bijeenkomstfunctie", "winkelfunctie"),
    "sociaal_cultureel": ("bijeenkomstfunctie",),
    "bibliotheek": ("bijeenkomstfunctie",),
    "museum": ("bijeenkomstfunctie",),
    "bioscoop_theater": ("bijeenkomstfunctie",),
}


class BagError(RuntimeError):
    """Koppeling met de BAG mislukt; de aanroeper slaat de m2-kolommen over."""


# ---------------------------------------------------------------------------
# WFS
# ---------------------------------------------------------------------------

def _bbox_param(bbox: Tuple[float, float, float, float]) -> str:
    return f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:{RD_EPSG}"


def _get(params: dict) -> requests.Response:
    """GET met herkansing. Een gebiedsanalyse doet tientallen requests (zie
    _fetch_tiled), dus een enkele afgebroken verbinding mag de hele
    vloeroppervlakte niet kosten. Een 4xx is een echte fout en wordt niet
    herhaald; alleen verbindingsfouten en 5xx krijgen een tweede kans."""
    last: Exception | None = None
    for poging in range(_RETRIES + 1):
        try:
            resp = requests.get(PDOK_BAG_WFS, params=params, timeout=_TIMEOUT_S)
            if 400 <= resp.status_code < 500:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if 400 <= status < 500:
                raise BagError(f"PDOK BAG wees het verzoek af ({status}).") from exc
            last = exc
        except requests.RequestException as exc:
            last = exc
        if poging < _RETRIES:
            time.sleep(_RETRY_PAUSE_S * (poging + 1))
    raise BagError(f"Kon PDOK BAG niet bereiken: {last}") from last


def count_features(typename: str, bbox: Tuple[float, float, float, float]) -> int:
    """Aantal features in de bbox, zonder ze op te halen (WFS resultType=hits)."""
    resp = _get({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeName": typename, "resultType": "hits", "bbox": _bbox_param(bbox),
    })
    match = re.search(r'numberMatched="(\d+)"', resp.text)
    if not match:
        raise BagError("Onverwacht antwoord van PDOK BAG (geen numberMatched).")
    return int(match.group(1))


def _fetch_tiled(
    typename: str,
    bbox: Tuple[float, float, float, float],
    expected: Optional[int] = None,
    depth: int = 0,
) -> List[dict]:
    """Haal alle features op, de bbox opsplitsend zolang paginering niet past.

    PDOK stopt met een HTTP 400 zodra startIndex boven ~50.000 komt, dus een
    dichte binnenstad past niet in één bbox. Elk kwadrant dat nog te vol is
    wordt opnieuw gevierendeeld.
    """
    if expected is None:
        expected = count_features(typename, bbox)
    if expected <= TILE_MAX or depth >= _MAX_TILE_DEPTH:
        return _fetch_all(typename, bbox, expected)

    minx, miny, maxx, maxy = bbox
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0
    feats: List[dict] = []
    seen: set = set()
    for quad in (
        (minx, miny, midx, midy),
        (midx, miny, maxx, midy),
        (minx, midy, midx, maxy),
        (midx, midy, maxx, maxy),
    ):
        for f in _fetch_tiled(typename, quad, None, depth + 1):
            # Objecten op een tegelgrens komen in twee kwadranten terug.
            ident = (f.get("properties") or {}).get("identificatie")
            if ident is not None:
                if ident in seen:
                    continue
                seen.add(ident)
            feats.append(f)
    return feats


def _fetch_all(typename: str, bbox: Tuple[float, float, float, float],
               expected: int) -> List[dict]:
    feats: List[dict] = []
    start = 0
    pages = max(1, -(-expected // _PAGE))  # ceil
    for _ in range(pages + 1):
        resp = _get({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeName": typename, "outputFormat": "application/json",
            "srsName": f"EPSG:{RD_EPSG}", "count": _PAGE, "startIndex": start,
            "bbox": _bbox_param(bbox),
        })
        try:
            page = resp.json().get("features", [])
        except ValueError as exc:
            raise BagError("Ongeldige JSON van PDOK BAG.") from exc
        feats.extend(page)
        if len(page) < _PAGE:
            break
        start += _PAGE
    return feats


# ---------------------------------------------------------------------------
# Koppeling
# ---------------------------------------------------------------------------

def _vbo_frame(feats: List[dict]) -> pd.DataFrame:
    """Verblijfsobjecten -> DataFrame, alleen niet-pure-woonfunctie."""
    rows = []
    for f in feats:
        props = f.get("properties") or {}
        doel = (props.get("gebruiksdoel") or "").strip()
        if not doel or doel == _WOON:
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        opp = props.get("oppervlakte")
        area = float(opp) if opp else np.nan
        if not (area >= MIN_VBO_M2):  # ook NaN valt hier af
            continue
        rows.append({
            "vbo_id": props.get("identificatie"),
            "pand_id": props.get("pandidentificatie"),
            "go_m2": area,
            "gebruiksdoel": doel,
            # Aantal functies: minder = specifieker. Bij vergelijkbare afstand
            # wint "winkelfunctie" van "winkelfunctie,woonfunctie".
            "n_doelen": doel.count(",") + 1,
            "bouwjaar": props.get("bouwjaar"),
            "postcode": (props.get("postcode") or "").replace(" ", "").upper(),
            "straat": (props.get("openbare_ruimte") or "").strip().lower(),
            "huisnummer": props.get("huisnummer"),
            "huisletter": (props.get("huisletter") or "").strip().upper(),
            "toevoeging": (props.get("toevoeging") or "").strip().upper(),
            "x": float(coords[0]),
            "y": float(coords[1]),
        })
    return pd.DataFrame(rows)


def _pand_arrays(feats: List[dict]) -> Tuple[List[str], List]:
    ids, geoms = [], []
    for f in feats:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            g = shape(geom)
        except Exception:
            continue
        if g.is_empty:
            continue
        ids.append((f.get("properties") or {}).get("identificatie"))
        geoms.append(g)
    return ids, geoms


def attach_floor_area(
    pois_wgs84: gpd.GeoDataFrame,
    *,
    margin_m: float = 25.0,
    nearby_m: float = 40.0,
    max_vbo: int = MAX_VBO,
) -> gpd.GeoDataFrame:
    """Voeg BAG-oppervlaktekolommen toe aan een POI-GeoDataFrame.

    Toegevoegde kolommen: bag_pand_id, bag_vbo_id, gebruiksdoel, bouwjaar,
    go_m2 (onverdeelde registratie), bvo_m2 (het deel dat deze voorziening
    beslaat), vbo_share, doel_match, via_nabij_pand. POI's zonder pand --
    parken, speeltuinen, haltes -- houden NaN; dat is de bedoeling, geen
    ontbrekende data. Sommeer bvo_m2 over unieke OSM-id's voor een gebiedstotaal
    (een supermarkt zit in twee categorieen).

    Raises BagError als PDOK onbereikbaar is of het gebied te groot is; de
    pipeline vangt dat af en levert dan gewoon geen m2-kolommen.
    """
    if pois_wgs84 is None or len(pois_wgs84) == 0:
        return pois_wgs84

    pois_rd = pois_wgs84.to_crs(RD_EPSG)
    minx, miny, maxx, maxy = pois_rd.total_bounds
    bbox = (minx - margin_m, miny - margin_m, maxx + margin_m, maxy + margin_m)

    n_vbo = count_features("bag:verblijfsobject", bbox)
    if n_vbo > max_vbo:
        raise BagError(
            f"Te veel BAG-verblijfsobjecten in dit gebied ({n_vbo:,} > {max_vbo:,}); "
            "kies een kleiner gebied voor de vloeroppervlakte-koppeling."
            .replace(",", ".")
        )

    vbo = _vbo_frame(_fetch_tiled("bag:verblijfsobject", bbox, n_vbo))
    pand_ids, pand_geoms = _pand_arrays(_fetch_tiled("bag:pand", bbox))

    out = pois_wgs84.copy()
    for col in ("bag_pand_id", "bag_vbo_id", "gebruiksdoel"):
        out[col] = None
    for col in ("go_m2", "bvo_m2", "vbo_share", "bouwjaar"):
        out[col] = np.nan
    # True = het gekozen verblijfsobject heeft ook het gebruiksdoel dat bij deze
    # categorie hoort; False = alleen op afstand gekozen, dus minder zeker.
    out["doel_match"] = False
    # True = niet binnen een pand gevonden maar via een pand in de directe
    # omgeving (vlak-POI's waarvan de centroide op het terrein ligt).
    out["via_nabij_pand"] = False
    # True = gekoppeld op adres i.p.v. op ligging; dat is exact in plaats van
    # "dichtstbijzijnde unit" en dus veel harder in een plint met acht zaken.
    out["via_adres"] = False
    if vbo.empty or not pand_geoms:
        return out

    # 1. Poort: in welk pand ligt de POI?
    poi_geoms = pois_rd.geometry.to_numpy()
    pand_tree = shapely.STRtree(pand_geoms)
    poi_idx, pand_idx = pand_tree.query(poi_geoms, predicate="within")
    poi_to_pand: Dict[int, int] = {}
    for i, j in zip(poi_idx, pand_idx):
        poi_to_pand.setdefault(int(i), int(j))
    if not poi_to_pand:
        return out

    # 2. Binnen dat pand: het dichtstbijzijnde niet-woon-verblijfsobject.
    by_pand: Dict[str, List[int]] = {}
    for pos, pid in enumerate(vbo["pand_id"].to_numpy()):
        if pid:
            by_pand.setdefault(pid, []).append(pos)

    # Container-registraties eruit (zie CONTAINER_SHARE).
    vbo_area = vbo["go_m2"].fillna(0.0).to_numpy()
    n_containers = 0
    for pid, positions in by_pand.items():
        if len(positions) < CONTAINER_MIN_VBO + 1:
            continue
        total = float(sum(vbo_area[k] for k in positions))
        if total <= 0:
            continue
        kept = [k for k in positions if vbo_area[k] / total <= CONTAINER_SHARE]
        if kept and len(kept) != len(positions):
            n_containers += len(positions) - len(kept)
            by_pand[pid] = kept

    vbo_x = vbo["x"].to_numpy()
    vbo_y = vbo["y"].to_numpy()
    vbo_doel = vbo["gebruiksdoel"].to_numpy()
    categories = (
        out["category"].to_numpy()
        if "category" in out.columns
        else np.array([None] * len(out))
    )
    vbo_ndoel = vbo["n_doelen"].to_numpy()
    assigned: Dict[int, int] = {}
    doel_match: Dict[int, bool] = {}
    via_nabij: Dict[int, bool] = {}
    via_adres: Dict[int, bool] = {}

    ids = out["id"].to_numpy() if "id" in out.columns else np.arange(len(out))

    # --- Adres-koppeling ---------------------------------------------------
    # 93% van de kleinschalige detailhandel in OSM draagt straat + huisnummer
    # (gemeten op de Utrecht-extract). Een adres wijst precies één unit aan,
    # waar "dichtstbijzijnde verblijfsobject binnen het pand" in een plint met
    # acht zaken naast elkaar regelmatig de buurman pakt.
    adres_index: Dict[Tuple, int] = {}
    for k in range(len(vbo)):
        nr = vbo.iat[k, vbo.columns.get_loc("huisnummer")]
        if nr in (None, "") or (isinstance(nr, float) and np.isnan(nr)):
            continue
        nr = str(int(nr)) if not isinstance(nr, str) else nr.strip()
        letter = vbo.iat[k, vbo.columns.get_loc("huisletter")]
        toev = vbo.iat[k, vbo.columns.get_loc("toevoeging")]
        pc = vbo.iat[k, vbo.columns.get_loc("postcode")]
        straat = vbo.iat[k, vbo.columns.get_loc("straat")]
        # Van specifiek naar globaal; eerste treffer wint bij het opzoeken.
        for key in (
            ("pc", pc, nr, letter, toev) if pc else None,
            ("pc", pc, nr) if pc else None,
            ("str", straat, nr, letter, toev) if straat else None,
            ("str", straat, nr) if straat else None,
        ):
            if key and key not in adres_index:
                adres_index[key] = k

    def _poi_adres(i: int) -> List[Tuple]:
        """Zoeksleutels voor deze POI, van specifiek naar globaal."""
        def val(col):
            if col not in out.columns:
                return ""
            v = out.iat[i, out.columns.get_loc(col)]
            return "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)

        nr = val("addr:housenumber").strip()
        if not nr:
            return []
        letter = val("addr:houseletter").strip().upper()
        toev = val("addr:housenumbersuffix").strip().upper()
        pc = val("addr:postcode").replace(" ", "").upper()
        straat = val("addr:street").strip().lower()
        # OSM zet de toevoeging vaak in het huisnummer zelf: "45A", "45-2".
        import re as _re

        m = _re.match(r"^(\d+)\s*[-/]?\s*([A-Za-z0-9]*)$", nr)
        if m:
            nr, extra = m.group(1), m.group(2).upper()
            if extra and not letter and not toev:
                if extra.isalpha():
                    letter = extra
                else:
                    toev = extra
        keys = []
        if pc:
            keys += [("pc", pc, nr, letter, toev), ("pc", pc, nr)]
        if straat:
            keys += [("str", straat, nr, letter, toev), ("str", straat, nr)]
        return keys

    if "addr:housenumber" in out.columns:
        claimed: set = set()
        for i in range(len(out)):
            if categories[i] not in EXPECTED_DOEL:
                continue
            for key in _poi_adres(i):
                k = adres_index.get(key)
                if k is None or k in claimed:
                    continue
                assigned[i] = k
                claimed.add(k)
                wanted = EXPECTED_DOEL.get(categories[i]) or ()
                doel_match[i] = any(w in vbo_doel[k] for w in wanted)
                via_adres[i] = True
                break
        # Rijen van hetzelfde OSM-object erven de treffer (een supermarkt zit in
        # twee categorieen maar is een pand-unit).
        by_id: Dict[Any, List[int]] = {}
        for i in range(len(out)):
            by_id.setdefault(ids[i], []).append(i)
        for rows in by_id.values():
            hit = next((i for i in rows if i in assigned), None)
            if hit is None:
                continue
            for i in rows:
                if i not in assigned and categories[i] in EXPECTED_DOEL:
                    assigned[i] = assigned[hit]
                    doel_match[i] = doel_match.get(hit, False)
                    via_adres[i] = True

    def _fitting(i: int, candidates: List[int]) -> List[int]:
        wanted = EXPECTED_DOEL.get(categories[i]) if categories[i] is not None else None
        if not wanted:
            return []
        return [k for k in candidates if any(w in vbo_doel[k] for w in wanted)]

    def _pick(i: int, candidates: List[int], require_doel: bool) -> bool:
        pt = poi_geoms[i]
        fitting = _fitting(i, candidates)
        if require_doel and not fitting:
            return False
        pool = fitting or candidates
        if not pool:
            return False
        assigned[i] = min(
            pool, key=lambda k: (vbo_x[k] - pt.x) ** 2 + (vbo_y[k] - pt.y) ** 2
        )
        doel_match[i] = bool(fitting)
        return True

    # 2a. Binnen het pand: een-op-een toewijzen, dichtstbijzijnde paren eerst.
    # Puur "dichtstbijzijnde" liet in een winkelcentrum twintig zaken hetzelfde
    # grote verblijfsobject claimen -- een cafe in Hoog Catharijne kreeg zo
    # 111.292 m². Een verblijfsobject is een adresseerbare eenheid, dus het
    # hoort bij een voorziening. Paren met passend gebruiksdoel gaan eerst, zodat
    # die de schaarse objecten krijgen; wie overblijft valt terug op stap 2c.
    # Alleen gebouwgebonden categorieen krijgen m2. Zonder deze grens pikte een
    # binnenspeeltuin het dichtstbijzijnde verblijfsobject van 34.914 m2 mee.
    def _eligible(i: int) -> bool:
        return categories[i] in EXPECTED_DOEL

    # Wat het adres al exact heeft toegewezen blijft staan; die verblijfsobjecten
    # zijn ook vergeven en doen in de geometrie-stap niet meer mee.
    al_vergeven = set(assigned.values())

    pois_by_pand: Dict[int, List[int]] = {}
    for i, j in poi_to_pand.items():
        if _eligible(i) and i not in assigned:
            pois_by_pand.setdefault(j, []).append(i)

    for j, poi_positions in pois_by_pand.items():
        candidates = [
            k for k in by_pand.get(pand_ids[j], []) if k not in al_vergeven
        ]
        if not candidates:
            continue
        # Een OSM-object dat in twee categorieen valt is een voorziening, geen
        # twee: match op object, verdeel daarna terug over de rijen.
        by_object: Dict[Any, List[int]] = {}
        for i in poi_positions:
            by_object.setdefault(ids[i], []).append(i)

        pairs = []
        for obj, rows in by_object.items():
            first = rows[0]
            pt = poi_geoms[first]
            fitting = set()
            for i in rows:
                fitting.update(_fitting(i, candidates))
            for k in candidates:
                dist2 = (vbo_x[k] - pt.x) ** 2 + (vbo_y[k] - pt.y) ** 2
                # Sorteersleutel: (1) passend gebruiksdoel, (2) afstandsband van
                # 5 m, (3) specificiteit, (4) exacte afstand. De band zorgt dat
                # specificiteit alleen bij ongeveer gelijke afstand de doorslag
                # geeft -- "winkelfunctie" wint dan van "winkelfunctie,
                # woonfunctie" -- zonder een unit 30 m verderop te verkiezen
                # boven de unit pal naast de deur.
                band = int(dist2**0.5 // 5)
                pairs.append(
                    (0 if k in fitting else 1, band, vbo_ndoel[k], dist2, obj, k)
                )
        pairs.sort()

        used_vbo: set = set()
        done_obj: set = set()
        for rank, _band, _nd, _dist2, obj, k in pairs:
            if obj in done_obj or k in used_vbo:
                continue
            done_obj.add(obj)
            used_vbo.add(k)
            for i in by_object[obj]:
                assigned[i] = k
                doel_match[i] = rank == 0

        # 2c. Meer voorzieningen dan verblijfsobjecten: de rest deelt er een.
        # `vbo_share` legt vast met hoeveel, zodat totalen blijven kloppen.
        for obj, rows in by_object.items():
            if obj in done_obj:
                continue
            for i in rows:
                _pick(i, candidates, require_doel=False)

    # 2b. Vlak-POI's (school, sportcomplex) zijn tot hun centroide teruggebracht
    # en die ligt vaak op het terrein i.p.v. in het gebouw. Voor die POI's mag
    # een pand in de buurt meedoen, maar alleen als het gebruiksdoel klopt --
    # anders pikt een speeltuin het eerste schuurtje.
    if nearby_m > 0:
        for i in range(len(out)):
            if i in assigned or not _eligible(i):
                continue
            near = pand_tree.query(poi_geoms[i].buffer(nearby_m), predicate="intersects")
            candidates = [
                k
                for j in near
                for k in by_pand.get(pand_ids[int(j)], [])
                if k not in al_vergeven
            ]
            if candidates and _pick(i, candidates, require_doel=True):
                via_nabij[i] = True

    # 3. Delen meerdere POI's toch een verblijfsobject, dan het aandeel
    # vastleggen. Tellen op OSM-object, niet op rij: een supermarkt zit zowel in
    # "detailhandel (grootschalig)" als in "dagelijkse boodschappen" en zou
    # anders in beide de halve oppervlakte krijgen.
    claimants: Dict[int, set] = {}
    for i, k in assigned.items():
        claimants.setdefault(k, set()).add(ids[i])
    share_count = {k: max(1, len(v)) for k, v in claimants.items()}

    for i, k in assigned.items():
        label = out.index[i]
        go = vbo.iat[k, vbo.columns.get_loc("go_m2")]
        share = 1.0 / share_count[k]
        # bvo_m2 is wat DEZE voorziening beslaat, dus inclusief het aandeel:
        # zitten er twintig zaken in een winkelcentrum dat als een
        # verblijfsobject is geregistreerd, dan is de volle oppervlakte niet van
        # een van hen. De onverdeelde registratie blijft in go_m2 staan.
        bvo = go * GO_TO_BVO * share if pd.notna(go) else np.nan
        out.loc[label, "bag_pand_id"] = vbo.iat[k, vbo.columns.get_loc("pand_id")]
        out.loc[label, "bag_vbo_id"] = vbo.iat[k, vbo.columns.get_loc("vbo_id")]
        out.loc[label, "gebruiksdoel"] = vbo.iat[
            k, vbo.columns.get_loc("gebruiksdoel")
        ]
        out.loc[label, "bouwjaar"] = vbo.iat[k, vbo.columns.get_loc("bouwjaar")]
        out.loc[label, "go_m2"] = go
        out.loc[label, "bvo_m2"] = bvo
        out.loc[label, "vbo_share"] = share
        out.loc[label, "doel_match"] = doel_match.get(i, False)
        out.loc[label, "via_nabij_pand"] = via_nabij.get(i, False)
        out.loc[label, "via_adres"] = via_adres.get(i, False)
    return out


def summarize_by_category(pois: gpd.GeoDataFrame) -> pd.DataFrame:
    """Per categorie: aantal POI's, aantal met m2, en de m2-totalen.

    `bvo_m2` is al aandeel-gecorrigeerd, dus drie winkels in een pand leveren
    samen niet 3x de pand-oppervlakte op.
    """
    if pois is None or len(pois) == 0 or "bvo_m2" not in pois.columns:
        return pd.DataFrame(
            columns=["categorie", "n", "n_met_m2", "dekking_pct",
                     "doel_match_pct", "bvo_m2_totaal", "bvo_m2_mediaan"]
        )
    rows = []
    for cat, sub in pois.groupby("category"):
        has = sub["bvo_m2"].notna()
        rows.append({
            "categorie": cat,
            "n": int(len(sub)),
            "n_met_m2": int(has.sum()),
            "dekking_pct": round(float(has.mean()) * 100, 1),
            "doel_match_pct": (
                round(float(sub.loc[has, "doel_match"].mean()) * 100, 1)
                if has.any() and "doel_match" in sub.columns
                else 0.0
            ),
            "bvo_m2_totaal": float(sub["bvo_m2"].sum(skipna=True)),
            "bvo_m2_mediaan": (
                float(sub.loc[has, "bvo_m2"].median()) if has.any() else np.nan
            ),
        })
    return pd.DataFrame(rows).sort_values("bvo_m2_totaal", ascending=False)
