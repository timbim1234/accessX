import { useEffect } from "react";
import L from "leaflet";
import { useMap } from "react-leaflet";
import { NL_OUTLINE } from "../nlOutline.js";

// Wereld-dekkend masker met Nederland als "gat": alles buiten NL wordt licht
// afgedekt zodat alleen Nederland zichtbaar is (analyse kan toch alleen in NL).
// Leaflet gebruikt fill-rule evenodd, dus [wereldring, ...NL-ringen] laat NL vrij.
// Niet-interactief; ligt boven de tegels (z 350) maar onder hexes/POI's (z 400+).
const WORLD = [
  [-85, -180],
  [-85, 180],
  [85, 180],
  [85, -180],
];

function outerRingsLatLng(geometry) {
  // GeoJSON [lon,lat] -> Leaflet [lat,lon]; alleen buitenringen als "gaten".
  const rings = [];
  if (geometry.type === "Polygon") {
    rings.push(geometry.coordinates[0].map(([lng, lat]) => [lat, lng]));
  } else if (geometry.type === "MultiPolygon") {
    geometry.coordinates.forEach((poly) => rings.push(poly[0].map(([lng, lat]) => [lat, lng])));
  }
  return rings;
}

export default function NLMask() {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("nlmask")) {
      const pane = map.createPane("nlmask");
      pane.style.zIndex = 350; // boven tegels (200), onder overlay (400)
      pane.style.pointerEvents = "none";
    }
    const rings = outerRingsLatLng(NL_OUTLINE);
    const mask = L.polygon([WORLD, ...rings], {
      pane: "nlmask",
      interactive: false,
      stroke: false,
      fill: true,
      fillColor: "#e9eef8",
      fillOpacity: 0.9,
    }).addTo(map);
    const border = L.geoJSON(NL_OUTLINE, {
      pane: "nlmask",
      interactive: false,
      style: { fill: false, color: "#b5b7c1", weight: 1, opacity: 0.8 },
    }).addTo(map);
    return () => {
      map.removeLayer(mask);
      map.removeLayer(border);
    };
  }, [map]);
  return null;
}
