import GeoSearch from "./GeoSearch.jsx";
import ProgressList from "./ProgressList.jsx";
import Results from "./Results.jsx";

const ANALYSIS_OPTIONS = [
  { key: "counts", label: "Aantal bereikbaar" },
  { key: "nearest", label: "Dichtstbijzijnde" },
  { key: "hansen", label: "Hansen" },
  { key: "population", label: "CBS-bevolking" },
  { key: "2sfca", label: "2SFCA vraag/aanbod" },
  { key: "equity", label: "Verdeling & Gini" },
];

export default function Sidebar({
  presets,
  presetsWarning,
  settings,
  onSettingsChange,
  onModeChange,
  onToggleGroup,
  onToggleAnalysis,
  hasPolygon,
  areaKm2,
  canRun,
  running,
  onRun,
  onAreaLoad,
  job,
  error,
  result,
  metricOptions,
  metric,
  onMetricChange,
  groupColorMap,
  poiVisible,
  onTogglePoi,
  isoMode,
  onIsoModeChange,
  isoLoading,
  isoError,
  hasIsochrone,
  onClearIso,
  onNewAnalysis,
  whatIfMode,
  onWhatIfModeChange,
  scenarioCategory,
  onScenarioCategoryChange,
  scenarioGroups,
  extraPois,
  onRemoveExtraPoi,
  onClearExtraPois,
  onRunScenario,
  baselineResult,
  viewMode,
  onViewModeChange,
}) {
  const limits = presets?.limits || { max_area_km2: 250, warn_area_km2: 40 };
  const tooBig = areaKm2 > limits.max_area_km2;
  const big = !tooBig && areaKm2 > limits.warn_area_km2;
  const areaTxt = areaKm2.toLocaleString("nl-NL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

  return (
    <aside className="sidebar">
      {presetsWarning && <p className="warning small">{presetsWarning}</p>}

      <section>
        <h2>Gebied</h2>
        <GeoSearch onAreaLoad={onAreaLoad} warnAreaKm2={limits.warn_area_km2} />
        {hasPolygon ? (
          <p>
            Oppervlak: <strong>{areaTxt} km²</strong>
          </p>
        ) : (
          <p className="hint">
            Zoek een gebied hierboven of teken een polygoon op de kaart (werkbalk linksboven op de
            kaart).
          </p>
        )}
        {big && (
          <p className="warning">
            Grote analyse (&gt; {limits.warn_area_km2} km²) — kan lang duren.
          </p>
        )}
        {tooBig && (
          <p className="error">
            Gebied te groot (&gt; {limits.max_area_km2} km²). Verklein de polygoon om te kunnen
            analyseren.
          </p>
        )}
      </section>

      <section>
        <h2>Vervoerswijze</h2>
        <div className="segmented">
          <button
            type="button"
            className={settings.mode === "walk" ? "active" : ""}
            onClick={() => onModeChange("walk")}
          >
            Lopen · 4,5 km/u
          </button>
          <button
            type="button"
            className={settings.mode === "bike" ? "active" : ""}
            onClick={() => onModeChange("bike")}
          >
            Fietsen · 15 km/u
          </button>
        </div>
        <label className="field">
          <span>Snelheid (km/u)</span>
          <input
            type="number"
            min="0.5"
            step="0.5"
            value={settings.speed_kmh}
            onChange={(e) => onSettingsChange({ speed_kmh: e.target.value })}
          />
        </label>
        <label className="field">
          <span>
            X-minutenstad: <strong>{settings.max_minutes} min</strong>
          </span>
          <input
            type="range"
            min="5"
            max="30"
            step="1"
            value={settings.max_minutes}
            onChange={(e) => onSettingsChange({ max_minutes: Number(e.target.value) })}
          />
        </label>
      </section>

      <section>
        <h2>Voorzieningen</h2>
        {presets ? (
          Object.entries(presets.poi_groups).map(([key, g]) => (
            <label key={key} className="check-row">
              <input
                type="checkbox"
                checked={settings.poi_groups.includes(key)}
                onChange={() => onToggleGroup(key)}
              />
              <span className="dot" style={{ background: groupColorMap[key] }} />
              <span>{g.label}</span>
            </label>
          ))
        ) : (
          <p className="hint">Voorinstellingen laden…</p>
        )}
        {presets && settings.poi_groups.length === 0 && (
          <p className="warning small">Kies minstens één voorzieningengroep.</p>
        )}
      </section>

      <section>
        <h2>Analyses</h2>
        {ANALYSIS_OPTIONS.map(({ key, label }) => {
          const disabled = key === "2sfca" && !settings.analyses.includes("population");
          return (
            <label key={key} className={"check-row" + (disabled ? " disabled" : "")}>
              <input
                type="checkbox"
                disabled={disabled}
                checked={settings.analyses.includes(key)}
                onChange={() => onToggleAnalysis(key)}
              />
              <span>{label}</span>
              {key === "2sfca" && disabled && (
                <span className="hint small">(vereist CBS-bevolking)</span>
              )}
            </label>
          );
        })}
        <details className="advanced">
          <summary>Geavanceerd</summary>
          <div className="field">
            <span>
              Hexresolutie <span className="hint small">(res 9 ≈ 0,1 km² per hex)</span>
            </span>
            <div className="segmented">
              {[8, 9, 10].map((r) => (
                <button
                  key={r}
                  type="button"
                  className={settings.hex_resolution === r ? "active" : ""}
                  onClick={() => onSettingsChange({ hex_resolution: r })}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
          <label className="field">
            <span>Beta (afstandsverval Hansen/2SFCA)</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={settings.beta}
              onChange={(e) => onSettingsChange({ beta: e.target.value })}
            />
          </label>
          <label className="field">
            <span>2SFCA-decay</span>
            <select
              value={settings.sfca_decay}
              onChange={(e) => onSettingsChange({ sfca_decay: e.target.value })}
            >
              <option value="exp">Exponentieel verval</option>
              <option value="binary">Binair (binnen bereik)</option>
            </select>
          </label>
        </details>
      </section>

      <section>
        <button type="button" className="run-btn" disabled={!canRun} onClick={onRun}>
          {running ? "Bezig met analyseren…" : "Analyseer gebied"}
        </button>
        {error && <p className="error">{error}</p>}
      </section>

      {job && !result && (
        <section>
          <h2>Voortgang</h2>
          <ProgressList job={job} />
        </section>
      )}

      {result && (
        <Results
          result={result}
          presets={presets}
          metricOptions={metricOptions}
          metric={metric}
          onMetricChange={onMetricChange}
          groupColorMap={groupColorMap}
          poiVisible={poiVisible}
          onTogglePoi={onTogglePoi}
          isoMode={isoMode}
          onIsoModeChange={onIsoModeChange}
          isoLoading={isoLoading}
          isoError={isoError}
          hasIsochrone={hasIsochrone}
          onClearIso={onClearIso}
          onNewAnalysis={onNewAnalysis}
          running={running}
          whatIfMode={whatIfMode}
          onWhatIfModeChange={onWhatIfModeChange}
          scenarioCategory={scenarioCategory}
          onScenarioCategoryChange={onScenarioCategoryChange}
          scenarioGroups={scenarioGroups}
          extraPois={extraPois}
          onRemoveExtraPoi={onRemoveExtraPoi}
          onClearExtraPois={onClearExtraPois}
          onRunScenario={onRunScenario}
          baselineResult={baselineResult}
          viewMode={viewMode}
          onViewModeChange={onViewModeChange}
        />
      )}
    </aside>
  );
}
