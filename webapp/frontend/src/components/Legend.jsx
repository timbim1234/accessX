import { DIVERGING, RAMP, fmt, metricDecimals, metricLabel, metricUnit } from "../metrics.js";

// Kaartlegenda rechtsonder. In "verschil"-modus (diffData) een divergente
// legenda rond 0 (blauw = beter); anders de sequentiële bin-legenda.
export default function Legend({ metric, bins, diffData, presets, hasNulls, maxMinutes }) {
  const d = metricDecimals(metric);

  if (diffData) {
    const M = diffData.absMax;
    const unit = metricUnit(metric);
    let items;
    if (!M || M <= 0) {
      items = [{ color: DIVERGING[2], text: "geen verschil" }];
    } else {
      items = [
        { color: DIVERGING[0], text: `≥ +${fmt(0.75 * M, d)}` },
        { color: DIVERGING[1], text: `+${fmt(0.25 * M, d)} – +${fmt(0.75 * M, d)}` },
        { color: DIVERGING[2], text: "≈ 0" },
        { color: DIVERGING[3], text: `−${fmt(0.75 * M, d)} – −${fmt(0.25 * M, d)}` },
        { color: DIVERGING[4], text: `≤ −${fmt(0.75 * M, d)}` },
      ];
    }
    return (
      <div className="legend">
        <div className="legend-title">Verschil t.o.v. basis (blauw = beter)</div>
        {items.map((it, i) => (
          <div key={i} className="legend-row">
            <span className="swatch" style={{ background: it.color }} />
            <span>{it.text}</span>
          </div>
        ))}
        {hasNulls && (
          <div className="legend-row">
            <span className="swatch null" />
            <span>geen vergelijking</span>
          </div>
        )}
        <div className="legend-note">
          blauw = beter · rood = slechter{unit ? ` · ${unit}` : ""}
        </div>
      </div>
    );
  }

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
