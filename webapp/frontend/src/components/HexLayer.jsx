import { GeoJSON } from "react-leaflet";
import { binColor, divergingColor, fmt, metricDecimals, metricGroupKey, metricLabel } from "../metrics.js";

// Choropleth van de hexes voor de geselecteerde metriek. In "verschil"-modus
// (diffData aanwezig) kleurt de laag het verschil scenario − basis met een
// divergent palet (blauw = beter). De laag wordt via `key` in MapView opnieuw
// aangemaakt bij metric-/result-/modewissel.
export default function HexLayer({ data, metric, bins, diffData, presets, groupKeys, onHexClick }) {
  const diffMode = Boolean(diffData);
  // nearest_cost: lager is beter; delta is al richting-gecorrigeerd in App.
  const invert = diffMode && metric.startsWith("nearest_cost_");

  const baseStyle = (feature) => {
    if (diffMode) {
      const val = diffData.values.get(feature?.properties?.hex_id);
      const color = divergingColor(val, diffData.absMax);
      if (color === null) {
        return { fillColor: "#ffffff", fillOpacity: 0, color: "#898781", weight: 1, opacity: 0.7 };
      }
      return { fillColor: color, fillOpacity: 0.78, color: "#ffffff", weight: 1, opacity: 1 };
    }
    const v = feature?.properties?.[metric];
    const color = binColor(bins, typeof v === "number" ? v : null);
    if (color === null) {
      // null -> transparante vulling + grijze hairline
      return { fillColor: "#ffffff", fillOpacity: 0, color: "#898781", weight: 1, opacity: 0.7 };
    }
    return { fillColor: color, fillOpacity: 0.75, color: "#ffffff", weight: 1, opacity: 1 };
  };

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

  const line = (label, value, bold) =>
    `<div class="tt-row${bold ? " tt-main" : ""}"><span>${esc(label)}</span><span class="tt-val">${esc(value)}</span></div>`;

  const tooltipHtml = (props) => {
    const d = metricDecimals(metric);
    if (diffMode) {
      const adj = diffData.values.get(props?.hex_id);
      if (adj === undefined) {
        return `<div class="hex-tooltip">${line(metricLabel(metric, presets), "geen vergelijking", true)}</div>`;
      }
      const scenarioVal = props?.[metric];
      // adj is richting-gecorrigeerd (positief = beter); rawDelta = scenario − basis
      const rawDelta = invert ? -adj : adj;
      const baseVal = typeof scenarioVal === "number" ? scenarioVal - rawDelta : null;
      const rows = [
        line(`${metricLabel(metric, presets)} — verschil`, `${rawDelta > 0 ? "+" : ""}${fmt(rawDelta, d)}`, true),
        line("Basis", fmt(baseVal, d)),
        line("Scenario", fmt(scenarioVal, d)),
      ];
      return `<div class="hex-tooltip">${rows.join("")}</div>`;
    }
    const rows = [line(metricLabel(metric, presets), fmt(props?.[metric], d), true)];
    if (metric !== "population" && props && "population" in props) {
      rows.push(line("Bevolking (CBS)", fmt(props.population, 0)));
    }
    const gk = metricGroupKey(metric, groupKeys);
    if (gk) {
      [`count_${gk}`, `nearest_cost_${gk}_1`, `hansen_${gk}`, `sfca_${gk}`].forEach((m2) => {
        if (m2 !== metric && props && m2 in props) {
          rows.push(line(metricLabel(m2, presets), fmt(props[m2], metricDecimals(m2))));
        }
      });
    }
    return `<div class="hex-tooltip">${rows.join("")}</div>`;
  };

  const onEachFeature = (feature, layer) => {
    layer.bindTooltip(tooltipHtml(feature.properties), { sticky: true, direction: "top" });
    layer.on({
      mouseover: () => layer.setStyle({ color: "#0b0b0b", weight: 1.5 }),
      mouseout: () => {
        const s = baseStyle(feature);
        layer.setStyle({ color: s.color, weight: s.weight, opacity: s.opacity });
      },
      click: () => {
        const hexId = feature?.properties?.hex_id;
        if (hexId !== null && hexId !== undefined) onHexClick(hexId);
      },
    });
  };

  return <GeoJSON data={data} style={baseStyle} onEachFeature={onEachFeature} />;
}
