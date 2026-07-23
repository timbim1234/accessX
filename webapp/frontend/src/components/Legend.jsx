import { RAMP, fmt, metricDecimals, metricLabel, metricUnit } from "../metrics.js";

// Kaartlegenda rechtsonder: metric-titel + eenheid, 5 kleurblokjes met bin-bereiken,
// optionele null-swatch. Donker = hogere waarde.
export default function Legend({ metric, bins, presets, hasNulls, maxMinutes }) {
  const d = metricDecimals(metric);
  const isNearest = metric.startsWith("nearest_cost_");
  const title = `${metricLabel(metric, presets)} (${metricUnit(metric)})${isNearest ? " — lager is beter" : ""}`;

  let items;
  if (bins.mode === "unique") {
    items = bins.levels.map((l, i) => ({ color: bins.colors[i], text: fmt(l, d) }));
  } else {
    const edges = [bins.min, ...bins.breaks, bins.max];
    items = RAMP.map((c, i) => ({ color: c, text: `${fmt(edges[i], d)} – ${fmt(edges[i + 1], d)}` }));
  }

  return (
    <div className="legend">
      <div className="legend-title">{title}</div>
      {items.map((it, i) => (
        <div key={i} className="legend-row">
          <span className="swatch" style={{ background: it.color }} />
          <span>{it.text}</span>
        </div>
      ))}
      {hasNulls && (
        <div className="legend-row">
          <span className="swatch null" />
          <span>{isNearest ? `niet bereikbaar binnen ${maxMinutes} min` : "geen waarde"}</span>
        </div>
      )}
      <div className="legend-note">donker = hogere waarde</div>
    </div>
  );
}
