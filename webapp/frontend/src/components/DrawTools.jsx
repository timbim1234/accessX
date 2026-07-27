smport { useRef } from "react";
import { FeatureGroup } from "react-leaflet";
import { EditControl } from "react-leaflet-draw";

const SHAPE_OPTIONS = {
  color: "#2a78d6",
  weight: 2,
  fillOpacity: 0.08,
};

// Tekenlaag: alleen polygon + rectangle; edit + delete aan; één AOI tegelijk.
export default function DrawTools({ onChange }) {
  const fgRef = useRef(null);

  const emit = () => {
    const fg = fgRef.current;
    const layers = fg ? fg.getLayers() : [];
    if (!layers.length) {
      onChange(null);
      return;
    }
    const gj = layers[0].toGeoJSON();
    onChange(gj && gj.geometry ? gj.geometry : null);
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
