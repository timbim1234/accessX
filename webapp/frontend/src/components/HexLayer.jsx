import { GeoJSON } from "react-leaflet";
import { binColor, fmt, metricDecimals, metricGroupKey, metricLabel } from "../metrics.js";

// Choropleth van de hexes voor de geselecteerde metriek.
// De laag wordt via `key` in MapView opnieuw aangemaakt bij metric-/resultwissel.
export default function HexLayer({ data, metric, bins, presets, groupKeys, onHexClick }) {
  const baseStyle = (feature) => {
    const v = feature?.properties?.[metric];
    const color = binColor(bins, typeof v === "number" ? v : null);
    if (color === null) {
      // null -> transparante vulling + grijze hairline
      return { fillColor: "#ffffff", fillOpacity: 0, color: "#898781", weight: 1, opacity: 0.7 };
    }
    return { fillColor: color, fillOpacity: 0.75, color: "#ffffff", weight: 1, opacity: 1 };
  };

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

  const tooltipHtml = (props) => {
    const line = (label, value, bold) =>
      `<div class="tt-row${bold ? " tt-main" : ""}"><span>${esc(label)}</span><span class="tt-val">${esc(value)}</span></div>`;
    const rows = [line(metricLabel(metric, presets), fmt(props?.[metric], metricDecimals(metric)), true)];
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
