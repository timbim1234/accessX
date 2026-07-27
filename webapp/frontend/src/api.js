// Dunne fetch-laag rond de backend-API (zie CONTRACT.md).
// In dev proxyt Vite "/api" naar http://localhost:8000.

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data && data.detail) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // body was geen JSON; hou de HTTP-status aan
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export function getPresets(signal) {
  return request("/api/presets", { signal });
}

export function postAnalyze(body, signal) {
  return request("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export function getJob(jobId, signal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`, { signal });
}

export function getJobResult(jobId, signal) {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/result`, { signal });
}

export function getIsochrone(jobId, hexId, interval = 5, signal) {
  const q = `hex_id=${encodeURIComponent(hexId)}&interval=${encodeURIComponent(interval)}`;
  return request(`/api/jobs/${encodeURIComponent(jobId)}/isochrone?${q}`, { signal });
}

// PDOK Locatieserver (via backend-proxy): suggesties bij een zoekterm.
export function getGeocode(q, signal) {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal });
}

// PDOK Locatieserver (via backend-proxy): geometrie + oppervlak van één item.
export function getArea(lsid, signal) {
  return request(`/api/area/${encodeURIComponent(lsid)}`, { signal });
}
