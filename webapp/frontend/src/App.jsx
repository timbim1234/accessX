import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { getIsochrone, getJob, getJobResult, getPresets, postAnalyze } from "./api.js";
import { FALLBACK_PRESETS } from "./fallbackPresets.js";
import { buildMetricOptions, computeBins, groupColors } from "./metrics.js";

const ANALYSES_ORDER = ["counts", "nearest", "hansen", "population", "2sfca", "equity"];

// Eenvoudige geodetische benadering: schoenveterformule op lon/lat,
// gecorrigeerd met cos(gemiddelde breedtegraad) en 111320 m per graad.
function polygonAreaKm2(geometry) {
  if (!geometry || geometry.type !== "Polygon" || !Array.isArray(geometry.coordinates)) return 0;
  let totalM2 = 0;
  geometry.coordinates.forEach((ring, r) => {
    if (!Array.isArray(ring) || ring.length < 4) return;
    let sum = 0;
    let latSum = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i];
      const [x2, y2] = ring[i + 1];
      sum += x1 * y2 - x2 * y1;
      latSum += y1;
    }
    const meanLatRad = (latSum / (ring.length - 1)) * (Math.PI / 180);
    const ringM2 = (Math.abs(sum) / 2) * Math.cos(meanLatRad) * 111320 * 111320;
    totalM2 += r === 0 ? ringM2 : -ringM2; // gaten aftrekken
  });
  return Math.max(0, totalM2) / 1e6;
}

