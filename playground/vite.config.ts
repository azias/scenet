import { defineConfig } from "vite";

/**
 * The playground build.
 *
 * `base` is settable because the same bundle is served from two places: `/` when you
 * run `npm run dev`, and `/scenet/playground/` on GitHub Pages. Every asset reference in
 * the app is resolved against `document.baseURI` rather than hardcoded, so this is the
 * only place the difference appears.
 */
export default defineConfig({
  base: process.env["SCENET_BASE"] ?? "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Monaco is large and splits into many chunks. The default 500 kB warning fires on
    // every build and says nothing useful about a page that also ships a Python
    // interpreter.
    chunkSizeWarningLimit: 4000,
  },
  worker: {
    format: "es",
  },
  optimizeDeps: {
    // Pyodide loads its own WebAssembly and looks for sibling files at runtime. Letting
    // Vite pre-bundle it rewrites those paths and it stops finding them.
    exclude: ["pyodide"],
  },
  server: {
    headers: {
      // Not required by Pyodide today, but these are what let it use SharedArrayBuffer
      // if a future version wants to, and they cost nothing in development.
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "credentialless",
    },
  },
});
