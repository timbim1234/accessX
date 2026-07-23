import { GeoJSON } from "react-leaflet";
import { RAMP } from "../metrics.js";

// Isochroonringen: van buiten (grootste drempel, licht) naar binnen (kleinste, donker).
export default function IsochroneLayer({ data }) {
  const features = [...(data?.rings?.features || [])];
  const thresholds = [...new Set(features.map((f) => f?.properties?.threshold))].sort((a, b) => a - b);
  // Grootste ringen eerst tekenen zodat kleinere ringen erbovenop liggen.
  features.sort((a, b) => (b?.properties?.threshold ?? 0) - (a?.properties?.threshold ?? 0));

  const colorFor = (t) => {
    const i = thresholds.indexOf(t);
    if (i === -1 || thresholds.length === 1) return RAMP[RAMP.length - 1];
    const frac = i / (thresholds.length - 1); // 0 = kleinste drempel (binnenste ring)
    return RAMP[Math.round((1 - frac) * (RAMP.length - 1))];
  };

  return (
    <GeoJSON
      key={`iso-${data?.hex_id}-${thresholds.join(",")}`}
      pane="isochrone"
      data={{ type: "FeatureCollection", features }}
      style={(f) => {
        const c = colorFor(f?.properties?.threshold);
        return { fillColor: c, fillOpacity: 0.25, color: c, weight: 1, opacity: 1 };
      }}
      onEachFeature={(f, layer) => {
        const t = f?.properties?.threshold;
        if (t !== null && t !== undefined) layer.bindTooltip(`Binnen ${t} min`);
      }}
    />
  );
}
