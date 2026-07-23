import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      onwarn(warning, warn) {
        // Bekende, onschadelijke warning: react-leaflet-draw doet
        // `import Draw from "leaflet-draw"` maar gebruikt de (niet-bestaande)
        // default export nergens; leaflet-draw is een side-effect-plugin op L.
        if (
          warning.code === "MISSING_EXPORT" &&
          String(warning.exporter || "").includes("leaflet-draw") &&
          String(warning.id || "").includes("react-leaflet-draw")
        ) {
          return;
        }
        warn(warning);
      },
    },
  },
});
