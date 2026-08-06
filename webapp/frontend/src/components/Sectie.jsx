// Uitklapbare sectie op <details>: geen state nodig, toetsenbord- en
// screenreader-toegankelijk, en de browser onthoudt zelf of hij open staat.
// De `kern` is het cijfer dat zichtbaar blijft als de sectie dicht is, zodat
// een paneel scanbaar blijft zonder alles open te klappen. `actie` is een
// bedieningselement rechts in de kop; klikken daarop mag de sectie niet open-
// of dichtklappen, vandaar dat het event daar stopt. Bewust alleen
// stopPropagation en geen preventDefault: dat laatste zou de eigen werking van
// een checkbox erin blokkeren.
export default function Sectie({
  titel,
  kern,
  actie,
  open = false,
  className = "",
  children,
}) {
  return (
    <details className={`acc ${className}`.trim()} open={open}>
      <summary>
        <span className="acc-titel">{titel}</span>
        {kern !== undefined && kern !== null ? (
          <span className="acc-kern">{kern}</span>
        ) : null}
        {actie ? (
          <span className="acc-actie" onClick={(e) => e.stopPropagation()}>
            {actie}
          </span>
        ) : null}
      </summary>
      <div className="acc-body">{children}</div>
    </details>
  );
}

// Korte uitleg van een methodiek, in de taal van de gebruiker.
export function Methode({ children }) {
  return <p className="methode">{children}</p>;
}
