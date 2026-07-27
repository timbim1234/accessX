import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";
import DrawTools from "./DrawTools.jsx";
import HexLayer from "./HexLayer.jsx";
import PoiLayer from "./PoiLayer.jsx";
import ScenarioLayer from "./ScenarioLayer.jsx";
import IsochroneLayer from "./IsochroneLayer.jsx";
import Legend from "./Legend.jsx";

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
}) {
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
      <MapContainer center={[52.09, 5.12]} zoom={8} className="map">
        <Panes />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers &copy; <a href="https://carto.com/attributions">CARTO</a>'
        />
        <DrawTools onChange={onPolygonChange} externalGeometry={externalGeometry} />
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
