# Playground

The Scenet compiler running in a browser, published to GitHub Pages.

## Why there is no compiler in here

The obvious way to build a browser playground for a DSL is to reimplement the compiler
in TypeScript. That forks the geometry into two codebases which slowly disagree, and
the browser version is the one nobody tests.

[Pyodide](https://pyodide.org/) ships `shapely`, `geos`, `numpy`, `pydantic` and
`kiwisolver` compiled to WebAssembly, and `fontTools`, `pyyaml` and the font packages
are pure Python. So the actual compiler runs unmodified, and the TypeScript here only
moves strings across the boundary.

The page installs the exact wheel `uv build` produces. Nothing is rebuilt or
transformed for the browser.

## Building

```bash
uv build --wheel        # from the repository root
cd playground
npm ci
npm run build           # writes public/
```

Then serve `public/` over HTTP — `file://` will not work, because Pyodide and micropip
both need real requests.

```bash
python -m http.server 8123 --directory public
```
