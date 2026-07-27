import { useEffect, useRef, useState } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import ToolbarIcon from "./ToolbarIcon.jsx";
import "./Toolbar.css";

// Fit-bounds als er geen AOI bekend is: heel Nederland.
const NL_BOUNDS = [
  [50.7, 3.2],
  [53.6, 7.3],
];

// Zwevende CityMaker-pill-toolbar. Kind van MapContainer (dus useMap() werkt).
// Drie groepen: kaartweergave (basemap), tekenen (polygoon/rechthoek/wissen) en
// navigatie (fit/uit/in). Het tekenen zelf wordt gedreven via `controlsRef`
// (geleverd door DrawTools); zoom/fit gaan rechtstreeks via useMap().
export default function Toolbar({
  controlsRef,
  hasAOI,
  aoiGeometry,
  basemap,
  basemaps,
  onBasemapChange,
}) {
  const map = useMap();
  const [panelOpen, setPanelOpen] = useState(false);
  // Highlight (`--drawing`) voor de actieve tekenmodus; null = niet aan het tekenen.
  const [drawMode, setDrawMode] = useState(null); // "polygon" | "rectangle" | null

  const rootRef = useRef(null);
  const anchorRef = useRef(null);
  const panelRef = useRef(null);

  // Klikken/scrollen op de toolbar mag niet naar de kaart lekken (anders pant de
  // kaart of plaatst de wat-als-klik een punt onder de knop).
  useEffect(() => {
    if (rootRef.current) {
      L.DomEvent.disableClickPropagation(rootRef.current);
      L.DomEvent.disableScrollPropagation(rootRef.current);
    }
  }, []);

  // Highlight resetten zodra een vorm klaar is (CREATED) of het tekenen stopt/
  // geannuleerd wordt (DRAWSTOP). Zo dooft de `--drawing`-knop weer.
  useEffect(() => {
    const reset = () => setDrawMode(null);
    map.on(L.Draw.Event.CREATED, reset);
    map.on(L.Draw.Event.DRAWSTOP, reset);
    return () => {
      map.off(L.Draw.Event.CREATED, reset);
      map.off(L.Draw.Event.DRAWSTOP, reset);
    };
  }, [map]);

  // Basemap-paneel sluiten bij een klik buiten paneel én ankerknop.
  useEffect(() => {
    if (!panelOpen) return undefined;
    const onDown = (e) => {
      if (panelRef.current?.contains(e.target)) return;
      if (anchorRef.current?.contains(e.target)) return;
      setPanelOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [panelOpen]);

  const startPolygon = () => {
    controlsRef.current?.startPolygon();
    setDrawMode("polygon");
  };
  const startRectangle = () => {
    controlsRef.current?.startRectangle();
    setDrawMode("rectangle");
  };
  const clearAOI = () => {
    if (!hasAOI) return;
    controlsRef.current?.clear();
    setDrawMode(null);
  };

  // Fit op de AOI-bounds (afgeleid uit de geometrie) indien aanwezig, anders NL.
  const fit = () => {
    let bounds = null;
    if (aoiGeometry) {
      try {
        const b = L.geoJSON({ type: "Feature", geometry: aoiGeometry, properties: {} }).getBounds();
        if (b && b.isValid()) bounds = b;
      } catch {
        // Ongeldige geometrie: terugvallen op NL-bounds.
      }
    }
    map.fitBounds(bounds ?? NL_BOUNDS, { padding: [24, 24] });
  };

  const selectBasemap = (id) => {
    onBasemapChange(id);
    setPanelOpen(false);
  };

  return (
    <div className="toolbar" ref={rootRef}>
      <div className="toolbar__bar">
        {/* Groep 1 — Kaartweergave (basemap) */}
        <div className="toolbar__group toolbar__group--visual">
          <div className="toolbar__anchor" ref={anchorRef} data-tooltip="Kaartweergave">
            <button
              type="button"
              className={`toolbar__btn toolbar__btn--thumb${panelOpen ? " toolbar__btn--active" : ""}`}
              onClick={() => setPanelOpen((v) => !v)}
              aria-label="Kaartweergave"
              aria-expanded={panelOpen}
            >
              <span className="toolbar__thumb-placeholder">
                <ToolbarIcon name="map" />
              </span>
            </button>
            {panelOpen && (
              <div className="toolbar-panel toolbar-panel--basemap" ref={panelRef}>
                <div className="toolbar-panel__header">
                  <span>Kaartweergave</span>
                  <button
                    type="button"
                    className="toolbar-panel__close-btn"
                    onClick={() => setPanelOpen(false)}
                    aria-label="Sluiten"
                  >
                    <ToolbarIcon name="close" size={18} />
                  </button>
                </div>
                <div className="basemap-list">
                  {basemaps.map((b) => {
                    const active = b.id === basemap;
                    return (
                      <button
                        key={b.id}
                        type="button"
                        className={`basemap-row${active ? " basemap-row--active" : ""}`}
                        onClick={() => selectBasemap(b.id)}
                      >
                        <span className="basemap-row__thumb--placeholder">
                          <ToolbarIcon name={b.icon || "map"} size={18} />
                        </span>
                        <span className="basemap-row__name">{b.label}</span>
                        {active && (
                          <span className="basemap-row__check">
                            <ToolbarIcon name="check" size={14} />
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        <span className="toolbar__divider" />

        {/* Groep 2 — Tekenen */}
        <div className="toolbar__group toolbar__group--draw">
          <button
            type="button"
            className={`toolbar__btn${drawMode === "polygon" ? " toolbar__btn--drawing" : ""}`}
            data-tooltip="Polygoon tekenen"
            onClick={startPolygon}
            aria-label="Polygoon tekenen"
          >
            <ToolbarIcon name="pencil" />
          </button>
          <button
            type="button"
            className={`toolbar__btn${drawMode === "rectangle" ? " toolbar__btn--drawing" : ""}`}
            data-tooltip="Rechthoek tekenen"
            onClick={startRectangle}
            aria-label="Rechthoek tekenen"
          >
            <ToolbarIcon name="rectangle" />
          </button>
          <button
            type="button"
            className={`toolbar__btn${hasAOI ? "" : " toolbar__btn--disabled"}`}
            data-tooltip="Gebied wissen"
            onClick={clearAOI}
            disabled={!hasAOI}
            aria-label="Gebied wissen"
          >
            <ToolbarIcon name="trash" />
          </button>
        </div>

        <span className="toolbar__divider" />

        {/* Groep 3 — Navigatie */}
        <div className="toolbar__group toolbar__group--nav">
          <button
            type="button"
            className="toolbar__btn"
            data-tooltip="Op gebied passen"
            onClick={fit}
            aria-label="Op gebied passen"
          >
            <ToolbarIcon name="fit" />
          </button>
          <button
            type="button"
            className="toolbar__btn"
            data-tooltip="Uitzoomen"
            onClick={() => map.zoomOut()}
            aria-label="Uitzoomen"
          >
            <ToolbarIcon name="zoom-out" />
          </button>
          <button
            type="button"
            className="toolbar__btn"
            data-tooltip="Inzoomen"
            onClick={() => map.zoomIn()}
            aria-label="Inzoomen"
          >
            <ToolbarIcon name="zoom-in" />
          </button>
        </div>
      </div>
    </div>
  );
}
