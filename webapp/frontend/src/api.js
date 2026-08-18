// Dunne fetch-laag rond de backend-API (zie CONTRACT.md).
// In dev proxyt Vite "/api" naar http://localhost:8000.

// FastAPI zet de melding in `detail`; die willen we letterlijk aan de
// gebruiker tonen in plaats van een kale statuscode.
async function foutVanRespons(res) {
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
  return err;
}

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) throw await foutVanRespons(res);
  return res.json();
}

// Bestandsnaam uit de Content-Disposition-header, zodat de download heet zoals
// de backend hem noemt (inclusief job-id).
function bestandsnaamUitHeader(header) {
  const m = /filename="?([^"]+)"?/i.exec(header || "");
  return m ? m[1] : null;
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

// Vertrekpunt is óf een hex ({ hexId }) óf een los punt ({ lon, lat, label }) —
// dat laatste voor een isochroon vanaf een aangeklikte voorziening.
export function getIsochrone(jobId, oorsprong, interval = 5, signal) {
  const p = new URLSearchParams();
  if (oorsprong?.hexId !== undefined && oorsprong?.hexId !== null) {
    p.set("hex_id", oorsprong.hexId);
  } else {
    p.set("lon", oorsprong.lon);
    p.set("lat", oorsprong.lat);
    if (oorsprong.label) p.set("label", oorsprong.label);
  }
  p.set("interval", interval);
  return request(`/api/jobs/${encodeURIComponent(jobId)}/isochrone?${p}`, { signal });
}

// PDOK Locatieserver (via backend-proxy): suggesties bij een zoekterm.
export function getGeocode(q, signal) {
  return request(`/api/geocode?q=${encodeURIComponent(q)}`, { signal });
}

// PDOK Locatieserver (via backend-proxy): geometrie + oppervlak van één item.
export function getArea(lsid, signal) {
  return request(`/api/area/${encodeURIComponent(lsid)}`, { signal });
}

// Export van hexes + voorzieningen + eventueel het getoonde isochroon als
// GeoPackage of gezipte Shapefile. Antwoord is een bestand, geen JSON; het
// isochroon gaat mee in de body omdat het niet in het jobresultaat zit.
export async function postExport(jobId, body, signal) {
  const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw await foutVanRespons(res);
  return {
    blob: await res.blob(),
    filename: bestandsnaamUitHeader(res.headers.get("Content-Disposition")),
  };
}
