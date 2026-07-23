// Kopie van GET /api/presets uit CONTRACT.md.
// Wordt alleen gebruikt als de backend (nog) niet bereikbaar is, zodat de UI
// toch kan renderen; er verschijnt dan een waarschuwing in de sidebar.
export const FALLBACK_PRESETS = {
  poi_groups: {
    daily_needs: {
      label: "Dagelijkse boodschappen",
      tags: { shop: ["supermarket", "bakery", "greengrocer", "butcher"], amenity: ["marketplace"] },
    },
    healthcare: {
      label: "Gezondheidszorg",
      tags: { amenity: ["pharmacy", "doctors", "clinic", "hospital", "dentist"] },
    },
    education: {
      label: "Onderwijs",
      tags: { amenity: ["school", "kindergarten"] },
    },
    open_space: {
      label: "Groen & spelen",
      tags: { leisure: ["park", "playground", "garden"] },
    },
    public_transport: {
      label: "OV-haltes",
      tags: { highway: ["bus_stop"], railway: ["station", "tram_stop"], amenity: ["bus_station"] },
    },
    meeting: {
      label: "Horeca & ontmoeten",
      tags: { amenity: ["cafe", "restaurant", "community_centre", "library"] },
    },
    sports: {
      label: "Sport",
      tags: { leisure: ["sports_centre", "fitness_centre", "swimming_pool"] },
    },
  },
  defaults: {
    mode: "walk",
    speed_kmh: 4.5,
    max_minutes: 15,
    hex_resolution: 9,
    selected_groups: ["daily_needs", "healthcare", "education", "open_space", "public_transport"],
    analyses: ["counts", "nearest", "hansen", "population", "2sfca", "equity"],
  },
  limits: { max_area_km2: 100, warn_area_km2: 25 },
};
