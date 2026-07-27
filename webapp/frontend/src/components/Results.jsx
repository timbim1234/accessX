import KpiCard from "./KpiCard.jsx";
import LorenzChart from "./LorenzChart.jsx";
import { fmt, metricLabel } from "../metrics.js";

// Client-side download via een tijdelijke <a download> (geen backend).
function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportGeoJSON(result) {
  const hexes = result?.hexes;
  if (!hexes) return;
  const blob = new Blob([JSON.stringify(hexes)], { type: "application/geo+json" });
  downloadBlob("accessx_hexes.geojson", blob);
}

// ;-gescheiden CSV van de hex-properties (zonder geometry). Excel NL leest ;-CSV;
// kommagetallen blijven met punt. BOM zodat Excel UTF-8 goed herkent.
function exportCSV(result) {
  const features = result?.hexes?.features || [];
  if (!features.length) return;
  const keys = Object.keys(features[0].properties || {});
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[;"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [keys.join(";")];
  for (const f of features) {
    const p = f.properties || {};
    lines.push(keys.map((k) => esc(p[k])).join(";"));
  }
  const bom = String.fromCharCode(0xfeff); // UTF-8 BOM zodat Excel NL de tekens goed leest
  const blob = new Blob([bom + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  downloadBlob("accessx_hexes.csv", blob);
}

export default function Results({
  result,
  presets,
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
  running,
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
  const meta = result.meta || {};
  const equity = result.equity;
  const gini = equity?.gini && Object.keys(equity.gini).length ? equity.gini : null;
  const lorenz = equity?.lorenz && Object.keys(equity.lorenz).length ? equity.lorenz : null;
  const groupKeys = Object.keys(presets?.poi_groups || {});
  const nPois = meta.n_pois || {};
  const summary = result.summary || null;
  const baselineSummary = baselineResult?.summary || null;
  const hasScenario = Boolean(baselineResult);
  const placed = extraPois || [];

  return (
    <section className="results">
      <h2>Resultaten</h2>

      {summary && (
        <KpiCard
          summary={summary}
          baselineSummary={hasScenario ? baselineSummary : null}
          groupColorMap={groupColorMap}
        />
      )}

      <label className="field">
        <span>Kaartmetriek</span>
        <select value={metric || ""} onChange={(e) => onMetricChange(e.target.value)}>
          {metricOptions.map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      {hasScenario && (
        <div className="view-toggle">
          <span className="view-toggle-label">Toon</span>
          <div className="segmented">
            <button
              type="button"
              className={viewMode === "scenario" ? "active" : ""}
              onClick={() => onViewModeChange("scenario")}
            >
              Scenario
            </button>
            <button
              type="button"
              className={viewMode === "diff" ? "active" : ""}
              onClick={() => onViewModeChange("diff")}
            >
              Verschil t.o.v. basis
            </button>
          </div>
        </div>
      )}

      {gini && (
        <div className="gini">
          <h3>Gini per metriek</h3>
          <table className="gini-table">
            <tbody>
              {Object.entries(gini).map(([k, v]) => (
                <tr key={k}>
                  <td>{metricLabel(k, presets)}</td>
                  <td className="num">{fmt(v, 3, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {equity.gini_weighted && <p className="hint small">Bevolkingsgewogen.</p>}
        </div>
      )}

      {lorenz && (
        <div className="lorenz">
          <h3>Lorenz-curves</h3>
          <LorenzChart lorenz={lorenz} presets={presets} groupColorMap={groupColorMap} />
        </div>
      )}

      <div className="summary">
        <h3>Samenvatting</h3>
        <p>
          {fmt(meta.n_hexes, 0)} hexes · {fmt(meta.area_km2, 1)} km²
          {meta.population_total !== null && meta.population_total !== undefined
            ? ` · ${fmt(meta.population_total, 0)} inwoners`
            : ""}
        </p>
        <h4>Voorzieningen op de kaart</h4>
        {groupKeys
          .filter((k) => k in nPois)
          .map((k) => (
            <label key={k} className="check-row">
              <input
                type="checkbox"
                checked={Boolean(poiVisible[k])}
                onChange={() => onTogglePoi(k)}
              />
              <span className="dot" style={{ background: groupColorMap[k] }} />
              <span>{presets.poi_groups[k].label}</span>
              <span className="count">{fmt(nPois[k], 0)}</span>
            </label>
          ))}
        {meta.n_extra_pois ? (
          <p className="hint small">+ {fmt(meta.n_extra_pois, 0)} scenario-voorziening(en) meegerekend.</p>
        ) : null}
      </div>

      <div className="whatif">
        <h3>Wat-als scenario</h3>
        <label className="check-row">
          <input
            type="checkbox"
            checked={whatIfMode}
            onChange={(e) => onWhatIfModeChange(e.target.checked)}
          />
          <span>✚ Wat-als modus — klik op de kaart om een voorziening te plaatsen</span>
        </label>
        {whatIfMode && (
          <label className="field">
            <span>Categorie voor nieuwe voorziening</span>
            <select
              value={scenarioCategory || ""}
              onChange={(e) => onScenarioCategoryChange(e.target.value)}
            >
              {scenarioGroups.map((k) => (
                <option key={k} value={k}>
                  {presets?.poi_groups?.[k]?.label || k}
                </option>
              ))}
            </select>
          </label>
        )}
        {placed.length > 0 && (
          <div className="whatif-list">
            {placed.map((p, i) => (
              <div key={i} className="whatif-item">
                <span className="dot" style={{ background: groupColorMap[p.category] || "#898781" }} />
                <span className="whatif-cat">
                  {presets?.poi_groups?.[p.category]?.label || p.category}
                </span>
                <span className="whatif-coord">
                  {fmt(p.lat, 4)}, {fmt(p.lon, 4)}
                </span>
                <button type="button" className="link-btn" onClick={() => onRemoveExtraPoi(i)}>
                  verwijder
                </button>
              </div>
            ))}
            <div className="whatif-actions">
              <button type="button" className="link-btn" onClick={onClearExtraPois}>
                wis alle
              </button>
            </div>
          </div>
        )}
        <button
          type="button"
          className="secondary-btn"
          disabled={!placed.length || running}
          onClick={onRunScenario}
        >
          Herbereken met scenario ({placed.length})
        </button>
      </div>

      <div className="iso-row">
        <label className="check-row">
          <input
            type="checkbox"
            checked={isoMode}
            onChange={(e) => onIsoModeChange(e.target.checked)}
          />
          <span>🕐 Isochroon bij klik</span>
        </label>
        {isoLoading && <span className="spinner" />}
        {hasIsochrone && (
          <button type="button" className="link-btn" onClick={onClearIso}>
            wis isochroon
          </button>
        )}
      </div>
      {isoError && <p className="error small">{isoError}</p>}

      {(meta.warnings || []).map((w, i) => (
        <p key={i} className="warning small">
          {w}
        </p>
      ))}

      <div className="export-row">
        <button type="button" className="secondary-btn" onClick={() => exportGeoJSON(result)}>
          Download GeoJSON
        </button>
        <button type="button" className="secondary-btn" onClick={() => exportCSV(result)}>
          Download CSV
        </button>
      </div>

      <button type="button" className="secondary-btn" onClick={onNewAnalysis}>
        Nieuwe analyse
      </button>
    </section>
  );
}
