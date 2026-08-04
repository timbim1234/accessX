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
        const p = f?.properties || {};
        const name = p.name || "naamloos";
        const label = groupLabels[p.category] || p.category || "onbekend";
        // Vloeroppervlakte alleen tonen als de BAG-koppeling er een gaf; het
        // vraagteken markeert een koppeling op afstand i.p.v. op gebruiksdoel.
        const m2 =
          typeof p.bvo_m2 === "number" && Number.isFinite(p.bvo_m2)
            ? ` — ${Math.round(p.bvo_m2).toLocaleString("nl-NL")} m² BVO${
                p.doel_match ? "" : " (?)"
              }`
            : "";
        layer.bindTooltip(`${esc(name)} — ${esc(label)}${esc(m2)}`);
      }}
    />
  );
}
