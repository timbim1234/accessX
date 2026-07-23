import { fmt } from "../metrics.js";

function StageIcon({ status }) {
  if (status === "done") return <span className="stage-icon done">✓</span>;
  if (status === "running")
    return (
      <span className="stage-icon">
        <span className="spinner" />
      </span>
    );
  if (status === "skipped") return <span className="stage-icon skipped">−</span>;
  return <span className="stage-icon pending">○</span>;
}

export default function ProgressList({ job }) {
  return (
    <div className="progress">
      {job.status === "queued" && <p className="hint small">In de wachtrij…</p>}
      <ul className="stage-list">
        {(job.stages || []).map((s) => (
          <li key={s.key} className={`stage ${s.status}`}>
            <StageIcon status={s.status} />
            <span className="stage-label">{s.label}</span>
            <span className="stage-meta">
              {s.seconds !== null && s.seconds !== undefined ? `${fmt(s.seconds, 1)} s` : ""}
            </span>
            {s.detail && <span className="stage-detail">{s.detail}</span>}
          </li>
        ))}
      </ul>
      {(job.warnings || []).map((w, i) => (
        <p key={i} className="warning small">
          {w}
        </p>
      ))}
    </div>
  );
}
