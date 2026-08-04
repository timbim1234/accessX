// Metriek-helpers: labels, eenheden, kleuren, bins en NL-getalnotatie.

// Sequentiële choropleth-ramp (CityMaker sky, licht -> donker = laag -> hoog).
export const RAMP = ["#e5f4fd", "#b1ddfa", "#7dc6f6", "#38a7f0", "#1466a8"];

// Categoriale reservekleuren = CityMaker data-palet "strong"
// (voor onbekende keys die niet in GROUP_COLORS staan).
export const CAT_COLORS = [
  "#38a7f0", // sky
  "#f07d68", // rose
  "#efa35a", // apricot
  "#51d686", // sage
  "#58d4c9", // teal
  "#f2d245", // sand
  "#9898f2", // lavender
  "#df7af6", // orchid
];

// Vaste kleur per groep-key (CityMaker data-palet "strong"). De kleur hoort bij de
// key en verandert nooit bij aan/uitzetten van groepen. Verwante categorieën delen
// een kleurfamilie: onderwijs in apricot-tinten, horeca in orchid, sport in
// graphite, groen in sage/teal/zand.
export const GROUP_COLORS = {
  // Functiemix
  detailhandel_kls: "#38a7f0", // sky
  detailhandel_grs: "#1466a8", // sky-donker
  kantoor: "#6f6f78", // clay-70
  bedrijven: "#8f8f96", // graphite
  sociaal_cultureel: "#df7af6", // orchid
  sociaal_medisch: "#f07d68", // rose
  basis_onderwijs: "#efa35a", // apricot
  voortgezet_onderwijs: "#c97d2e", // apricot-donker
  onderwijs_overig: "#e8c9a0", // apricot-licht
  hotel: "#b07af6", // violet
  bibliotheek: "#9898f2", // lavender
  museum: "#7a7ae0", // lavender-donker
  restaurant: "#f2a0b8", // rose-licht
  cafe: "#e07a9c", // rose-mid
  bioscoop_theater: "#c25a8f", // magenta
  sporthal: "#5a6a78", // slate
  fitness: "#7d95a8", // slate-licht
  zwembad: "#38c0d6", // cyaan
  // Bereikbaarheid
  daily_needs: "#2b8fd6", // sky-mid
  kinderopvang: "#f2d245", // sand
  public_transport: "#9898f2", // lavender
  speeltuinen: "#58d4c9", // teal
  parken_natuur: "#51d686", // sage
  volkstuinen: "#a8c94a", // olijf
  sport_buiten: "#3fa86a", // sage-donker
  // Legacy-keys (resultaten/exports van vóór de legenda-indeling)
  healthcare: "#f07d68",
  education: "#efa35a",
  meeting: "#df7af6",
  sports: "#8f8f96",
  open_space: "#51d686",
};

// Kleur-map voor de keys die de presets leveren: expliciete kleur waar bekend,
// anders een reservekleur op volgorde van binnenkomst.
export function groupColors(presets) {
  const map = {};
  let fallback = 0;
  Object.keys(presets?.poi_groups || {}).forEach((key) => {
    if (GROUP_COLORS[key]) {
      map[key] = GROUP_COLORS[key];
    } else {
      map[key] = CAT_COLORS[fallback % CAT_COLORS.length];
      fallback += 1;
    }
  });
  return map;
}

// NL-getalnotatie (komma als decimaalteken); null/NaN -> "–".
export function fmt(value, maxDecimals = 2, minDecimals = 0) {
  const n = typeof value === "string" ? Number(value) : value;
  if (n === null || n === undefined || typeof n !== "number" || !Number.isFinite(n)) return "–";
  return n.toLocaleString("nl-NL", {
    maximumFractionDigits: maxDecimals,
    minimumFractionDigits: minDecimals,
  });
}

