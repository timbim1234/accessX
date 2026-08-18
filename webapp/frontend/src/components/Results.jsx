import { useState } from "react";

import { postExport } from "../api.js";
import KpiCard from "./KpiCard.jsx";
import LorenzChart from "./LorenzChart.jsx";
import Sectie, { Methode } from "./Sectie.jsx";
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
  jobId,
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
  isochrone,
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
  const bvo = result.bvo || null;
  const groen = result.groen || null;
  const baselineSummary = baselineResult?.summary || null;
  const hasScenario = Boolean(baselineResult);
  const placed = extraPois || [];
  const zichtbarePoiGroepen = groupKeys.filter((k) => k in nPois);
  // Waar het getoonde isochroon vandaan komt: de naam van de voorziening als
  // die er is, anders het type vertrekpunt.
  const isoOrigin = isochrone?.origin || null;
  const isochroonLabel = hasIsochrone
    ? isoOrigin?.label || (isoOrigin?.type === "punt" ? "vanaf voorziening" : "vanaf hex")
    : null;
  const totaalPois = zichtbarePoiGroepen.reduce((n, k) => n + (nPois[k] || 0), 0);

  // GPKG/SHP maakt de backend met GDAL (kan niet in de browser). Het getoonde
  // isochroon gaat mee in de request omdat het niet in het jobresultaat zit.
  const [exportBezig, setExportBezig] = useState(null); // "gpkg" | "shp" | null
  const [exportFout, setExportFout] = useState(null);

  async function downloadBestand(fmt) {
    if (!jobId || exportBezig) return;
    setExportBezig(fmt);
    setExportFout(null);
    try {
      const { blob, filename } = await postExport(jobId, {
        format: fmt,
        isochrone: isochrone || null,
      });
      downloadBlob(filename || `accessx_export.${fmt === "gpkg" ? "gpkg" : "zip"}`, blob);
    } catch (e) {
      console.error("Export mislukt:", e);
      setExportFout(`Export mislukt: ${e.message}`);
    } finally {
      setExportBezig(null);
    }
  }

  // Welke kaartmetrieken zitten er in dit resultaat? Bepaalt welke uitleg
  // zinvol is om te tonen.
  const heeftMetriek = (prefix) =>
    metricOptions.some((g) => g.options.some((o) => o.value.startsWith(prefix)));

  return (
    <section className="results">
      <h2>Resultaten</h2>

      <p className="results-context">
        {fmt(meta.n_hexes, 0)} hexes · {fmt(meta.area_km2, 1)} km²
        {meta.population_total !== null && meta.population_total !== undefined
          ? ` · ${fmt(meta.population_total, 0)} inwoners`
          : ""}
      </p>

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

      {summary && (
        <Sectie
          titel="15-minutenstad-score"
          kern={
            summary.composite_pct !== null && summary.composite_pct !== undefined
              ? `${fmt(summary.composite_pct, 0)}%`
              : null
          }
          open
        >
          <Methode>
            Per categorie het aandeel {summary.weighted ? "inwoners" : "hexes"} dat
            binnen {fmt(summary.max_minutes, 0)} minuten lopen minstens één voorziening
            bereikt, gerouteerd over het echte straatnetwerk. De totaalscore is het
            gemiddelde over de gekozen categorieën.
          </Methode>
          <KpiCard
            summary={summary}
            baselineSummary={hasScenario ? baselineSummary : null}
            groupColorMap={groupColorMap}
          />
        </Sectie>
      )}

      {groen ? (
        <Sectie
          titel={`Groen binnen ${fmt(groen.norm_m, 0)} m`}
          kern={`${fmt(groen.pct_binnen_norm, 0)}%`}
        >
          <Methode>
            Loopafstand over het netwerk tot de <em>rand</em> van het dichtstbijzijnde
            groengebied van minstens {fmt(groen.min_area_m2 / 10000, 1)} ha — niet
            hemelsbreed, en niet tot het middelpunt: bij een groot park scheelt dat
            honderden meters. Dit is de 300 m uit de 3-30-300-regel.
          </Methode>
          <div className="groen-card">
            <div className="groen-score">
              <strong>{fmt(groen.pct_binnen_norm, 0)}</strong>
              <span className="unit">%</span>
              <span className="groen-score-label">
                van de {groen.gewogen ? "inwoners" : "hexes"} haalt de norm
              </span>
            </div>
            <div className="groen-bar">
              <div
                className="groen-bar-fill"
                style={{ width: `${Math.max(0, Math.min(100, groen.pct_binnen_norm))}%` }}
              />
            </div>
            <dl className="kv">
              <div>
                <dt>Mediaan loopafstand</dt>
                <dd>{fmt(groen.mediaan_afstand_m, 0)} m</dd>
              </div>
              <div>
                <dt>Groenvlakken in en om het gebied</dt>
                <dd>
                  {fmt(groen.n_groenvlakken, 0)} · {fmt(groen.groen_ha, 0)} ha
                </dd>
              </div>
            </dl>
          </div>
        </Sectie>
      ) : null}

      {bvo?.per_group?.length ? (
        <Sectie
          titel="Vloeroppervlakte (BAG)"
          kern={`${fmt(bvo.m2_totaal, 0)} m²`}
        >
          <Methode>
            Elke voorziening is gekoppeld aan een BAG-verblijfsobject, bij voorkeur op
            adres en anders op ligging binnen het pand. <strong>Typisch</strong> is
            aantal × mediaan: dat cijfer is ongevoelig voor complexen die als één
            verblijfsobject geregistreerd staan. De ⚠ markeert precies zulke
            uitschieters — staat die er, gebruik dan <em>typisch</em>. Buitenruimte
            zoals parken en speeltuinen heeft geen verblijfsobject en dus terecht geen
            m².
          </Methode>
          <table className="bvo-table">
            <tbody>
              {bvo.per_group
                .filter((g) => g.n_met_m2 > 0)
                .map((g) => (
                  <tr key={g.key}>
                    <td>
                      <span className="dot" style={{ background: groupColorMap[g.key] }} />
                      {g.label}
                      <span className="bvo-sub">
                        typisch {fmt(g.m2_typisch, 0)} m²
                        {g.adres_pct > 0 ? ` · ${fmt(g.adres_pct, 0)}% op adres` : ""}
                        {" · "}
                        {fmt(g.zeker_pct, 0)}% doel klopt
                        {g.n_met_m2 < g.n ? ` · ${g.n_met_m2}/${g.n} gekoppeld` : ""}
                      </span>
                    </td>
                    <td className="num">
                      {fmt(g.m2_totaal, 0)}
                      {g.n_uitschieters > 0 ? (
                        <span
                          className="bvo-flag"
                          title={`${g.n_uitschieters} uitschieter(s): waarschijnlijk een heel complex dat als één verblijfsobject is geregistreerd. Kijk dan naar "typisch".`}
                        >
                          ⚠
                        </span>
                      ) : null}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Sectie>
      ) : null}

      {gini || lorenz ? (
        <Sectie
          titel="Verdeling & Gini"
          kern={gini ? fmt(Object.values(gini)[0], 2, 2) : null}
        >
          <Methode>
            Hoe gelijk de bereikbaarheid over het gebied verdeeld is. 0 betekent dat
            iedereen evenveel bereikt, 1 dat alles bij één plek zit. De Lorenz-curve
            toont dezelfde verdeling grafisch: hoe verder van de diagonaal, hoe
            ongelijker.
            {equity?.gini_weighted ? " Bevolkingsgewogen." : ""}
          </Methode>
          {gini && (
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
          )}
          {lorenz && (
            <LorenzChart lorenz={lorenz} presets={presets} groupColorMap={groupColorMap} />
          )}
        </Sectie>
      ) : null}

      <Sectie titel="Kaartmetrieken uitgelegd">
        <Methode>
          Wat de kiezer hierboven op de kaart zet. Alle afstanden zijn gerouteerd over
          het loopnetwerk, niet hemelsbreed.
        </Methode>
        <dl className="kv uitleg">
          {heeftMetriek("count_") && (
            <div>
              <dt>Aantal bereikbaar</dt>
              <dd>
                Hoeveel voorzieningen van die categorie er vanaf deze hex binnen de
                tijdsdrempel te bereiken zijn. Telt stuks, niet omvang.
              </dd>
            </div>
          )}
          {heeftMetriek("nearest_cost_") && (
            <div>
              <dt>Minuten naar dichtstbijzijnde</dt>
              <dd>
                Reistijd naar de eerste voorziening van die categorie. Leeg als er
                binnen de drempel geen is.
              </dd>
            </div>
          )}
          {heeftMetriek("hansen_") && (
            <div>
              <dt>Hansen</dt>
              <dd>
                Alle bereikbare voorzieningen bij elkaar opgeteld, maar hoe verder weg
                hoe minder ze meetellen (afstandsverval). Eén voorziening om de hoek
                weegt zwaarder dan drie op tien minuten.
              </dd>
            </div>
          )}
          {heeftMetriek("sfca_") && (
            <div>
              <dt>2SFCA</dt>
              <dd>
                Vraag tegen aanbod: voorzieningen worden verdeeld over iedereen die ze
                kan bereiken. Een supermarkt die door 10.000 mensen wordt gedeeld
                scoort lager dan dezelfde supermarkt met 500 gebruikers.
              </dd>
            </div>
          )}
          {heeftMetriek("bvo_hansen_") && (
            <div>
              <dt>Bereikbaar vloeroppervlak</dt>
              <dd>
                Zelfde rekenwijze als Hansen, maar elke voorziening telt mee voor haar
                m² in plaats van als "1". Drie buurtsupers zijn dan iets anders dan
                drie avondwinkels.
              </dd>
            </div>
          )}
          {heeftMetriek("groen_") && (
            <div>
              <dt>Loopafstand tot groen</dt>
              <dd>
                Meters lopen naar de rand van het dichtstbijzijnde groengebied; de
                ja/nee-variant kleurt of dat binnen 300 m valt.
              </dd>
            </div>
          )}
          <div>
            <dt>Bevolking (CBS)</dt>
            <dd>Inwoners per hex uit het CBS-vierkantennet, als achtergrond bij de rest.</dd>
          </div>
        </dl>
      </Sectie>

      <Sectie
        titel="Voorzieningen op de kaart"
        kern={fmt(totaalPois, 0)}
      >
        <Methode>
          Aan- en uitzetten van de stippen op de kaart. Het getal is het aantal
          gevonden voorzieningen in het geanalyseerde gebied, inclusief de loopbuffer
          eromheen.
        </Methode>
        {zichtbarePoiGroepen.map((k) => (
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
          <p className="hint small">
            + {fmt(meta.n_extra_pois, 0)} scenario-voorziening(en) meegerekend.
          </p>
        ) : null}
      </Sectie>

      <Sectie
        titel="Wat-als scenario"
        kern={placed.length ? `${placed.length} geplaatst` : null}
      >
        <Methode>
          Plaats fictieve voorzieningen op de kaart en herbereken. Daarna kun je boven
          wisselen tussen het scenario en het verschil met de basisanalyse.
        </Methode>
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
                <span
                  className="dot"
                  style={{ background: groupColorMap[p.category] || "#898781" }}
                />
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
      </Sectie>

      <Sectie
        titel="Isochroon"
        kern={isochroonLabel}
        open={Boolean(isoMode || hasIsochrone)}
      >
        <Methode>
          Klik op een hex of op een voorziening, en de kaart toont het gebied dat
          vanaf dat punt binnen de tijdsdrempel te belopen is — de werkelijke vorm
          over het stratennet, niet een cirkel. Vanaf een voorziening beantwoordt dat
          de omgekeerde vraag: wie kan hier binnen de tijd komen?
        </Methode>
        {isoMode && (
          <p className="hint small">
            De stippen op de kaart zijn nu aanklikbaar als vertrekpunt.
          </p>
        )}
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
      </Sectie>

      <Sectie titel="Exporteren">
        <Methode>
          GeoPackage en Shapefile bevatten drie lagen in RD New (EPSG:28992):
          de hexes met alle berekende waarden, de voorzieningen als punten en
          — als er een isochroon open staat — de ringen daarvan. GeoJSON en
          CSV bevatten alleen de hexes (WGS84, resp. zonder geometrie).
        </Methode>
        <p className="small">
          Lagen in deze export: hexes, voorzieningen
          {hasIsochrone
            ? `, isochroon (${isochroonLabel})`
            : " — er staat geen isochroon open"}
          .
        </p>
        <div className="export-row">
          <button
            type="button"
            className="secondary-btn"
            disabled={!jobId || Boolean(exportBezig)}
            onClick={() => downloadBestand("gpkg")}
          >
            {exportBezig === "gpkg" ? "Bezig..." : "GeoPackage (.gpkg)"}
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={!jobId || Boolean(exportBezig)}
            onClick={() => downloadBestand("shp")}
          >
            {exportBezig === "shp" ? "Bezig..." : "Shapefile (.zip)"}
          </button>
        </div>
        <div className="export-row">
          <button type="button" className="secondary-btn" onClick={() => exportGeoJSON(result)}>
            Download GeoJSON
          </button>
          <button type="button" className="secondary-btn" onClick={() => exportCSV(result)}>
            Download CSV
          </button>
        </div>
        {exportFout && <p className="error small">{exportFout}</p>}
      </Sectie>

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
