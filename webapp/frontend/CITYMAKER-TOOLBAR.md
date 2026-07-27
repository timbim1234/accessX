# CityMaker Toolbar — Styling Handoff (referentie)

Zwevende, volledig afgeronde witte pill-bar, gecentreerd onderaan de kaart. Iconen
zwart (#101010) via `currentColor`; actieve/tekenstates lavender-paars. Panelen
(Kaartweergave) zweven erboven met lila `--gradient-accent` en een witte binnencard.
Tooltips zijn donkere pills (clay-100).

## Toegepast op het accessX-testlab (`webapp/frontend`)
Faithful op look + structuur; knopgroepen gemapt op wat deze tool heeft:
- **Groep 1 — Kaartweergave**: basemap-thumbnail + paneel (Licht / Luchtfoto / OSM).
- **Groep 2 — Tekenen**: polygoon / rechthoek / wissen (vervangt de leaflet-draw-werkbalk).
- **Groep 3 — Navigatie**: fit-op-gebied / uitzoomen / inzoomen.
Weggelaten t.o.v. de GIS-tool: kaartlagen-, merge-, upload-, combine-knoppen
(POI-lagen zitten in de sidebar). Iconen: inline-SVG met `currentColor` (geen
externe assets), zodat active/drawing/disabled-states automatisch meekleuren.

## Kernwaarden
- Pill-bar: `height 52px · padding 8px · gap 4px · border-radius 48px ·
  box-shadow 0 4px 24px rgba(0,0,0,.12), 0 1px 4px rgba(0,0,0,.06) · z-index 1000`.
- Knop `.toolbar__btn` 36×36, `radius-full`, transparant, icon `#101010` via currentColor.
  hover → `--surface-clay`; `--active` → bg `--lavender-20` kleur `--lavender-100`;
  `--drawing` → bg `--lavender-100` kleur `--white`; `--disabled` → opacity .35.
- Divider: 1px × 20px `--clay-20`. Tooltip: `[data-tooltip]::after` donkere clay-100 pill.
- Paneel: `--gradient-accent` buitenrand, radius 24, padding 8, witte binnencard radius 20;
  rijen hover `--surface-clay`, actief lavender-accent + check.

De volledige bron-CSS is aangeleverd in de chat-handoff en 1-op-1 overgenomen in
`src/components/Toolbar.css` (aangepaste klassen weggelaten).
