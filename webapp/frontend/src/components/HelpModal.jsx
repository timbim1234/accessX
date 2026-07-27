import { useEffect } from "react";

// Uitleg van alle methoden en berekeningen achter de analyses. Inhoud volgt de
// accessX-library (netwerkgebaseerde bereikbaarheid). Formules in leesbare notatie.
const SECTIONS = [
  {
    title: "Reisnetwerk & reistijd — de “kosten”",
    body: (
      <>
        Alle analyses routeren over het <b>echte straatnetwerk</b> (OpenStreetMap),
        niet hemelsbreed. Elke straat krijgt een reistijd op basis van de snelheid
        (lopen 4,5 km/u of fietsen 15 km/u, aanpasbaar). De <b>“X”</b> in
        X-minutenstad is die kostendrempel (bv. 15 minuten). Alle modellen gebruiken
        dezelfde reiskost, dus je kunt hetzelfde gebied door verschillende definities
        van bereikbaarheid halen.
      </>
    ),
  },
  {
    title: "Hexgrid (H3)",
    body: (
      <>
        Het gebied wordt opgedeeld in zeshoeken (H3, resolutie 8–10). Elke hex is
        een <b>herkomst</b>; vanaf het middelpunt wordt over het netwerk gerouteerd naar
        de voorzieningen. Resolutie 9 ≈ 0,1 km² per hex (fijner = meer detail,
        langzamer).
      </>
    ),
  },
  {
    title: "Voorzieningen & bevolking",
    body: (
      <>
        Voorzieningen (POI’s) komen uit OpenStreetMap, gegroepeerd in categorieën
        (boodschappen, zorg, onderwijs, groen, OV…). Bevolking komt uit het{" "}
        <b>CBS 100 m-grid</b> en wordt oppervlakte-gewogen aan de hexes toegekend
        (inclusief leeftijdsgroepen). Deze vormen de vraag- en aanbodkant van de modellen.
      </>
    ),
  },
  {
    title: "Aantal bereikbaar — cumulatieve opportuniteiten",
    body: (
      <>
        Telt hoeveel voorzieningen per categorie je vanaf een hex binnen de drempel
        <i> X</i> kunt bereiken. Simpel en intuïtief: “hoeveel supermarkten binnen
        15 loopminuten”.
      </>
    ),
    formula: "count(i) = aantal j met  c(i, j) ≤ X",
  },
  {
    title: "Dichtstbijzijnde voorziening",
    body: (
      <>
        De <b>minimale netwerkkost</b> tot de dichtstbijzijnde voorziening per categorie.
        Toont gaten in de dekking: waar is de dichtstbijzijnde huisarts bínnen of
        búiten X minuten?
      </>
    ),
    formula: "nearest(i) = minⱼ c(i, j)",
  },
  {
    title: "Hansen-bereikbaarheid — afstandsverval",
    body: (
      <>
        Weegt nabije bestemmingen zwaarder dan verre, met een vloeiend verval in plaats
        van een harde grens. <i>Oⱼ</i> = gewicht/aantrekkelijkheid van bestemming{" "}
        <i>j</i>, <i>c</i> = reistijd, <i>β</i> = vervalparameter (hoger = sneller
        verval). <span className="help-ref">Hansen (1959).</span>
      </>
    ),
    formula: "A(i) = Σⱼ  Oⱼ · exp(−β · c(i, j))",
  },
  {
    title: "2SFCA — vraag versus aanbod",
    body: (
      <>
        Twee stappen. <b>1)</b> Per voorziening: het aanbod gedeeld door alle bereikbare
        vraag eromheen. <b>2)</b> Per hex: de som van de bereikbare aanbod-ratio’s.
        <i> S</i> = capaciteit/aanbod, <i>D</i> = bevolking (vraag), <i>f</i> = verval
        (binair of exponentieel). Meet dus de <b>druk</b> op voorzieningen ten opzichte
        van de omliggende bevolking. <span className="help-ref">Luo &amp; Wang (2003).</span>
      </>
    ),
    formula:
      "1)  R(j) = S(j) ⁄ Σₖ D(k)·f(c(k,j))\n2)  A(i) = Σⱼ R(j)·f(c(i,j))",
  },
  {
    title: "Verdeling & Gini (Lorenz)",
    body: (
      <>
        Hoe (on)gelijk is bereikbaarheid verdeeld? De Lorenz-curve zet het cumulatieve
        bevolkingsaandeel (x) af tegen het cumulatieve bereikbaarheidsaandeel (y).
        De <b>Gini-index</b> vat dat samen: 0 = perfect gelijk, 1 = maximaal ongelijk.
        Bevolkingsgewogen wanneer CBS-data aanwezig is.
      </>
    ),
    formula: "Gini = 1 − 2 · (oppervlak onder de Lorenz-curve)",
  },
  {
    title: "15-minutenstad-score — sufficiëntie",
    body: (
      <>
        Per hex wordt getoetst of een mandje <b>minimumdrempels</b> wordt gehaald
        (bv. ≥ 1 supermarkt én ≥ 1 huisarts binnen X min). De score is het
        aandeel behaalde drempels (0–1). De KPI-kaart aggregeert dit bevolkingsgewogen:
        “welk % van de inwoners haalt de drempels”.
      </>
    ),
    formula: "score(i) = behaalde drempels ⁄ totaal aantal drempels",
  },
  {
    title: "Isochronen",
    body: (
      <>
        Loopbereik-polygonen: vanaf een gekozen hex alle plekken die binnen 5/10/15
        minuten bereikbaar zijn over het netwerk. Een visuele laag bovenop de scores
        (klik een hex met de isochroon-modus aan).
      </>
    ),
  },
  {
    title: "Wat-als scenario",
    body: (
      <>
        Plaats fictieve voorzieningen op de kaart en herbereken. De weergave
        <b> “Verschil t.o.v. basis”</b> toont per hex de verandering
        (blauw = beter bereikbaar, rood = slechter). Zo zie je de winst van een nieuw
        park of een nieuwe supermarkt <i>vóór</i> je bouwt.
      </>
    ),
  },
];

export default function HelpModal({ onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="help-overlay" onClick={onClose}>
      <div
        className="help-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Methoden en berekeningen"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="help-modal__header">
          <span className="help-modal__title">Methoden &amp; berekeningen</span>
          <button className="help-close" onClick={onClose} aria-label="Sluiten" title="Sluiten">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="help-modal__body">
          <p className="help-intro">
            De analyses zijn netwerkgebaseerd (over straten, niet hemelsbreed) en komen uit
            de <b>accessX</b>-library. Data: OpenStreetMap (voorzieningen) en CBS (bevolking).
          </p>
          {SECTIONS.map((s) => (
            <section className="help-section" key={s.title}>
              <h3 className="help-section__title">{s.title}</h3>
              <p className="help-section__body">{s.body}</p>
              {s.formula && <pre className="help-formula">{s.formula}</pre>}
            </section>
          ))}
          <p className="help-foot">
            Meer achtergrond: zie de accessX-documentatie en de README van deze testomgeving.
          </p>
        </div>
      </div>
    </div>
  );
}
