// Inline-SVG iconenset voor de zwevende toolbar. Alle paden erven
// stroke="currentColor" van de <svg>, zodat de knop-states (hover, --active,
// --drawing) de icoonkleur meenemen. viewBox 0 0 24 24, afgeronde lijnen.
const ICONS = {
  // Lagen-/basemap-stapel (drie ruiten).
  map: (
    <>
      <path d="M12 3 20 7.5 12 12 4 7.5 Z" />
      <path d="M4 12 12 16.5 20 12" />
      <path d="M4 16.5 12 21 20 16.5" />
    </>
  ),
  // Potlood (polygoon tekenen): body + ferrule-lijn bij het uiteinde.
  pencil: (
    <>
      <path d="M4 20 4.8 16 15 5.8 18.2 9 8 19.2 Z" />
      <path d="M13 7.8 16.2 11" />
    </>
  ),
  // Rechthoek tekenen.
  rectangle: <rect x="4.5" y="6.5" width="15" height="11" rx="1.5" />,
  // Prullenbak (gebied wissen).
  trash: (
    <>
      <path d="M4 7 20 7" />
      <path d="M9 7 9 4.8a1.2 1.2 0 0 1 1.2-1.2h3.6a1.2 1.2 0 0 1 1.2 1.2V7" />
      <path d="M17.5 7 16.8 19.2a1.6 1.6 0 0 1-1.6 1.5H8.8a1.6 1.6 0 0 1-1.6-1.5L6.5 7" />
      <path d="M10 11 10 17" />
      <path d="M14 11 14 17" />
    </>
  ),
  // Inzoomen (+).
  "zoom-in": (
    <>
      <path d="M12 5 12 19" />
      <path d="M5 12 19 12" />
    </>
  ),
  // Uitzoomen (−).
  "zoom-out": <path d="M5 12 19 12" />,
  // Op gebied passen: vier hoekpijlen naar buiten.
  fit: (
    <>
      <path d="M9.5 9.5 4.5 4.5M4.5 8.5 4.5 4.5 8.5 4.5" />
      <path d="M14.5 9.5 19.5 4.5M15.5 4.5 19.5 4.5 19.5 8.5" />
      <path d="M14.5 14.5 19.5 19.5M19.5 15.5 19.5 19.5 15.5 19.5" />
      <path d="M9.5 14.5 4.5 19.5M4.5 15.5 4.5 19.5 8.5 19.5" />
    </>
  ),
  // Sluiten (×).
  close: (
    <>
      <path d="M6 6 18 18" />
      <path d="M18 6 6 18" />
    </>
  ),
  // Vinkje (actieve basemap).
  check: <path d="M5 12.5 10 17.5 19 6.5" />,
};

export default function ToolbarIcon({ name, size = 20 }) {
  const content = ICONS[name];
  if (!content) return null;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {content}
    </svg>
  );
}
