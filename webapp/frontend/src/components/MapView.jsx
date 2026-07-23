import { useEffect } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import DrawTools from "./DrawTools.jsx";
import HexLayer from "./HexLayer.jsx";
import PoiLayer from "./PoiLayer.jsx";
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

export default function MapView({
  onPolygonChange,
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
}) {
  const groupKeys = Object.keys(presets?.poi_groups || {});
  const groupLabels = {};
  groupKeys.forEach((k) => {
    groupLabels[k] = presets.poi_groups[k].label;
  });
  const visKey = groupKeys.filter((k) => poiVisible[k]).join("|");

  return (
    <div className="map-wrap">
      <MapContainer center={[52.09, 5.12]} zoom={8} className="map">
        <Panes />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers &copy; <a href="https://carto.com/attributions">CARTO</a>'
        />
        <DrawTools onChange={onPolygonChange} />
        {result?.hexes && metric && (
          <HexLayer
            key={`hex-${resultKey}-${metric}`}
            data={result.hexes}
            metric={metric}
            bins={bins}
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
      </MapContainer>
      {result && metric && bins && (
        <Legend metric={metric} bins={bins} presets={presets} hasNulls={hasNulls} maxMinutes={maxMinutes} />
      )}
    </div>
  );
}
