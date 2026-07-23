import { metricGroupKey, metricLabel } from "../metrics.js";

// Statische Lorenz-minigrafiek (inline SVG, ~300x220), max 3 curves.
// P = cumulatief bevolkingsaandeel (x), A = cumulatief bereikbaarheidsaandeel (y).
export default function LorenzChart({ lorenz, presets, groupColorMap }) {
  const entries = Object.entries(lorenz || {}).slice(0, 3);
  const groupKeys = Object.keys(presets?.poi_groups || {});

  const W = 300;
  const H = 220;
  const m = { l: 34, r: 10, t: 10, b: 26 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;
  const sx = (p) => m.l + p * iw;
  const sy = (a) => m.t + (1 - a) * ih;

  const gridTicks = [0, 0.25, 0.5, 0.75, 1];
  const labelTicks = [0, 0.5, 1];

  const curves = entries
    .map(([key, d]) => {
      const P = Array.isArray(d?.P) ? d.P : [];
      const A = Array.isArray(d?.A) ? d.A : [];
      const n = Math.min(P.length, A.length);
      if (n < 2) return null;
      let path = "";
      for (let i = 0; i < n; i++) {
        path += `${i === 0 ? "M" : "L"}${sx(P[i]).toFixed(1)},${sy(A[i]).toFixed(1)}`;
      }
      const gk = metricGroupKey(key, groupKeys);
      return {
        key,
        path,
        color: (gk && groupColorMap[gk]) || "#52514e",
        label: metricLabel(key, presets),
      };
    })
    .filter(Boolean);

  return (
    <div className="lorenz-chart">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Lorenz-curves">
        {gridTicks.map((t) => (
          <g key={`grid-${t}`}>
            <line x1={sx(t)} y1={m.t} x2={sx(t)} y2={m.t + ih} stroke="#e1e0d9" strokeWidth="1" />
            <line x1={m.l} y1={sy(t)} x2={m.l + iw} y2={sy(t)} stroke="#e1e0d9" strokeWidth="1" />
          </g>
        ))}
        {labelTicks.map((t) => (
          <g key={`lbl-${t}`}>
            <text x={sx(t)} y={H - 8} textAnchor="middle" fontSize="10" fill="#898781">
              {t.toLocaleString("nl-NL")}
            </text>
            <text x={m.l - 6} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="#898781">
              {t.toLocaleString("nl-NL")}
            </text>
          </g>
        ))}
        <line
          x1={sx(0)}
          y1={sy(0)}
          x2={sx(1)}
          y2={sy(1)}
          stroke="#898781"
          strokeWidth="1"
          strokeDasharray="4 3"
        />
        {curves.map((c) => (
          <path key={c.key} d={c.path} fill="none" stroke={c.color} strokeWidth="2">
            <title>{c.label}</title>
          </path>
        ))}
      </svg>
      <div className="legend-chips">
        {curves.map((c) => (
          <span key={c.key} className="chip">
            <span className="dot" style={{ background: c.color }} />
            <span>{c.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
