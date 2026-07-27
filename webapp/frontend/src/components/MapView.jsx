import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";
import DrawTools from "./DrawTools.jsx";
import HexLayer from "./HexLayer.jsx";
import PoiLayer from "./PoiLayer.jsx";
import ScenarioLayer from "./ScenarioLayer.jsx";
import IsochroneLayer from "./IsochroneLayer.jsx";
import Legend from "./Legend.jsx";
import Toolbar from "./Toolbar.jsx";
import NLMask from "./NLMask.jsx";

// Kaart vast op Nederland: buiten deze grenzen kun je niet slepen/zoomen
// (analyse kan toch alleen binnen NL). Iets ruimer dan de landsgrens.
const NL_MAX_BOUNDS = [
  [50.6, 3.1],
  [53.75, 7.45],
];

// Beschikbare basemaps voor de kaartweergave-groep in de toolbar. De thumbnails
// zijn placeholders (icoon), geen externe afbeeldingen.
const BASEMAPS = [
  {
    id: "licht",
    label: "Licht",
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers &copy; <a href="https://carto.com/attributions">CARTO</a>',
    icon: "map",
  },
  {
    id: "luchtfoto",
    label: "Luchtfoto",
    // Esri World Imagery gebruikt {z}/{y}/{x}-volgorde en heeft geen {s}-subdomein.
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Esri, Maxar, Earthstar Geographics",
    icon: "map",
  },
  {
    id: "osm",
    label: "OSM",
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers',
    icon: "map",
  },
];

// Vaste panes zodat de stapeling niet afhangt van (re)mount-volgorde:
// hexes (overlayPane, z 400) < isochroonringen (430) < POI-punten (440).
// Zonder deze panes komt de hexlaag na een metric-wissel (key-remount)
// bovenop de eerder getekende POI's en isochronen te liggen.
function Panes() {
  const map = useMap();
  useEffect(() => {
    if (!map.getPane("isochrone")) map.createPane("isochrone").style.zIndex = 430;
    if (!map.getPane("pois")) map.createPane("pois").style.zIndex = 440;
  }, [map]);
  return null;
}

// Kaartklik-handler voor de wat-als-plaatsmodus. Alleen actief als `active`;
// botst niet met de isochroon-klik (die zit op de hexlaag) omdat wat-als- en
// isochroon-modus elkaar uitsluiten in App.
function WhatIfClicker({ active, onPlace }) {
  useMapEvents({
    click(e) {
      if (!active) return;
      onPlace(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export default function MapView({
  onPolygonChange,
  externalGeometry,
  result,
  resultKey,
  metric,
  bins,
  hasNulls,
  presets,
  groupColorMap,
  poiVisible,
  onHexClick,
  isochrone,
  maxMinutes,
  whatIfMode,
  onMapClick,
  extraPois,
  diffData,
  hasAOI,
  aoiGeometry,
}) {
  // Tekenbesturing die DrawTools invult en de Toolbar aanroept.
  const drawControls = useRef(null);
  const [basemap, setBasemap] = useState("licht");
  const activeBasemap = BASEMAPS.find((b) => b.id === basemap) || BASEMAPS[0];

  const groupKeys = useMemo(() => Object.keys(presets?.poi_groups || {}), [presets]);
  const groupLabels = useMemo(() => {
    const labels = {};
    groupKeys.forEach((k) => {
      labels[k] = presets.poi_groups[k].label;
    });
    return labels;
  }, [groupKeys, presets]);
  const visKey = groupKeys.filter((k) => poiVisible[k]).join("|");
  const diffMode = Boolean(diffData);

  return (
    <div className={`map-wrap${whatIfMode ? " placing" : ""}`}>
      <MapContainer
        center={[52.15, 5.4]}
        zoom={8}
        minZoom={7}
        maxBounds={NL_MAX_BOUNDS}
        maxBoundsViscosity={1.0}
        className="map"
        zoomControl={false}
      >
        <Panes />
        <TileLayer key={activeBasemap.id} url={activeBasemap.url} attribution={activeBasemap.attribution} />
        <NLMask />
        <DrawTools
          onChange={onPolygonChange}
          externalGeometry={externalGeometry}
          controlsRef={drawControls}
        />
        <WhatIfClicker active={whatIfMode} onPlace={onMapClick} />
        {result?.hexes && metric && (
          <HexLayer
            key={`hex-${resultKey}-${metric}-${diffMode ? "diff" : "sc"}`}
            data={result.hexes}
            metric={metric}
            bins={bins}
            diffData={diffData}
            presets={presets}
            groupKeys={groupKeys}
            onHexClick={onHexClick}
          />
        )}
        {isochrone?.rings && <IsochroneLayer data={isochrone} />}
        {result?.pois && (
          <PoiLayer
            key={`poi-${resultKey}-${visKey}`}
            data={result.pois}
            visible={poiVisible}
            groupColorMap={groupColorMap}
            groupLabels={groupLabels}
          />
        )}
        {extraPois?.length > 0 && (
          <ScenarioLayer points={extraPois} groupColorMap={groupColorMap} groupLabels={groupLabels} />
        )}
        <Toolbar
          controlsRef={drawControls}
          hasAOI={hasAOI}
          aoiGeometry={aoiGeometry}
          basemap={basemap}
          basemaps={BASEMAPS}
          onBasemapChange={setBasemap}
        />
      </MapContainer>
      {result && metric && (bins || diffData) && (
        <Legend
          metric={metric}
          bins={bins}
          diffData={diffData}
          presets={presets}
          hasNulls={hasNulls}
          maxMinutes={maxMinutes}
        />
      )}
    </div>
  );
}
