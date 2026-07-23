import LorenzChart from "./LorenzChart.jsx";
import { fmt, metricLabel } from "../metrics.js";

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
}) {
  const meta = result.meta || {};
  const equity = result.equity;
  const gini = equity?.gini && Object.keys(equity.gini).length ? equity.gini : null;
  const lorenz = equity?.lorenz && Object.keys(equity.lorenz).length ? equity.lorenz : null;
  const groupKeys = Object.keys(presets?.poi_groups || {});
  const nPois = meta.n_pois || {};

  return (
    <section className="results">
      <h2>Resultaten</h2>

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

      <button type="button" className="secondary-btn" onClick={onNewAnalysis}>
        Nieuwe analyse
      </button>
    </section>
  );
}
