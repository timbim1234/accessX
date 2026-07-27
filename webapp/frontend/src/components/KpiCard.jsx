import { fmt } from "../metrics.js";

// Statuskleuren (ink-tokens): groen omhoog / rood omlaag voor de scenario-delta.
const UP = "#0ca30c";
const DOWN = "#d03b3b";

// 15-minutenstad-KPI bovenaan de resultaten: grote getallen voor de
// composietscore en "volledig voorzien", plus per-groep-balkjes. Bij een
// scenario toont de composiet-tegel het verschil t.o.v. de basis.
export default function KpiCard({ summary, baselineSummary, groupColorMap }) {
  if (!summary) return null;
  const perGroup = Array.isArray(summary.per_group) ? summary.per_group : [];
  const composite = summary.composite_pct;
  const fully = summary.fully_served_pct;

  let delta = null;
  if (
    baselineSummary &&
    typeof composite === "number" &&
    typeof baselineSummary.composite_pct === "number"
  ) {
    delta = composite - baselineSummary.composite_pct;
  }

  return (
    <div className="kpi-card">
      <h3>15-minutenstad-KPI</h3>
      <div className="kpi-tiles">
        {typeof composite === "number" && (
          <div className="kpi-tile">
            <div className="kpi-value">
              {fmt(composite, 1)}
              <span className="kpi-unit">%</span>
              {delta !== null && (
                <span className="kpi-delta" style={{ color: delta >= 0 ? UP : DOWN }}>
                  {delta >= 0 ? "▲ +" : "▼ "}
                  {fmt(delta, 1)}
                </span>
              )}
            </div>
            <div className="kpi-label">15-minutenstad-score</div>
          </div>
        )}
        {typeof fully === "number" && (
          <div className="kpi-tile">
            <div className="kpi-value">
              {fmt(fully, 1)}
              <span className="kpi-unit">%</span>
            </div>
            <div className="kpi-label">volledig voorzien</div>
          </div>
        )}
      </div>

      {perGroup.length > 0 && (
        <div className="kpi-bars">
          {perGroup.map((g) => (
            <div key={g.key} className="kpi-bar-row">
              <span className="kpi-bar-label" title={g.label}>
                {g.label}
              </span>
              <span className="kpi-bar-track">
                <span
                  className="kpi-bar-fill"
                  style={{
                    width: `${Math.max(0, Math.min(100, Number(g.pct) || 0))}%`,
                    background: groupColorMap[g.key] || "#898781",
                  }}
                />
              </span>
              <span className="kpi-bar-pct">{fmt(g.pct, 1)}%</span>
            </div>
          ))}
        </div>
      )}

      <div className="kpi-foot">
        {summary.weighted ? "bevolkingsgewogen" : "per hex (geen bevolking)"}
      </div>
    </div>
  );
}