// Groep-key uit een metriek-kolomnaam (keys bevatten underscores, dus exact matchen).
export function metricGroupKey(metric, groupKeys) {
  for (const k of groupKeys) {
    if (
      metric === `count_${k}` ||
      metric === `nearest_cost_${k}_1` ||
      metric === `hansen_${k}` ||
      metric === `sfca_${k}` ||
      metric === `bvo_hansen_${k}` ||
      metric === `count_${k}_sufficient`
    ) {
      return k;
    }
  }
  return null;
}

export function metricLabel(metric, presets) {
  const groups = presets?.poi_groups || {};
  if (metric === "population") return "Bevolking (CBS)";
  if (metric === "sufficient_score") return "15-minutenstad-score (0–1)";
  if (metric === "groen_afstand_m") return "Loopafstand tot groen (m)";
  if (metric === "groen_binnen_300m") return "Groen binnen 300 m (ja/nee)";
  if (metric === "hansen_total") return "Hansen: totaal";
  if (metric === "sfca_total") return "2SFCA: totaal";
  const gk = metricGroupKey(metric, Object.keys(groups));
  if (gk) {
    const gl = groups[gk].label;
    if (metric === `count_${gk}`) return `Aantal bereikbaar: ${gl}`;
    if (metric === `nearest_cost_${gk}_1`) return `Minuten naar dichtstbijzijnde: ${gl}`;
    if (metric === `hansen_${gk}`) return `Hansen: ${gl}`;
    if (metric === `sfca_${gk}`) return `2SFCA: ${gl}`;
    if (metric === `bvo_hansen_${gk}`) return `Bereikbaar vloeroppervlak: ${gl}`;
    if (metric === `count_${gk}_sufficient`) return `Drempel gehaald: ${gl}`;
  }
  return metric;
}

export function metricUnit(metric) {
  if (metric === "groen_afstand_m") return "meter";
  if (metric === "groen_binnen_300m") return "1 = ja";
  if (metric.startsWith("bvo_")) return "m²";
  if (metric.startsWith("count_") && !metric.endsWith("_sufficient")) return "aantal";
  if (metric.startsWith("nearest_cost_")) return "minuten";
  if (metric === "population" || metric.startsWith("pop_")) return "inwoners";
  return "score";
}

export function metricDecimals(metric) {
  if (metric.startsWith("groen_")) return 0;
  if (metric.startsWith("count_")) return 0;
  if (metric.startsWith("bvo_")) return 0;
  if (metric === "population" || metric.startsWith("pop_")) return 0;
  if (metric.startsWith("nearest_cost_")) return 1;
  return 2;
}

// 5 quantile-bins over niet-null waarden; < 5 unieke waarden -> per unieke waarde.
export function computeBins(values) {
  const v = (values || [])
    .filter((x) => x !== null && x !== undefined && typeof x === "number" && Number.isFinite(x))
    .sort((a, b) => a - b);
  if (!v.length) return null;
  const uniq = [...new Set(v)];
  if (uniq.length <= 5) {
    const colors =
      uniq.length === 1
        ? [RAMP[2]]
        : uniq.map((_, i) => RAMP[Math.round((i * (RAMP.length - 1)) / (uniq.length - 1))]);
    return { mode: "unique", levels: uniq, colors };
  }
  const breaks = [];
  for (let i = 1; i < 5; i++) {
    breaks.push(v[Math.min(v.length - 1, Math.floor((i * v.length) / 5))]);
  }
  return { mode: "quantile", breaks, min: v[0], max: v[v.length - 1] };
}

