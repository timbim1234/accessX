import { GeoJSON } from "react-leaflet";
import { ISO_RAMP } from "../metrics.js";

// Isochroonringen: van buiten (grootste drempel, amber) naar binnen (kleinste,
// diep karmijn).
//
// De ringen liggen genest bovenop de choropleth, dus de fills stapelen: bij
// drie ringen van 25% is het midden al bijna dicht terwijl de buitenste
// verdwijnt. Daarom is de fill hier laag gehouden en dragen de rándén het
// signaal, met een witte omkadering eronder zodat ze op elke ondergrond leesbaar
// blijven — ook op de luchtfoto.
export default function IsochroneLayer({ data }) {
  const features = [...(data?.rings?.features || [])];
  if (!features.length) return null;

  const thresholds = [...new Set(features.map((f) => f?.properties?.threshold))].sort(
    (a, b) => a - b
  );
  // Grootste ringen eerst tekenen zodat kleinere ringen erbovenop liggen.
  features.sort((a, b) => (b?.properties?.threshold ?? 0) - (a?.properties?.threshold ?? 0));

  const colorFor = (t) => {
    const i = thresholds.indexOf(t);
    if (i === -1 || thresholds.length === 1) return ISO_RAMP[ISO_RAMP.length - 1];
    const frac = i / (thresholds.length - 1); // 0 = kleinste drempel (binnenste ring)
    return ISO_RAMP[Math.round((1 - frac) * (ISO_RAMP.length - 1))];
  };

  // react-leaflet ververst een GeoJSON-laag niet bij nieuwe data, dus de key
  // moet het vertrekpunt bevatten: anders blijft bij een klik op de volgende
  // voorziening het oude isochroon staan (hex_id is dan null).
  const o = data?.origin;
  const oorsprong =
    data?.hex_id ??
    (o?.type === "punt" ? `${o.lon.toFixed(6)},${o.lat.toFixed(6)}` : "onbekend");
  const geo = { type: "FeatureCollection", features };
  const key = `${oorsprong}-${thresholds.join(",")}`;

  return (
    <>
      <GeoJSON
        key={`iso-casing-${key}`}
        pane="isochrone"
        data={geo}
        interactive={false}
        style={() => ({
          fill: false,
          color: "#ffffff",
          weight: 5,
          opacity: 0.85,
          lineJoin: "round",
        })}
      />
      <GeoJSON
        key={`iso-${key}`}
        pane="isochrone"
        data={geo}
        style={(f) => {
          const c = colorFor(f?.properties?.threshold);
          return {
            fillColor: c,
            fillOpacity: 0.14,
            color: c,
            weight: 2.5,
            opacity: 1,
            lineJoin: "round",
          };
        }}
        onEachFeature={(f, layer) => {
          const t = f?.properties?.threshold;
          if (t !== null && t !== undefined) layer.bindTooltip(`Binnen ${t} min`);
        }}
      />
    </>
  );
}
