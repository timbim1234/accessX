# CityMaker Styling — Handoff / Referentie

> Toegepast op het accessX-testlab (`webapp/frontend`). Bron: CityMaker design system
> (Next.js 15 + React 19). Hier geïmplementeerd in plain CSS: `src/tokens.css`
> (alle custom properties) + `src/App.css` (component-styling die de tokens consumeert).
> Roboto wordt geladen via `index.html`. Dataviz-kleuren (choropleth, POI-categorieën,
> verschil-schema) staan in `src/metrics.js` en volgen het CityMaker **data-palet**.

## Kern in één zin
Zeer afgeronde (24px/pill) UI, kleine Roboto-tekst (12px) met 0.03em letterspacing,
zacht gradient-lila background, neutrale clay-grijzen voor structuur, sky-blauw voor
primaire acties/selectie, lavender-paars voor interactieve/actieve states, subtiele
schaduwen en scale(0.95–1.02) micro-interacties.

## Tokens (zie tokens.css)
- **Kleurschalen** (100 = sterkst → 20 = lichtst, + surface): Sky (blauw), Lavender
  (paars), Clay (grijs). Neutraal: `--black #101010`, `--white #FFFFFF`.
  Rolverdeling: Clay = neutrale UI/structuur; Sky = primair/positief accent; Lavender =
  interactief/geselecteerd in tools.
- **Data-palet** (alleen grafieken/dataviz, géén UI): sage, sand, sky, lavender, orchid,
  apricot, rose, teal, graphite — zacht + sterk paar per kleur ("strong" = serie-kleur).
- **Gradients**: `--gradient-base` (paginabg lila), `--gradient-accent` (floating panels),
  `--gradient-white`. **Schaduwen**: `--shadow-modal`, `--shadow-panel`.
- **Typografie** (font-shorthand incl. family): `--heading-strong/heading/section/
  body-strong/body/body-light/label-strong/label-light`. Basis-body = 12px.
- **Spacing** 4px-grid `--space-1..16`. **Radius** xs16/sm20/md24/lg40/full. **Sizes**
  `--size-sm/md/lg` (32/36/40), icon-sizes.

## Toegepast op deze tool
- Sidebar + kaart zijn afgeronde witte "floating cards" op de lila gradient-canvas.
- Knoppen: primair = sky (`--run-btn`), secundair = wit + clay-border; active scale(0.95).
- Inputs/selects: 36px, radius-md, clay-20 border, focus = 2px sky.
- KPI-kaart = zacht sky-panel; legenda = floating witte card met zachte schaduw.
- Rij-hover in lijsten = lavender wash (`--row-hover`).
- Dataviz: choropleth = sky-sequential ramp; POI-categorieën = data-palet "strong"
  (parken/speeltuinen/volkstuinen in groen/teal/zand); verschil = sky↔rose divergent.

Wil je de bron-uitdraai onaangepast? Deze samenvatting is de repo-kopie; het volledige
handoff-document is in de chat aangeleverd.