export default function App() {
  const [presets, setPresets] = useState(null);
  const [presetsWarning, setPresetsWarning] = useState(null);

  const [settings, setSettings] = useState(() => ({
    mode: FALLBACK_PRESETS.defaults.mode,
    speed_kmh: FALLBACK_PRESETS.defaults.speed_kmh,
    max_minutes: FALLBACK_PRESETS.defaults.max_minutes,
    hex_resolution: FALLBACK_PRESETS.defaults.hex_resolution,
    poi_groups: [...FALLBACK_PRESETS.defaults.selected_groups],
    analyses: [...FALLBACK_PRESETS.defaults.analyses],
    beta: 0.15,
    sfca_decay: "exp",
  }));

  const [polygon, setPolygon] = useState(null);
  const [areaKm2, setAreaKm2] = useState(0);

  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const [metric, setMetric] = useState(null);
  const [poiVisible, setPoiVisible] = useState({});

  const [isoMode, setIsoMode] = useState(false);
  const [isochrone, setIsochrone] = useState(null);
  const [isoLoading, setIsoLoading] = useState(false);
  const [isoError, setIsoError] = useState(null);

  const abortRef = useRef(null);
  const isoModeRef = useRef(false);
  const jobIdRef = useRef(null);
  // Teller om in-flight isochroon-fetches te invalideren (nieuwe klik,
  // nieuwe run of reset): een verouderde respons mag de state niet meer raken.
  const isoReqRef = useRef(0);
  useEffect(() => {
    isoModeRef.current = isoMode;
  }, [isoMode]);
  useEffect(() => {
    jobIdRef.current = jobId;
  }, [jobId]);

  // Presets laden; bij falen terugvallen op de ingebouwde kopie uit CONTRACT.md.
  useEffect(() => {
    let cancelled = false;
    getPresets()
      .then((p) => {
        if (cancelled) return;
        setPresets(p);
        const d = p.defaults || {};
        setSettings((s) => ({
          ...s,
          mode: d.mode ?? s.mode,
          speed_kmh: d.speed_kmh ?? s.speed_kmh,
          max_minutes: d.max_minutes ?? s.max_minutes,
          hex_resolution: d.hex_resolution ?? s.hex_resolution,
          poi_groups: d.selected_groups ? [...d.selected_groups] : s.poi_groups,
          analyses: d.analyses ? [...d.analyses] : s.analyses,
        }));
      })
      .catch((e) => {
        if (cancelled) return;
        console.error("Voorinstellingen laden mislukt:", e);
        setPresets(FALLBACK_PRESETS);
        setPresetsWarning(
          "Voorinstellingen konden niet van de backend worden geladen (draait de backend op poort 8000?). Ingebouwde standaardwaarden worden gebruikt."
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePolygonChange = useCallback((geometry) => {
    setPolygon(geometry);
    setAreaKm2(geometry ? polygonAreaKm2(geometry) : 0);
  }, []);

  const updateSettings = useCallback((patch) => {
    setSettings((s) => ({ ...s, ...patch }));
  }, []);

  const handleModeChange = useCallback((mode) => {
    setSettings((s) => ({ ...s, mode, speed_kmh: mode === "walk" ? 4.5 : 15 }));
  }, []);

  const toggleGroup = useCallback((key) => {
    setSettings((s) => ({
      ...s,
      poi_groups: s.poi_groups.includes(key)
        ? s.poi_groups.filter((k) => k !== key)
        : [...s.poi_groups, key],
    }));
  }, []);

  const toggleAnalysis = useCallback((key) => {
    setSettings((s) => {
      let analyses = s.analyses.includes(key)
        ? s.analyses.filter((a) => a !== key)
        : [...s.analyses, key];
      if (key === "population" && !analyses.includes("population")) {
        analyses = analyses.filter((a) => a !== "2sfca");
      }
      return { ...s, analyses };
    });
  }, []);

  const limits = presets?.limits || FALLBACK_PRESETS.limits;
  const canRun =
    Boolean(polygon) &&
    settings.poi_groups.length > 0 &&
    !running &&
    Number(settings.speed_kmh) > 0 &&
    areaKm2 <= limits.max_area_km2;

  const runAnalysis = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setError(null);
    setResult(null);
    setJob(null);
    setJobId(null);
    setMetric(null);
    isoReqRef.current += 1; // in-flight isochroon-fetch van vorige job invalideren
    setIsochrone(null);
    setIsoError(null);
    setIsoLoading(false);
    setRunning(true);
    try {
      const groupOrder = Object.keys((presets || FALLBACK_PRESETS).poi_groups);
      const body = {
        polygon,
        mode: settings.mode,
        speed_kmh: Number(settings.speed_kmh),
        max_minutes: settings.max_minutes,
        hex_resolution: settings.hex_resolution,
        poi_groups: groupOrder.filter((k) => settings.poi_groups.includes(k)),
        analyses: ANALYSES_ORDER.filter((a) => settings.analyses.includes(a)),
        beta: Number(settings.beta),
        sfca_decay: settings.sfca_decay,
      };
      const { job_id: newJobId } = await postAnalyze(body, ac.signal);
      setJobId(newJobId);
    } catch (e) {
      if (e.name === "AbortError") return;
      console.error("Analyse starten mislukt:", e);
      setError(`Analyse starten mislukt: ${e.message}`);
      setRunning(false);
    }
  }, [polygon, settings, presets]);

  // Pollen (1500 ms) zolang de job loopt; stoppen bij unmount of nieuwe run.
  useEffect(() => {
    if (!jobId) return undefined;
    const ac = new AbortController();
    let stopped = false;
    let timer = null;

    async function poll() {
      try {
        const j = await getJob(jobId, ac.signal);
        if (stopped) return;
        setJob(j);
        if (j.status === "done") {
          const r = await getJobResult(jobId, ac.signal);
          if (stopped) return;
          setResult(r);
          setRunning(false);
        } else if (j.status === "error") {
          setError(j.error || "Onbekende fout tijdens de analyse.");
          setRunning(false);
        } else {
          timer = setTimeout(poll, 1500);
        }
      } catch (e) {
        if (stopped || e.name === "AbortError") return;
        console.error("Jobstatus ophalen mislukt:", e);
        setError(`Jobstatus ophalen mislukt: ${e.message}`);
        setRunning(false);
      }
    }

    poll();
    return () => {
      stopped = true;
      ac.abort();
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  const metricOptions = useMemo(() => buildMetricOptions(result, presets), [result, presets]);

  // Bij een nieuw resultaat: standaardmetriek kiezen en POI-lagen aanzetten.
  useEffect(() => {
    if (!result) return;
    const props = result.hexes?.features?.[0]?.properties || {};
    setMetric((prev) => {
      if (prev && prev in props) return prev;
      const flat = metricOptions.flatMap((g) => g.options);
      return flat.length ? flat[0].value : null;
    });
    const vis = {};
    Object.keys((presets || FALLBACK_PRESETS).poi_groups).forEach((k) => {
      vis[k] = true;
    });
    setPoiVisible(vis);
  }, [result, metricOptions, presets]);

  const metricValues = useMemo(() => {
    if (!result || !metric) return null;
    return (result.hexes?.features || []).map((f) => f.properties?.[metric]);
  }, [result, metric]);

  const bins = useMemo(() => (metricValues ? computeBins(metricValues) : null), [metricValues]);

  const hasNulls = useMemo(
    () =>
      metricValues
        ? metricValues.some((v) => v === null || v === undefined || typeof v !== "number" || !Number.isFinite(v))
        : false,
    [metricValues]
  );

  const groupColorMap = useMemo(() => groupColors(presets || FALLBACK_PRESETS), [presets]);

  const togglePoi = useCallback((key) => {
    setPoiVisible((v) => ({ ...v, [key]: !v[key] }));
  }, []);

  const handleHexClick = useCallback(async (hexId) => {
    if (!isoModeRef.current || !jobIdRef.current) return;
    const req = ++isoReqRef.current;
    setIsoLoading(true);
    setIsoError(null);
    try {
      const data = await getIsochrone(jobIdRef.current, hexId, 5);
      if (req !== isoReqRef.current) return; // verouderde respons negeren
      setIsochrone(data);
    } catch (e) {
      if (req !== isoReqRef.current) return;
      console.error("Isochroon ophalen mislukt:", e);
      setIsoError(`Isochroon ophalen mislukt: ${e.message}`);
    } finally {
      if (req === isoReqRef.current) setIsoLoading(false);
    }
  }, []);

  const clearIsochrone = useCallback(() => {
    isoReqRef.current += 1; // in-flight isochroon-fetch invalideren
    setIsochrone(null);
    setIsoError(null);
    setIsoLoading(false);
  }, []);

  const newAnalysis = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    isoReqRef.current += 1; // in-flight isochroon-fetch invalideren
    setResult(null);
    setJob(null);
    setJobId(null);
    setError(null);
    setMetric(null);
    setRunning(false);
    setIsochrone(null);
    setIsoMode(false);
    setIsoError(null);
    setIsoLoading(false);
  }, []);

  const maxMinutesUsed = result?.meta?.params?.max_minutes ?? settings.max_minutes;

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">accessX testlab</span>
        <span className="app-subtitle">— X-minutenstad-analyse op eigen polygoon</span>
      </header>
      <div className="app-body">
        <Sidebar
          presets={presets}
          presetsWarning={presetsWarning}
          settings={settings}
          onSettingsChange={updateSettings}
          onModeChange={handleModeChange}
          onToggleGroup={toggleGroup}
          onToggleAnalysis={toggleAnalysis}
          hasPolygon={Boolean(polygon)}
          areaKm2={areaKm2}
          canRun={canRun}
          running={running}
          onRun={runAnalysis}
          job={job}
          error={error}
          result={result}
          metricOptions={metricOptions}
          metric={metric}
          onMetricChange={setMetric}
          groupColorMap={groupColorMap}
          poiVisible={poiVisible}
          onTogglePoi={togglePoi}
          isoMode={isoMode}
          onIsoModeChange={setIsoMode}
          isoLoading={isoLoading}
          isoError={isoError}
          hasIsochrone={Boolean(isochrone)}
          onClearIso={clearIsochrone}
          onNewAnalysis={newAnalysis}
        />
        <MapView
          onPolygonChange={handlePolygonChange}
          result={result}
          resultKey={jobId || "none"}
          metric={metric}
          bins={bins}
          hasNulls={hasNulls}
          presets={presets || FALLBACK_PRESETS}
          groupColorMap={groupColorMap}
          poiVisible={poiVisible}
          onHexClick={handleHexClick}
          isochrone={isochrone}
          maxMinutes={maxMinutesUsed}
        />
      </div>
    </div>
  );
}
