import { useEffect, useRef } from "react";
import L from "leaflet";
import { useMap } from "react-leaflet";

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");

// Fictieve (wat-als) voorzieningen als aparte ruit-markers met dikke witte ring,
// zodat ze duidelijk van de echte POI-punten te onderscheiden zijn. Imperatief
// beheerd via een layerGroup (geen remount-gedoe bij toevoegen/verwijderen).
export default function ScenarioLayer({ points, groupColorMap, groupLabels }) {
  const map = useMap();
  const groupRef = useRef(null);

  useEffect(() => {
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;
    return () => {
      map.removeLayer(group);
      groupRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    group.clearLayers();
    (points || []).forEach((p) => {
      const color = groupColorMap[p.category] || "#898781";
      const icon = L.divIcon({
        className: "scenario-divicon",
        html: `<span class="scenario-diamond" style="background:${color}"></span>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      const marker = L.marker([p.lat, p.lon], { icon, keyboard: false });
      const label = (groupLabels && groupLabels[p.category]) || p.category || "scenario";
      marker.bindTooltip(`Scenario — ${esc(label)}`);
      group.addLayer(marker);
    });
  }, [points, groupColorMap, groupLabels]);

  return null;
}
