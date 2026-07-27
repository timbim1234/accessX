import L from "leaflet";
import { GeoJSON } from "react-leaflet";

// POI-punten als circleMarkers in de vaste categoriekleur van hun groep.
// De laag wordt via `key` in MapView opnieuw aangemaakt bij zichtbaarheidswissel.
// Leaflet rendert tooltip-strings als HTML; OSM-namen dus escapen.
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

export default function PoiLayer({ data, visible, groupColorMap, groupLabels }) {
  return (
    <GeoJSON
      data={data}
      pane="pois"
      filter={(f) => Boolean(visible[f?.properties?.category]) && !f?.properties?.scenario}
      pointToLayer={(f, latlng) =>
        L.circleMarker(latlng, {
          pane: "pois",
          radius: 5,
          fillColor: groupColorMap[f?.properties?.category] || "#898781",
          fillOpacity: 0.9,
          color: "#ffffff",
          weight: 1.5,
          opacity: 1,
        })
      }
      onEachFeature={(f, layer) => {
        const name = f?.properties?.name || "naamloos";
        const cat = f?.properties?.category;
        const label = groupLabels[cat] || cat || "onbekend";
        layer.bindTooltip(`${esc(name)} — ${esc(label)}`);
      }}
    />
  );
}
