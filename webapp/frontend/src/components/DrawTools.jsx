import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet-draw"; // breidt L.Draw uit (L.Draw.Polygon/Rectangle, L.Draw.Event)
import { FeatureGroup, useMap } from "react-leaflet";

const SHAPE_OPTIONS = {
  color: "#8886d8", // CityMaker lavender-100 (tekenmodus)
  weight: 2,
  fillOpacity: 0.08,
};

// Tekenlaag: één AOI tegelijk (polygoon of rechthoek). Het tekenen wordt gedreven
// door de zwevende toolbar via `controlsRef` (startPolygon/startRectangle/clear);
// er is geen zichtbare leaflet-draw-werkbalk meer. `externalGeometry` (bv. een
// geladen PDOK-gebied) wordt in de FeatureGroup geïnjecteerd zodat de kaart erop
// inzoomt en de AOI wisbaar is.
export default function DrawTools({ onChange, externalGeometry, controlsRef }) {
  const fgRef = useRef(null);
  const map = useMap();
  // Actieve leaflet-draw-handler (om te kunnen disablen bij een nieuwe start/wis).
  const drawHandlerRef = useRef(null);

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

  // Nieuwe vorm klaar: vorige AOI weg, nieuwe laag toevoegen, doorgeven.
  const handleCreated = (e) => {
    const fg = fgRef.current;
    if (fg) {
      fg.clearLayers(); // één AOI tegelijk
      fg.addLayer(e.layer);
    }
    emit();
  };

  // De CREATED-listener één keer registreren; leaflet-draw vuurt dit event op de
  // map af zodra het tekenen van een polygoon/rechthoek is afgerond.
  useEffect(() => {
    map.on(L.Draw.Event.CREATED, handleCreated);
    return () => {
      map.off(L.Draw.Event.CREATED, handleCreated);
    };
    // fgRef/onChange zijn stabiel; alleen op de map-referentie (her)binden.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);

  // Besturing beschikbaar maken voor de toolbar. Bij een nieuwe start wordt een
  // eventueel lopende teken-handler eerst uitgezet (voorkomt dubbel tekenen).
  useEffect(() => {
    if (!controlsRef) return undefined;
    const startDraw = (Ctor, options) => {
      if (drawHandlerRef.current) {
        try {
          drawHandlerRef.current.disable();
        } catch {
          // handler kan al afgesloten zijn; negeren
        }
      }
      const handler = new Ctor(map, options);
      drawHandlerRef.current = handler;
      handler.enable();
    };
    controlsRef.current = {
      startPolygon: () =>
        startDraw(L.Draw.Polygon, { allowIntersection: false, shapeOptions: SHAPE_OPTIONS }),
      startRectangle: () => startDraw(L.Draw.Rectangle, { shapeOptions: SHAPE_OPTIONS }),
      clear: () => {
        if (drawHandlerRef.current) {
          try {
            drawHandlerRef.current.disable();
          } catch {
            // negeren
          }
          drawHandlerRef.current = null;
        }
        fgRef.current?.clearLayers();
        onChange(null);
      },
    };
    return () => {
      controlsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, controlsRef, onChange]);

  // Geladen gebied injecteren: bestaande lagen weg, geometrie als polygoon
  // toevoegen, kaart naar de bounds, en de nieuwe AOI doorgeven.
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

  return <FeatureGroup ref={fgRef} />;
}
