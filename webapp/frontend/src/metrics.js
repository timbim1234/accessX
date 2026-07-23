// Metriek-helpers: labels, eenheden, kleuren, bins en NL-getalnotatie.

// Sequentiële ramp uit CONTRACT.md (licht -> donker = laag -> hoog).
export const RAMP = ["#cde2fb", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"];

// Categoriale POI-kleuren in VASTE volgorde van de presets-keys.
export const CAT_COLORS = [
  "#2a78d6", // 1 blue
  "#eb6834", // 2 orange
  "#1baf7a", // 3 aqua
  "#eda100", // 4 yellow
  "#e87ba4", // 5 magenta
  "#008300", // 6 green
  "#4a3aa7", // 7 violet
  "#e34948", // 8 red
];

// Vaste kleur per groep-key, in de volgorde waarin de presets de keys leveren.
// De kleur hoort bij de key en verandert nooit bij aan/uitzetten van groepen.
export function groupColors(presets) {
  const map = {};
  Object.keys(presets?.poi_groups || {}).forEach((key, i) => {
    map[key] = CAT_COLORS[i % CAT_COLORS.length];
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
  if (metric === "sufficient_score") return "Sufficiëntiescore";
  if (metric === "hansen_total") return "Hansen: totaal";
  if (metric === "sfca_total") return "2SFCA: totaal";
  const gk = metricGroupKey(metric, Object.keys(groups));
  if (gk) {
    const gl = groups[gk].label;
    if (metric === `count_${gk}`) return `Aantal bereikbaar: ${gl}`;
    if (metric === `nearest_cost_${gk}_1`) return `Minuten naar dichtstbijzijnde: ${gl}`;
    if (metric === `hansen_${gk}`) return `Hansen: ${gl}`;
    if (metric === `sfca_${gk}`) return `2SFCA: ${gl}`;
    if (metric === `count_${gk}_sufficient`) return `Drempel gehaald: ${gl}`;
  }
  return metric;
}

export function metricUnit(metric) {
  if (metric.startsWith("count_") && !metric.endsWith("_sufficient")) return "aantal";
  if (metric.startsWith("nearest_cost_")) return "minuten";
  if (metric === "population" || metric.startsWith("pop_")) return "inwoners";
  return "score";
}

export function metricDecimals(metric) {
  if (metric.startsWith("count_")) return 0;
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
    if (options.length) out.push({ label: g.label, options });
  }
  const general = [];
  if ("hansen_total" in props) general.push({ value: "hansen_total", label: "Hansen: totaal" });
  if ("sfca_total" in props) general.push({ value: "sfca_total", label: "2SFCA: totaal" });
  if ("population" in props) general.push({ value: "population", label: "Bevolking (CBS)" });
  if ("sufficient_score" in props) general.push({ value: "sufficient_score", label: "Sufficiëntiescore" });
  if (general.length) out.push({ label: "Algemeen", options: general });
  return out;
}
