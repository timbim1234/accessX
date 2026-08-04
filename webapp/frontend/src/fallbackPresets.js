// Kopie van GET /api/presets.
// Wordt alleen gebruikt als de backend (nog) niet bereikbaar is, zodat de UI
// toch kan renderen; er verschijnt dan een waarschuwing in de sidebar.
// De `match`-specs staan hier bewust niet in: de frontend gebruikt alleen
// label + section. Bron van waarheid is webapp/backend/poi_groups.py.
export const FALLBACK_PRESETS = {
  poi_groups: {
    // Functiemix (CityMaker-legenda)
    detailhandel_kls: { label: "Detailhandel (kleinschalig)", section: "functiemix" },
    detailhandel_grs: { label: "Detailhandel (grootschalig)", section: "functiemix" },
    kantoor: { label: "Kantoor", section: "functiemix" },
    bedrijven: { label: "Bedrijven", section: "functiemix" },
    sociaal_cultureel: { label: "Sociaal cultureel", section: "functiemix" },
    sociaal_medisch: { label: "Sociaal medisch", section: "functiemix" },
    basis_onderwijs: { label: "Basisonderwijs", section: "functiemix" },
    voortgezet_onderwijs: { label: "Voortgezet onderwijs", section: "functiemix" },
    onderwijs_overig: { label: "Onderwijs (niveau onbekend / overig)", section: "functiemix" },
    hotel: { label: "Hotel", section: "functiemix" },
    bibliotheek: { label: "Bibliotheek", section: "functiemix" },
    museum: { label: "Museum", section: "functiemix" },
    restaurant: { label: "Restaurant", section: "functiemix" },
    cafe: { label: "Café", section: "functiemix" },
    bioscoop_theater: { label: "Bioscoop / theater", section: "functiemix" },
    sporthal: { label: "Sporthal", section: "functiemix" },
    fitness: { label: "Fitness", section: "functiemix" },
    zwembad: { label: "Zwembad", section: "functiemix" },
    // Bereikbaarheid (15-minutenstad)
    daily_needs: { label: "Dagelijkse boodschappen", section: "bereikbaarheid" },
    kinderopvang: { label: "Kinderopvang", section: "bereikbaarheid" },
    public_transport: { label: "OV-haltes", section: "bereikbaarheid" },
    speeltuinen: { label: "Speeltuinen", section: "bereikbaarheid" },
    parken_natuur: { label: "Parken & natuur", section: "bereikbaarheid" },
    volkstuinen: { label: "Volkstuinen & moestuinen", section: "bereikbaarheid" },
    sport_buiten: { label: "Sportvelden & buitensport", section: "bereikbaarheid" },
  },
  sections: [
    { key: "functiemix", label: "Functiemix" },
    { key: "bereikbaarheid", label: "Bereikbaarheid (15-minutenstad)" },
  ],
  defaults: {
    mode: "walk",
    speed_kmh: 4.5,
    max_minutes: 15,
    hex_resolution: 9,
    selected_groups: [
      "daily_needs",
      "sociaal_medisch",
      "basis_onderwijs",
      "kinderopvang",
      "public_transport",
      "parken_natuur",
      "speeltuinen",
    ],
    analyses: ["counts", "nearest", "hansen", "population", "2sfca", "equity"],
  },
  limits: { max_area_km2: 250, warn_area_km2: 40 },
};
