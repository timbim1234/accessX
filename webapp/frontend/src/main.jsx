import React from "react";
import ReactDOM from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "leaflet-draw/dist/leaflet.draw.css";
import "./tokens.css";
import "./App.css";
import App from "./App.jsx";

// Workaround voor bekende leaflet-draw 1.0.4-bug onder strikte ESM-bundling:
// L.GeometryUtil.readableArea lekt een globale `type`-variabele. Zonder bestaande
// binding gooit een toewijzing daaraan in strict mode een ReferenceError.
if (typeof window !== "undefined" && window.type === undefined) {
  window.type = "";
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
