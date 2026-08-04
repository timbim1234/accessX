import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import Sidebar, { ANALYSIS_OPTIONS } from "./components/Sidebar.jsx";
import HelpModal from "./components/HelpModal.jsx";
import { getIsochrone, getJob, getJobResult, getPresets, postAnalyze } from "./api.js";
import { FALLBACK_PRESETS } from "./fallbackPresets.js";
import { buildMetricOptions, computeBins, computeDelta, groupColors } from "./metrics.js";

const ANALYSES_ORDER = ANALYSIS_OPTIONS.map((o) => o.key);

// Ringoppervlak (km²) van één polygoon (array van ringen); buitenring positief,
// gaten negatief. Schoenveterformule op lon/lat met cos(breedtegraad)-correctie.
function ringsAreaKm2(rings) {
  if (!Array.isArray(rings)) return 0;
  let totalM2 = 0;
  rings.forEach((ring, r) => {
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

// Oppervlak van een Polygon of MultiPolygon (bv. een geladen PDOK-gemeente).
function polygonAreaKm2(geometry) {
  if (!geometry || !Array.isArray(geometry.coordinates)) return 0;
  if (geometry.type === "Polygon") return ringsAreaKm2(geometry.coordinates);
  if (geometry.type === "MultiPolygon") {
    return geometry.coordinates.reduce((acc, poly) => acc + ringsAreaKm2(poly), 0);
  }
  return 0;
}

export default function App() {
  const [presets, setPresets] = useState(null);
  const [presetsWarning, setPresetsWarning] = useState(null);
  const [showHelp, setShowHelp] = useState(
    typeof window !== "undefined" && window.location.hash === "#uitleg"
  );

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
  const [externalGeometry, setExternalGeometry] = useState(null);

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

  // Wat-als scenario
  const [whatIfMode, setWhatIfMode] = useState(false);
  const [scenarioCategory, setScenarioCategory] = useState(null);
  const [extraPois, setExtraPois] = useState([]);
  const [baselineResult, setBaselineResult] = useState(null);
  const [viewMode, setViewMode] = useState("scenario"); // "scenario" | "diff"

  const abortRef = useRef(null);
  const isoModeRef = useRef(false);
  const whatIfModeRef = useRef(false);
  const scenarioCategoryRef = useRef(null);
  const jobIdRef = useRef(null);
  // Teller om in-flight isochroon-fetches te invalideren (nieuwe klik,
  // nieuwe run of reset): een verouderde respons mag de state niet meer raken.
  const isoReqRef = useRef(0);
  const resultRef = useRef(null);
  const extraPoisRef = useRef([]);
  const baselineResultRef = useRef(null);
  const baseBodyRef = useRef(null); // exacte request-body van de laatste basis-run
  const baseSnapshotRef = useRef(null); // basis-result om te herstellen bij scenario-fout
  const scenarioRunRef = useRef(false); // is de lopende run een scenario-run

  useEffect(() => {
    isoModeRef.current = isoMode;
  }, [isoMode]);
  useEffect(() => {
    whatIfModeRef.current = whatIfMode;
  }, [whatIfMode]);
  useEffect(() => {
    scenarioCategoryRef.current = scenarioCategory;
  }, [scenarioCategory]);
  useEffect(() => {
    jobIdRef.current = jobId;
  }, [jobId]);
  useEffect(() => {
    resultRef.current = result;
  }, [result]);
  useEffect(() => {
    extraPoisRef.current = extraPois;
  }, [extraPois]);
  useEffect(() => {
    baselineResultRef.current = baselineResult;
  }, [baselineResult]);

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

  // Een geladen PDOK-gebied als AOI zetten: via externalGeometry injecteert
  // DrawTools de geometrie in de teken-FeatureGroup en fit de kaart erop.
  // Nieuwe objectreferentie forceert het injectie-effect (ook bij hetzelfde id).
  const handleAreaLoad = useCallback((geometry) => {
    setExternalGeometry(geometry ? { ...geometry } : null);
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

  // Gedeelde start voor basis- en scenario-runs. Bij een scenario-run wordt de
  // basis vastgehouden (baselineResult) zodat het verschil getoond kan worden.
  const startJob = useCallback((body, { scenario }) => {
    if (abortRef.current) abortRef.current.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    // Basis om tegen te vergelijken: bij een herhaalde scenario-run blijft de
    // oorspronkelijke basis staan; anders is het huidige (basis-)result.
    const baseSnapshot = scenario
      ? baselineResultRef.current || resultRef.current
      : resultRef.current;

    setError(null);
    if (scenario) {
      baseSnapshotRef.current = baseSnapshot;
      setBaselineResult(baseSnapshot);
      setViewMode("scenario");
      scenarioRunRef.current = true;
    } else {
      baseSnapshotRef.current = null;
      setBaselineResult(null);
      setViewMode("scenario");
      setMetric(null);
      scenarioRunRef.current = false;
    }
    setResult(null);
    setJob(null);
    setJobId(null);
    isoReqRef.current += 1; // in-flight isochroon-fetch van vorige job invalideren
    setIsochrone(null);
    setIsoError(null);
    setIsoLoading(false);
    setRunning(true);

    (async () => {
      try {
        const { job_id: newJobId } = await postAnalyze(body, ac.signal);
        setJobId(newJobId);
      } catch (e) {
        if (e.name === "AbortError") return;
        console.error("Analyse starten mislukt:", e);
        setError(`Analyse starten mislukt: ${e.message}`);
        setRunning(false);
        if (scenario) {
          // Basisweergave herstellen na een mislukte scenario-start.
          setResult(baseSnapshot);
          setBaselineResult(null);
          scenarioRunRef.current = false;
        }
      }
    })();
  }, []);

  const runAnalysis = useCallback(() => {
    if (!polygon) return;
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
    baseBodyRef.current = body;
    startJob(body, { scenario: false });
  }, [polygon, settings, presets, startJob]);

  // Scenario-run: exact dezelfde body als de basis-run + extra_pois.
  const runScenario = useCallback(() => {
    const base = baseBodyRef.current;
    if (!base || !extraPoisRef.current.length) return;
    startJob({ ...base, extra_pois: extraPoisRef.current }, { scenario: true });
  }, [startJob]);

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
          if (scenarioRunRef.current) {
            // Basisweergave herstellen na een mislukte scenario-run.
            setResult(baseSnapshotRef.current);
            setBaselineResult(null);
            scenarioRunRef.current = false;
          }
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

  // Verschil scenario − basis per hex voor de geselecteerde metriek (richting
  // gecorrigeerd: positief = beter, symmetrische schaal rond 0).
  const diffData = useMemo(() => {
    if (viewMode !== "diff" || !baselineResult || !result || !metric) return null;
    const raw = computeDelta(baselineResult.hexes?.features, result.hexes?.features, metric);
    const invert = metric.startsWith("nearest_cost_"); // lager is beter -> teken omkeren
    const values = new Map();
    let absMax = 0;
    for (const [id, dRaw] of raw) {
      const val = invert ? -dRaw : dRaw;
      values.set(id, val);
      const a = Math.abs(val);
      if (a > absMax) absMax = a;
    }
    return { values, absMax };
  }, [viewMode, baselineResult, result, metric]);

  const hasNulls = useMemo(() => {
    if (diffData) {
      const total = result?.hexes?.features?.length || 0;
      return total > diffData.values.size;
    }
    return metricValues
      ? metricValues.some(
          (v) => v === null || v === undefined || typeof v !== "number" || !Number.isFinite(v)
        )
      : false;
  }, [diffData, result, metricValues]);

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

  // Isochroon-modus en wat-als-plaatsmodus sluiten elkaar uit.
  const handleIsoModeChange = useCallback((on) => {
    setIsoMode(on);
    if (on) setWhatIfMode(false);
  }, []);

  const handleWhatIfModeChange = useCallback((on) => {
    setWhatIfMode(on);
    if (on) setIsoMode(false);
  }, []);

  // Bij het aanzetten van de wat-als-modus een geldige categorie kiezen uit de
  // groepen van de basis-run (waartegen de backend extra_pois valideert).
  useEffect(() => {
    if (!whatIfMode) return;
    const groups = baseBodyRef.current?.poi_groups || [];
    if (!groups.length) return;
    setScenarioCategory((prev) => (prev && groups.includes(prev) ? prev : groups[0]));
  }, [whatIfMode]);

  const handleMapClick = useCallback((lat, lng) => {
    if (!whatIfModeRef.current) return;
    const category = scenarioCategoryRef.current;
    if (!category) return;
    setExtraPois((prev) => [...prev, { lon: lng, lat, category }]);
  }, []);

  const removeExtraPoi = useCallback((idx) => {
    setExtraPois((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const clearExtraPois = useCallback(() => setExtraPois([]), []);

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
    setWhatIfMode(false);
    setExtraPois([]);
    setBaselineResult(null);
    setViewMode("scenario");
    scenarioRunRef.current = false;
    baseBodyRef.current = null;
    baseSnapshotRef.current = null;
  }, []);

  const maxMinutesUsed = result?.meta?.params?.max_minutes ?? settings.max_minutes;
  const scenarioGroups = baseBodyRef.current?.poi_groups || [];

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">accessX testlab</span>
        <span className="app-subtitle">— X-minutenstad-analyse op eigen polygoon</span>
        <button
          className="help-btn"
          onClick={() => setShowHelp(true)}
          aria-label="Uitleg van methoden en berekeningen"
          title="Methoden & berekeningen"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M9.2 9.3a2.8 2.8 0 1 1 3.9 2.6c-.8.4-1.1 1-1.1 1.8v.4" />
            <circle cx="12" cy="17.3" r="0.6" fill="currentColor" stroke="none" />
          </svg>
        </button>
      </header>
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
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
          onAreaLoad={handleAreaLoad}
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
          onIsoModeChange={handleIsoModeChange}
          isoLoading={isoLoading}
          isoError={isoError}
          hasIsochrone={Boolean(isochrone)}
          onClearIso={clearIsochrone}
          onNewAnalysis={newAnalysis}
          whatIfMode={whatIfMode}
          onWhatIfModeChange={handleWhatIfModeChange}
          scenarioCategory={scenarioCategory}
          onScenarioCategoryChange={setScenarioCategory}
          scenarioGroups={scenarioGroups}
          extraPois={extraPois}
          onRemoveExtraPoi={removeExtraPoi}
          onClearExtraPois={clearExtraPois}
          onRunScenario={runScenario}
          baselineResult={baselineResult}
          viewMode={viewMode}
          onViewModeChange={setViewMode}
        />
        <MapView
          onPolygonChange={handlePolygonChange}
          externalGeometry={externalGeometry}
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
          whatIfMode={whatIfMode}
          onMapClick={handleMapClick}
          extraPois={extraPois}
          diffData={diffData}
          hasAOI={Boolean(polygon)}
          aoiGeometry={polygon}
        />
      </div>
    </div>
  );
}
