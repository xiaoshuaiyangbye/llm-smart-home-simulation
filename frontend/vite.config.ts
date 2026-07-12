import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          // The helper is needed by the entry to initiate lazy imports. Keeping
          // it separate prevents that entry edge from preloading three-runtime.
          if (id.includes("vite/preload-helper")) {
            return "vite-preload";
          }
          // Keep React in an entry-safe shared chunk. Otherwise Rollup folds it
          // into the 3D chunk through @react-three's transitive dependency graph.
          if (id.includes("node_modules/react/") || id.includes("node_modules/react-dom/")) {
            return "react-runtime";
          }
          if (id.includes("node_modules/three") || id.includes("node_modules/@react-three")) {
            return "three-runtime";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
