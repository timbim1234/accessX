import { useEffect, useRef } from "react";
import L from "leaflet";
import { FeatureGroup, useMap } from "react-leaflet";
import { EditControl } from "react-leaflet-draw";

const SHAPE_OPTIONS = {
  color: "#2a78d6",
  weight: 2,
  fillOpacity: 0.08,
};

// Tekenlaag: alleen polygon + rectangle; edit + delete aan; één AOI tegelijk.
// `externalGeometry` (bv. een geladen PDOK-gebied) wordt in de FeatureGroup
// geïnjecteerd zodat hij ook bewerkbaar/wisbaar is en de kaart erop inzoomt.
export default function DrawTools({ onChange, externalGeometry }) {
  const fgRef = useRef(null);
  const map = useMap();

  const emit = () => {
    const fg = fgRef.current;
    const layers = fg ? fg.getLayers() : [];
    if (!layers.length) {
      onChange(null);
      return;
    }
    const geoms = layers
      .map((l) => (l.toGeoJSON ? l.toGeoJSON() : null))
      .map((g) => (g && g.geometry ? g.geometry : null))
      .filter(Boolean);
    if (!geoms.length) {
      onChange(null);
      return;
    }
    if (geoms.length === 1) {
      onChange(geoms[0]);
      return;
    }
    // Meerdere lagen (bv. een MultiPolygon-gemeente): combineren tot MultiPolygon.
    const polys = [];
    geoms.forEach((g) => {
      if (g.type === "Polygon") polys.push(g.coordinates);
      else if (g.type === "MultiPolygon") g.coordinates.forEach((c) => polys.push(c));
    });
    onChange({ type: "MultiPolygon", coordinates: polys });
  };

  const handleCreated = (e) => {
    const fg = fgRef.current;
    if (fg) {
      // Vorige shape verwijderen: één AOI tegelijk.
      fg.getLayers().forEach((l) => {
        if (l !== e.layer) fg.removeLayer(l);
      });
    }
    emit();
  };

  // Geladen gebied injecteren: bestaande lagen weg, geometrie als bewerkbare
  // polygoon toevoegen, kaart naar de bounds, en de nieuwe AOI doorgeven.
  useEffect(() => {
    if (!externalGeometry) return;
    const fg = fgRef.current;
    if (!fg) return;
    fg.clearLayers();
    const gj = L.geoJSON(
      { type: "Feature", geometry: externalGeometry, properties: {} },
      { style: SHAPE_OPTIONS }
    );
    gj.eachLayer((l) => fg.addLayer(l));
    try {
      const b = fg.getBounds();
      if (b && b.isValid()) map.fitBounds(b, { padding: [24, 24] });
    } catch {
      // getBounds kan falen bij een lege/ongeldige geometrie; negeren.
    }
    onChange(externalGeometry);
    // Alleen reageren op een nieuwe geometrie-referentie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalGeometry]);

  return (
    <FeatureGroup ref={fgRef}>
      <EditControl
        position="topleft"
        onCreated={handleCreated}
        onEdited={emit}
        onDeleted={emit}
        draw={{
          polygon: { allowIntersection: false, showArea: false, shapeOptions: SHAPE_OPTIONS },
          rectangle: { showArea: false, shapeOptions: SHAPE_OPTIONS },
          marker: false,
          circle: false,
          circlemarker: false,
          polyline: false,
        }}
      />
    </FeatureGroup>
  );
}