export function binColor(bins, value) {
  if (!bins || value === null || value === undefined || typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  if (bins.mode === "unique") {
    let idx = bins.levels.findIndex((l) => value <= l);
    if (idx === -1) idx = bins.levels.length - 1;
    return bins.colors[idx];
  }
  const i = bins.breaks.findIndex((b) => value <= b);
  return RAMP[i === -1 ? RAMP.length - 1 : i];
}

// Metric-opties voor de kiezer: alleen wat echt in de data zit
// (props van de eerste hex-feature scannen), gegroepeerd per voorzieningengroep.
export function buildMetricOptions(result, presets) {
  const props = result?.hexes?.features?.[0]?.properties;
  if (!props || !presets) return [];
  const out = [];
  for (const [key, g] of Object.entries(presets.poi_groups || {})) {
    const options = [];
    if (`count_${key}` in props) {
      options.push({ value: `count_${key}`, label: `Aantal bereikbaar: ${g.label}` });
    }
    if (`nearest_cost_${key}_1` in props) {
      options.push({ value: `nearest_cost_${key}_1`, label: `Minuten naar dichtstbijzijnde: ${g.label}` });
    }
    if (`hansen_${key}` in props) {
      options.push({ value: `hansen_${key}`, label: `Hansen: ${g.label}` });
    }
    if (`sfca_${key}` in props) {
      options.push({ value: `sfca_${key}`, label: `2SFCA: ${g.label}` });
    }
    if (`bvo_hansen_${key}` in props) {
      options.push({
        value: `bvo_hansen_${key}`,
        label: `Bereikbaar vloeroppervlak: ${g.label}`,
      });
    }
    if (options.length) out.push({ label: g.label, options });
  }
  const general = [];
  if ("groen_afstand_m" in props) {
    general.push({ value: "groen_afstand_m", label: "Loopafstand tot groen (m)" });
  }
  if ("groen_binnen_300m" in props) {
    general.push({ value: "groen_binnen_300m", label: "Groen binnen 300 m (ja/nee)" });
  }
  if ("hansen_total" in props) general.push({ value: "hansen_total", label: "Hansen: totaal" });
  if ("sfca_total" in props) general.push({ value: "sfca_total", label: "2SFCA: totaal" });
  if ("population" in props) general.push({ value: "population", label: "Bevolking (CBS)" });
  if ("sufficient_score" in props) general.push({ value: "sufficient_score", label: "15-minutenstad-score (0–1)" });
  if (general.length) out.push({ label: "Algemeen", options: general });
  return out;
}

// Divergent palet (uit dataviz palette.md) voor het verschil scenario − basis.
// Index 0 = sterk beter (donkerblauw) … index 4 = sterk slechter (donkerrood),
// met een neutrale grijze midden (index 2) rond 0.
export const DIVERGING = ["#1466a8", "#7dc6f6", "#e4e7ee", "#f0a491", "#e0533c"];

// Kleur voor een reeds richting-gecorrigeerde delta (positief = beter) op een
// symmetrische schaal rond 0; `absMax` bepaalt de uitersten. 5 discrete stappen,
// consistent met de choropleth-stijl. Kleine deltas -> grijs.
export function divergingColor(value, absMax) {
  if (value === null || value === undefined || typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  if (!absMax || absMax <= 0) return DIVERGING[2];
  const t = Math.max(-1, Math.min(1, value / absMax)); // -1 (slechter) .. +1 (beter)
  const idx = Math.round(2 - 2 * t); // t=+1 -> 0 (blauw), t=0 -> 2 (grijs), t=-1 -> 4 (rood)
  return DIVERGING[Math.max(0, Math.min(DIVERGING.length - 1, idx))];
}

// Verschil per hex: scenario[metric] − baseline[metric], gematcht op hex_id.
// Alleen hexes die in BEIDE zitten en in beide een eindig getal hebben.
// Richting-correctie (nearest_cost: lager is beter) gebeurt bij het kleuren.
export function computeDelta(baselineFeatures, scenarioFeatures, metric) {
  const out = new Map();
  if (!metric || !Array.isArray(baselineFeatures) || !Array.isArray(scenarioFeatures)) return out;
  const base = new Map();
  for (const f of baselineFeatures) {
    const id = f?.properties?.hex_id;
    const v = f?.properties?.[metric];
    if (id !== null && id !== undefined && typeof v === "number" && Number.isFinite(v)) {
      base.set(id, v);
    }
  }
  for (const f of scenarioFeatures) {
    const id = f?.properties?.hex_id;
    const v = f?.properties?.[metric];
    if (id === null || id === undefined || typeof v !== "number" || !Number.isFinite(v)) continue;
    if (!base.has(id)) continue;
    out.set(id, v - base.get(id));
  }
  return out;
}
