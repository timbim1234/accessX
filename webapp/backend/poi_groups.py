"""Voorzieningencategorieen (POI-groepen) en de tag-matcher, als losse module.

Deze module is bewust dependency-vrij (geen pandas/geopandas/osmnx), zodat zowel
`analysis.py` (webapp-pipeline) als `prepare_local_data.py` (pbf-prep, draait
zonder de zware stack) dezelfde definities gebruiken. Eendere definities zijn
essentieel: de categorie wordt in pois.parquet gebakken, dus prep en runtime
moeten exact hetzelfde matchen.

Indeling volgt de CityMaker-functiemixlegenda (sectie "functiemix"), aangevuld
met de categorieen die voor een 15-minutenstad-analyse nodig zijn maar niet in
die legenda staan (sectie "bereikbaarheid").

Matcher-grammatica -- een `match`-spec is een van:
    {"amenity": ["school"], "shop": True}   leaf: OR over (key, waarde)-paren
    {"any": [spec, ...]}                    OR
    {"all": [spec, ...]}                    AND
    {"not": spec}                           NOT

Waarden per key: True (key aanwezig, elke waarde), een string, of een lijst.

LET OP bij "all": zet de meest selectieve voorwaarde vooraan. `query_tags()`
gebruikt alleen het eerste kind van een "all" om de Overpass-query op te bouwen
(elke AND-voorwaarde op zich levert al een superset; het eerste kind is de
selectiefste). Zou `access` vooraan staan bij `zwembad`, dan haalde de
Overpass-query elk pad met access=yes op.

Code en commentaar Engels/Nederlands gemengd conform de rest van de backend;
user-facing labels zijn Nederlands.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Herbruikbare waardelijsten
# ---------------------------------------------------------------------------

# Grootschalige detailhandel (perifeer/volumineus). De rest van shop=* valt
# onder kleinschalige detailhandel.
SHOP_GROOTSCHALIG: List[str] = [
    "supermarket",
    "department_store",
    "mall",
    "doityourself",
    "furniture",
    "garden_centre",
    "car",
    "caravan",
    "boat",
    "truck",
    "motorcycle",
    "trade",
    "wholesale",
    "kitchen",
    "bed",
    "carpet",
    "tiles",
    "agrarian",
]

# Onderwijsniveau. OSM-NL tagt dit met isced:level en/of de NL-specifieke
# `school`-key; beide zijn maar op ~50% van de scholen ingevuld (gemeten op de
# NL-extract), vandaar de aparte restcategorie `onderwijs_overig`.
# Combinatiewaarden ("0-2") tellen bewust in beide niveaus mee: dat zijn brede
# scholen / scholengemeenschappen.
ISCED_BASIS: List[str] = [
    "0", "1", "0;1", "0,1", "0-1", "1;2", "0;2", "0-2", "0-3", "0-4",
    "0;1;2", "1-3", "1;2;3",
]
ISCED_VO: List[str] = [
    "2", "3", "2;3", "2-3", "1;2", "0;2", "0-2", "0-3", "0-4", "3;4",
    "2;3;4", "0;1;2", "1-3", "1;2;3", "3;4",
]
SCHOOL_BASIS: List[str] = [
    "primary", "primary;secondary", "kindergarten;primary", "primary;kindergarten",
]
SCHOOL_VO: List[str] = [
    "secondary", "primary;secondary", "secondary;college", "vocational",
]

# Deelspecs voor onderwijs, hergebruikt in de restcategorie.
_BASIS_NIVEAU: Dict[str, Any] = {
    "any": [{"isced:level": ISCED_BASIS}, {"school": SCHOOL_BASIS}]
}
_VO_NIVEAU: Dict[str, Any] = {
    "any": [{"isced:level": ISCED_VO}, {"school": SCHOOL_VO}]
}

# ---------------------------------------------------------------------------
# Categorieen
# ---------------------------------------------------------------------------

SECTIONS: List[Dict[str, str]] = [
    {"key": "functiemix", "label": "Functiemix"},
    {"key": "bereikbaarheid", "label": "Bereikbaarheid (15-minutenstad)"},
]

POI_GROUPS: Dict[str, Dict[str, Any]] = {
    # --- Functiemix (CityMaker-legenda) ------------------------------------
    "detailhandel_kls": {
        "label": "Detailhandel (kleinschalig)",
        "section": "functiemix",
        "match": {
            "all": [
                {"shop": True},
                {"not": {"shop": SHOP_GROOTSCHALIG + ["vacant", "no"]}},
            ]
        },
    },
    "detailhandel_grs": {
        "label": "Detailhandel (grootschalig)",
        "section": "functiemix",
        "match": {"shop": SHOP_GROOTSCHALIG},
    },
    "kantoor": {
        "label": "Kantoor",
        "section": "functiemix",
        "match": {"office": True, "building": ["office"]},
    },
    "bedrijven": {
        "label": "Bedrijven",
        "section": "functiemix",
        # building=industrial (154k in NL) is bewust weggelaten: dat zit ook op
        # schuren en loodsen en zou de categorie onbruikbaar maken.
        "match": {
            "landuse": ["industrial"],
            "craft": True,
            "man_made": ["works"],
            "building": ["warehouse"],
        },
    },
    "sociaal_cultureel": {
        "label": "Sociaal cultureel",
        "section": "functiemix",
        "match": {
            "amenity": [
                "community_centre",
                "social_centre",
                "arts_centre",
                "events_venue",
                "music_venue",
                "youth_centre",
                "conference_centre",
            ],
            "social_facility": [
                "community_centre",
                "outreach",
                "food_bank",
                "clothing_bank",
                "social_club",
                "workshop",
            ],
        },
    },
    "sociaal_medisch": {
        "label": "Sociaal medisch",
        "section": "functiemix",
        "match": {
            "healthcare": True,
            "amenity": [
                "doctors", "dentist", "pharmacy", "clinic", "hospital",
                "nursing_home", "social_facility",
            ],
            "social_facility": [
                "nursing_home", "assisted_living", "group_home", "day_care",
                "ambulatory_care", "hospice", "shelter",
            ],
            "shop": ["optician", "hearing_aids", "medical_supply"],
        },
    },
    "basis_onderwijs": {
        "label": "Basisonderwijs",
        "section": "functiemix",
        "match": {"all": [{"amenity": ["school"]}, _BASIS_NIVEAU]},
    },
    "voortgezet_onderwijs": {
        "label": "Voortgezet onderwijs",
        "section": "functiemix",
        "match": {"all": [{"amenity": ["school"]}, _VO_NIVEAU]},
    },
    "onderwijs_overig": {
        "label": "Onderwijs (niveau onbekend / overig)",
        "section": "functiemix",
        "match": {
            "any": [
                {
                    "all": [
                        {"amenity": ["school"]},
                        {"not": {"any": [_BASIS_NIVEAU, _VO_NIVEAU]}},
                    ]
                },
                {
                    "amenity": [
                        "college", "university", "music_school", "language_school",
                        "prep_school", "dancing_school", "research_institute",
                    ]
                },
                {"office": ["educational_institution"]},
            ]
        },
    },
    "hotel": {
        "label": "Hotel",
        "section": "functiemix",
        "match": {"tourism": ["hotel", "guest_house", "hostel", "motel"]},
    },
    "bibliotheek": {
        "label": "Bibliotheek",
        "section": "functiemix",
        "match": {"amenity": ["library"]},
    },
    "museum": {
        "label": "Museum",
        "section": "functiemix",
        "match": {"tourism": ["museum", "gallery"]},
    },
    "restaurant": {
        "label": "Restaurant",
        "section": "functiemix",
        "match": {"amenity": ["restaurant", "fast_food", "food_court", "ice_cream"]},
    },
    "cafe": {
        "label": "Café",
        "section": "functiemix",
        "match": {"amenity": ["cafe", "bar", "pub", "biergarten", "nightclub"]},
    },
    "bioscoop_theater": {
        "label": "Bioscoop / theater",
        "section": "functiemix",
        "match": {"amenity": ["cinema", "theatre"]},
    },
    "sporthal": {
        "label": "Sporthal",
        "section": "functiemix",
        "match": {"leisure": ["sports_hall", "sports_centre"]},
    },
    "fitness": {
        "label": "Fitness",
        "section": "functiemix",
        "match": {"leisure": ["fitness_centre"]},
    },
    "zwembad": {
        "label": "Zwembad",
        "section": "functiemix",
        # NIET leisure=swimming_pool los: dat zijn in NL vooral particuliere
        # tuinbaden (5.525 objecten, waarvan maar 265 met naam en 2.322
        # expliciet access=private/customers/no). Een openbaar zwembad is
        # sport=swimming op een sports_centre/water_park, of een bad dat
        # expliciet openbaar toegankelijk is.
        "match": {
            "any": [
                {
                    "all": [
                        {"sport": ["swimming"]},
                        {"leisure": ["sports_centre", "water_park", "swimming_pool"]},
                    ]
                },
                {"amenity": ["public_bath"]},
                {"leisure": ["water_park"]},
                {
                    "all": [
                        {"leisure": ["swimming_pool"]},
                        {"access": ["yes", "public", "permissive"]},
                    ]
                },
            ]
        },
    },
    # --- Bereikbaarheid (15-minutenstad) -----------------------------------
    # Deze categorieen staan niet in de functiemixlegenda, maar zonder hen
    # verliest de 15-minutenstad-analyse haar kern (boodschappen, OV, groen).
    "daily_needs": {
        "label": "Dagelijkse boodschappen",
        "section": "bereikbaarheid",
        "match": {
            "shop": [
                "supermarket", "bakery", "greengrocer", "butcher", "convenience",
                "chemist", "deli", "cheese", "seafood", "pastry", "confectionery",
                "kiosk", "farm", "general", "grocery", "health_food", "beverages",
                "dairy",
            ],
            "amenity": ["marketplace"],
        },
    },
    "kinderopvang": {
        "label": "Kinderopvang",
        "section": "bereikbaarheid",
        "match": {
            "amenity": ["childcare", "kindergarten"],
            "social_facility": ["day_care", "daycare"],
        },
    },
    "public_transport": {
        "label": "OV-haltes",
        "section": "bereikbaarheid",
        # public_transport=platform/stop_position bewust NIET: dat zijn
        # grotendeels dezelfde haltes als highway=bus_stop (dubbeltelling).
        "match": {
            "highway": ["bus_stop"],
            "railway": ["station", "tram_stop", "halt", "subway_entrance"],
            "amenity": ["bus_station", "ferry_terminal"],
        },
    },
    "speeltuinen": {
        "label": "Speeltuinen",
        "section": "bereikbaarheid",
        "match": {
            "all": [
                {"leisure": ["playground", "indoor_play"]},
                {"not": {"access": ["private", "customers", "no"]}},
            ]
        },
    },
    "parken_natuur": {
        "label": "Parken & natuur",
        "section": "bereikbaarheid",
        # landuse=forest / natural=wood bewust weggelaten: dat levert 678.000
        # "voorzieningen" op (elk bosperceel en elke berm) en een centroide is
        # daar sowieso een slechte proxy voor bereikbaarheid.
        "match": {
            "leisure": [
                "park", "nature_reserve", "recreation_ground", "dog_park", "common",
            ],
            "landuse": ["recreation_ground", "village_green"],
        },
    },
    "volkstuinen": {
        "label": "Volkstuinen & moestuinen",
        "section": "bereikbaarheid",
        "match": {"landuse": ["allotments"]},
    },
    "sport_buiten": {
        "label": "Sportvelden & buitensport",
        "section": "bereikbaarheid",
        "match": {
            "leisure": [
                "pitch", "track", "fitness_station", "horse_riding",
                "golf_course", "ice_rink", "stadium", "swimming_area",
            ]
        },
    },
}

# Standaardselectie: breed genoeg voor een zinvolle 15-minutenstad-analyse,
# klein genoeg om snel te blijven (kosten schalen lineair met het aantal
# categorieen).
DEFAULT_SELECTED: List[str] = [
    "daily_needs",
    "sociaal_medisch",
    "basis_onderwijs",
    "kinderopvang",
    "public_transport",
    "parken_natuur",
    "speeltuinen",
]


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------

def _leaf_matches(tags: Any, spec: Dict[str, Any]) -> bool:
    for key, values in spec.items():
        if key not in tags:
            continue
        if values is True:
            return True
        value = tags[key]
        if isinstance(values, str):
            if value == values:
                return True
        elif value in values:
            return True
    return False


def matches(tags: Any, spec: Dict[str, Any]) -> bool:
    """True als `tags` (dict of osmium TagList) aan `spec` voldoet."""
    if "any" in spec:
        return any(matches(tags, sub) for sub in spec["any"])
    if "all" in spec:
        return all(matches(tags, sub) for sub in spec["all"])
    if "not" in spec:
        return not matches(tags, spec["not"])
    return _leaf_matches(tags, spec)


def match_groups(tags: Any, groups: Dict[str, Dict[str, Any]] | None = None) -> List[str]:
    """Alle categorieen waar dit object in valt (een object kan er meerdere zijn).

    Voor de standaardcategorieen loopt dit via een key-index: alleen groepen die
    op een van de aanwezige tag-keys kunnen matchen worden echt geevalueerd. De
    pbf-prep roept dit voor elk object in de extract aan (~100 mln), dus alle 25
    specs per object evalueren maakte de NL-prep ruim een uur langer.
    """
    if groups is None:
        groups = POI_GROUPS
    if groups is not POI_GROUPS:
        return [key for key, spec in groups.items() if matches(tags, spec["match"])]

    candidates: set = set()
    if isinstance(tags, dict):
        for key in tags:
            hit = _KEY_TO_GROUPS.get(key)
            if hit:
                candidates.update(hit)
    else:  # osmium TagList
        for tag in tags:
            hit = _KEY_TO_GROUPS.get(tag.k)
            if hit:
                candidates.update(hit)
    if not candidates:
        return []
    return [
        key
        for key, spec in POI_GROUPS.items()
        if key in candidates and matches(tags, spec["match"])
    ]


# ---------------------------------------------------------------------------
# Overpass-query opbouwen
# ---------------------------------------------------------------------------

def _collect_query_tags(spec: Dict[str, Any], out: Dict[str, Any]) -> None:
    if "not" in spec:
        # Een negatie kan niets aan de query toevoegen (en zou hem verbreden).
        return
    if "any" in spec:
        for sub in spec["any"]:
            _collect_query_tags(sub, out)
        return
    if "all" in spec:
        # Elke AND-voorwaarde is op zich een superset; neem alleen de eerste
        # (per conventie de selectiefste).
        if spec["all"]:
            _collect_query_tags(spec["all"][0], out)
        return
    for key, values in spec.items():
        if values is True or out.get(key) is True:
            out[key] = True
            continue
        vals = [values] if isinstance(values, str) else list(values)
        out[key] = sorted(set(out.get(key, [])) | set(vals))


def query_tags(selected: List[str], groups: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Eén OSM-tagdict die een superset van alle geselecteerde groepen ophaalt."""
    groups = POI_GROUPS if groups is None else groups
    out: Dict[str, Any] = {}
    for key in selected:
        if key in groups:
            _collect_query_tags(groups[key]["match"], out)
    return out


def necessary_keys(spec: Dict[str, Any]) -> set:
    """Tag-keys waarvan er minstens een aanwezig moet zijn om te kunnen matchen.

    Volgt dezelfde wandeling als de Overpass-query: negaties tellen niet mee, en
    van een "all" alleen het eerste (per conventie noodzakelijke) kind. Daarmee
    is dit een correcte voorfilter: mist een object al deze keys, dan kan de
    spec onmogelijk matchen.
    """
    out: Dict[str, Any] = {}
    _collect_query_tags(spec, out)
    return set(out)


# Key -> groepen die op die key kunnen matchen (voorfilter voor match_groups).
_KEY_TO_GROUPS: Dict[str, List[str]] = {}
for _group, _spec in POI_GROUPS.items():
    _keys = necessary_keys(_spec["match"])
    if not _keys:
        raise ValueError(
            f"Categorie {_group!r} heeft geen noodzakelijke tag-key; zet de "
            "positieve voorwaarde vooraan in de 'all'-lijst."
        )
    for _key in _keys:
        _KEY_TO_GROUPS.setdefault(_key, []).append(_group)

#: Alle tag-keys die de matcher uberhaupt kan gebruiken.
MATCH_KEYS = frozenset(_KEY_TO_GROUPS)
