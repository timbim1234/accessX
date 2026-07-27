import { useEffect, useRef, useState } from "react";
import { getArea, getGeocode } from "../api.js";
import { fmt } from "../metrics.js";

const TYPE_LABELS = {
  gemeente: "gemeente",
  woonplaats: "woonplaats",
  wijk: "wijk",
  buurt: "buurt",
};

// Zoekbalk voor de sidebar-sectie "Gebied": debounce (~300 ms) op /api/geocode,
// klik op een resultaat -> /api/area/{id} -> laad de geometrie als AOI.
export default function GeoSearch({ onAreaLoad, warnAreaKm2 }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loaded, setLoaded] = useState(null); // { label, area_km2 }
  const acRef = useRef(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setResults([]);
      setOpen(false);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    const timer = setTimeout(async () => {
      if (acRef.current) acRef.current.abort();
      const ac = new AbortController();
      acRef.current = ac;
      try {
        const data = await getGeocode(q, ac.signal);
        setResults(data.results || []);
        setOpen(true);
        setError(null);
      } catch (e) {
        if (e.name === "AbortError") return;
        console.error("Zoeken mislukt:", e);
        setError(`Zoeken mislukt: ${e.message}`);
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const pick = async (item) => {
    setOpen(false);
    setQuery(item.label);
    setResults([]);
    setLoading(true);
    setError(null);
    setLoaded(null);
    try {
      const area = await getArea(item.id);
      onAreaLoad(area.geometry);
      setLoaded({ label: area.label || item.label, area_km2: area.area_km2 });
    } catch (e) {
      console.error("Gebied laden mislukt:", e);
      setError(`Gebied laden mislukt: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const big =
    loaded &&
    typeof loaded.area_km2 === "number" &&
    typeof warnAreaKm2 === "number" &&
    loaded.area_km2 > warnAreaKm2;

  return (
    <div className="geosearch">
      <input
        type="text"
        className="geosearch-input"
        placeholder="Zoek gemeente, wijk of buurt…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
      />
      {searching && <p className="hint small">Zoeken…</p>}
      {open && results.length > 0 && (
        <ul className="geosearch-results">
          {results.map((r) => (
            <li key={r.id}>
              <button type="button" className="geosearch-item" onClick={() => pick(r)}>
                <span className="geosearch-name">{r.label}</span>
                <span className="geosearch-type">{TYPE_LABELS[r.type] || r.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {loading && <p className="hint small">Gebied laden…</p>}
      {error && <p className="error small">{error}</p>}
      {loaded && (
        <p className="hint small">
          Geladen: <strong>{loaded.label}</strong>
          {typeof loaded.area_km2 === "number" ? ` · ${fmt(loaded.area_km2, 1)} km²` : ""}
        </p>
      )}
      {big && (
        <p className="warning small">
          Groot gebied ({fmt(loaded.area_km2, 0)} km²). Tip: kies bij grote gebieden hexresolutie 8
          voor een snellere analyse.
        </p>
      )}
    </div>
  );
}
