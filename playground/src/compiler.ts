/**
 * The bridge to the compiler.
 *
 * There is deliberately no compiler in this file, or anywhere else in this directory.
 *
 * The obvious way to build a browser playground for a DSL is to reimplement the
 * compiler in TypeScript. That forks the geometry into two codebases which then drift
 * apart, and the browser version is always the one that is subtly wrong. Pyodide ships
 * shapely, geos, numpy, pydantic and kiwisolver compiled to WebAssembly, so the actual
 * Python compiler runs unmodified and this file only moves strings across the boundary.
 *
 * The wheel installed here is the exact artefact `uv build` produces. Not a copy of the
 * source, not a browser-specific build -- the same file that goes to PyPI.
 */

import { loadPyodide, type PyodideInterface } from "pyodide";

/** How the compiler reports back. Errors are data, not exceptions. */
export type CompileResult =
  | {
      readonly ok: true;
      readonly svg: string;
      readonly debug: string;
      readonly core: string;
      readonly notes: readonly string[];
      readonly panels: readonly string[];
    }
  | { readonly ok: false; readonly error: string };

/** Progress messages, so a twenty-second boot does not look like a hang. */
export type ProgressReporter = (message: string) => void;

interface WheelManifest {
  readonly wheel: string;
  /** Content-addressed path, so a rebuild at the same version is never served stale. */
  readonly path: string;
  readonly sha256: string;
}

/**
 * The Python side of the bridge.
 *
 * Exceptions are caught here and returned as JSON rather than allowed to cross the WASM
 * boundary. Letting them propagate loses the carefully written message, and for a
 * language playground the message is most of the value -- a diagnostic naming the
 * offending construct is the difference between a tool you can learn from and one that
 * simply says no.
 */
const BRIDGE = `
import json


def _scenet_compile(source, kind):
    try:
        from scenet import compile_scene, parse_script, compile_ir
        from scenet.emit.debug_svg import render_debug
        from scenet.emit.strip import render_strip
        from scenet.emit.svg import render

        if kind == "script":
            results = {
                name: compile_ir(panel) for name, panel in parse_script(source).items()
            }
        else:
            results = compile_scene(source)

        names = list(results)
        single = len(names) == 1

        if single:
            only = results[names[0]]
            svg = render(only.core)
            debug = render_debug(only.core)
            core = only.core.to_json()
        else:
            pairs = [(name, result.core) for name, result in results.items()]
            svg = render_strip(pairs)
            debug = render_strip(pairs)
            core = json.dumps(
                {name: json.loads(result.core.to_json()) for name, result in results.items()},
                indent=2,
                sort_keys=True,
            )

        notes = []
        for name, result in results.items():
            for note in result.notes:
                notes.append(note if single else f"{name}: {note}")

        return json.dumps({
            "ok": True,
            "svg": svg,
            "debug": debug,
            "core": core,
            "notes": notes,
            "panels": names,
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
`;

/** A booted compiler, ready to be handed source. */
export interface Compiler {
  compile(source: string, kind: string): Promise<CompileResult>;
  readonly version: string;
}

function assetUrl(path: string): string {
  return new URL(path, document.baseURI).href;
}

/**
 * Boot Pyodide, install Scenet, and return something that compiles.
 *
 * Takes ten to twenty seconds on a first visit and is mostly download; afterwards the
 * browser cache makes it fast. Every asset comes from this origin -- there is no CDN
 * involved, which is what allows the strict Content-Security-Policy on the page.
 *
 * @param report - Called with a human-readable message at each stage of the boot.
 */
export async function bootCompiler(report: ProgressReporter): Promise<Compiler> {
  report("Starting Python…");
  const pyodide: PyodideInterface = await loadPyodide({
    indexURL: assetUrl("pyodide/"),
  });

  report("Loading numeric libraries…");
  // Built for Pyodide and served from this origin; see scripts/fetch-assets.ts.
  await pyodide.loadPackage(
    ["micropip", "numpy", "pydantic", "kiwisolver", "shapely", "fonttools", "pyyaml"],
    { messageCallback: () => undefined },
  );

  report("Installing Scenet…");
  const response = await fetch(assetUrl("wheel.json"));
  if (!response.ok) {
    throw new Error("wheel.json is missing; run `uv build --wheel` then `npm run build`");
  }
  const manifest = (await response.json()) as WheelManifest;

  const fontWheels = (await (await fetch(assetUrl("font-wheels.json"))).json()) as string[];

  pyodide.globals.set("_scenet_wheel", assetUrl(manifest.path));
  pyodide.globals.set(
    "_scenet_fonts",
    fontWheels.map((name) => assetUrl(`pyodide/${name}`)),
  );
  await pyodide.runPythonAsync(`
import micropip
# The lettering font arrives as an ordinary Python dependency rather than a system
# lookup, because measuring text identically everywhere is what makes the output
# deterministic. Both wheels are vendored at build time and served from this origin, so
# the page reaches no other host -- which is what lets the CSP say 'self' and mean it.
await micropip.install(list(_scenet_fonts))
await micropip.install(_scenet_wheel)
`);

  await pyodide.runPythonAsync(BRIDGE);
  const version = String(await pyodide.runPythonAsync("__import__('scenet').__version__"));

  return {
    version,
    async compile(source: string, kind: string): Promise<CompileResult> {
      // Passed through globals rather than interpolated into Python source. Panel text
      // is arbitrary and would otherwise need escaping, which is a bug waiting for the
      // first person who writes a quotation mark in a line of dialogue.
      pyodide.globals.set("_scenet_source", source);
      pyodide.globals.set("_scenet_kind", kind);
      const raw = await pyodide.runPythonAsync("_scenet_compile(_scenet_source, _scenet_kind)");
      return JSON.parse(String(raw)) as CompileResult;
    },
  };
}
