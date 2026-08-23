/**
 * Playground glue: boot Pyodide, install Scenet, compile on edit.
 *
 * There is deliberately no compiler here. The obvious way to build a browser
 * playground for a DSL is to reimplement the compiler in TypeScript, which forks the
 * geometry into two codebases that drift apart. Pyodide ships shapely, geos, numpy,
 * pydantic and kiwisolver, so the actual Python compiler runs unmodified under
 * WebAssembly and this file only moves strings around.
 */

/** The slice of Pyodide's surface this page uses. */
interface PyodideInterface {
  runPythonAsync(code: string): Promise<unknown>;
  loadPackage(names: string[]): Promise<void>;
  globals: { set(name: string, value: unknown): void };
}

declare function loadPyodide(options?: { indexURL?: string }): Promise<PyodideInterface>;

interface Example {
  readonly name: string;
  readonly source: string;
}

/** Debounce delay. Long enough to avoid recompiling mid-word, short enough to feel live. */
const COMPILE_DELAY_MS = 260;

const EXAMPLES: readonly Example[] = [
  {
    name: "Two characters",
    source: `panel:
  size: [1000, 800]

camera:
  shot: medium_shot

cast:
  alice: {reference: alice, pose: pointing,     at: left_third}
  bob:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}

staging:
  - alice left_of bob
  - alice looking_at bob
  - alice ground_shared_with bob

script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know."}
`,
  },
  {
    name: "One figure, thinking",
    source: `panel:
  size: [800, 800]

camera:
  shot: medium_close_up
  angle: low

cast:
  bob: {reference: bob, pose: hands_on_hips, at: center}

script:
  - say: {by: bob, text: "She is going to be furious about this.", kind: thought}
`,
  },
  {
    name: "Whisper and shout",
    source: `panel:
  size: [1200, 700]

camera:
  shot: medium_full

cast:
  alice: {reference: alice, pose: pointing,     at: left_third}
  bob:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}

staging:
  - alice left_of bob
  - alice looking_at bob
  - alice ground_shared_with bob

script:
  - say: {by: alice, text: "Did you take the last one?", kind: whisper}
  - say: {by: bob,   text: "I did not!", kind: shout}
`,
  },
  {
    name: "A crowd (camera retreats)",
    source: `# Four characters at a close-up cannot fit side by side, so the camera pulls
# back -- and says so. The requested shot is an upper bound on tightness.

panel:
  size: [1400, 700]

camera:
  shot: close_up

cast:
  alice: {reference: alice}
  bob:   {reference: bob,   pose: arms_crossed}
  carol: {reference: alice, pose: hands_on_hips}
  dave:  {reference: bob,   pose: pointing}

staging:
  - alice ground_shared_with bob
  - bob ground_shared_with carol
  - carol ground_shared_with dave

script:
  - say: {by: alice, text: "Is everyone here?"}
  - say: {by: dave,  text: "Looks like it."}
`,
  },
];

/**
 * Compile a source string and hand back SVG plus any diagnostics.
 *
 * Errors are caught on the Python side and returned as data. Letting them propagate as
 * exceptions across the WASM boundary loses the carefully written message, which for a
 * language playground is most of the value.
 */
const COMPILE_PY = `
import json

def _scenet_compile(source):
    try:
        from scenet.emit.svg import render
        from scenet.pipeline import compile_source

        result = compile_source(source)
        return json.dumps({
            "ok": True,
            "svg": render(result.core),
            "notes": list(result.notes),
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
`;

interface CompileOk {
  readonly ok: true;
  readonly svg: string;
  readonly notes: readonly string[];
}
interface CompileFailed {
  readonly ok: false;
  readonly error: string;
}
type CompileResult = CompileOk | CompileFailed;

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (found === null) {
    throw new Error(`playground markup is missing #${id}`);
  }
  return found as T;
}

const sourceInput = element<HTMLTextAreaElement>("source");
const exampleSelect = element<HTMLSelectElement>("examples");
const output = element<HTMLDivElement>("output");
// Not `status`: that is a global DOM property (window.status, a string), and a
// module-scope const of the same name collides with it.
const statusLine = element<HTMLParagraphElement>("status");
const notes = element<HTMLSpanElement>("notes");
const errorBox = element<HTMLPreElement>("error");

function setStatus(message: string, busy = false): void {
  statusLine.textContent = message;
  statusLine.classList.toggle("busy", busy);
}

function showResult(result: CompileResult): void {
  if (result.ok) {
    output.innerHTML = result.svg;
    errorBox.hidden = true;
    notes.textContent = result.notes.join(" · ");
    setStatus("Compiled.");
    return;
  }
  // The previous panel stays on screen. Blanking it on every keystroke that leaves
  // the source momentarily invalid makes the page flicker while you type.
  errorBox.hidden = false;
  errorBox.textContent = result.error;
  notes.textContent = "";
  setStatus("Could not compile.");
}

async function boot(): Promise<void> {
  setStatus("Starting Python…", true);
  const pyodide = await loadPyodide();

  setStatus("Installing dependencies…", true);
  // These are built for Pyodide and come from its own distribution.
  await pyodide.loadPackage(["micropip", "numpy", "pydantic", "kiwisolver", "shapely"]);

  setStatus("Installing Scenet…", true);
  // The build writes the wheel's filename here, so a version bump cannot leave the
  // page pointing at a wheel that no longer exists.
  const manifestResponse = await fetch("./wheel.json");
  if (!manifestResponse.ok) {
    throw new Error("wheel.json is missing; run `npm run build` in playground/");
  }
  const manifest = (await manifestResponse.json()) as { wheel: string };

  pyodide.globals.set("_scenet_wheel", `./${manifest.wheel}`);
  await pyodide.runPythonAsync(`
import micropip
# Pure-Python wheels, fetched from PyPI. The font is a dependency rather than a
# system lookup because determinism requires a fixed one.
await micropip.install(["fonttools", "pyyaml", "fonts", "font-source-sans-pro"])
await micropip.install(_scenet_wheel)
`);

  await pyodide.runPythonAsync(COMPILE_PY);

  const runCompile = async (): Promise<void> => {
    setStatus("Compiling…", true);
    // Passed through globals rather than interpolated into the Python source: panel
    // text is arbitrary and would otherwise need escaping, which is a bug waiting to
    // happen the first time somebody writes a quote in a line of dialogue.
    pyodide.globals.set("_scenet_source", sourceInput.value);
    const raw = await pyodide.runPythonAsync("_scenet_compile(_scenet_source)");
    showResult(JSON.parse(String(raw)) as CompileResult);
  };

  let timer: number | undefined;
  const scheduleCompile = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void runCompile(), COMPILE_DELAY_MS);
  };

  EXAMPLES.forEach((example, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = example.name;
    exampleSelect.append(option);
  });

  exampleSelect.addEventListener("change", () => {
    const example = EXAMPLES[Number(exampleSelect.value)];
    if (example !== undefined) {
      sourceInput.value = example.source;
      void runCompile();
    }
  });

  sourceInput.addEventListener("input", scheduleCompile);

  sourceInput.value = EXAMPLES[0]?.source ?? "";
  await runCompile();
}

boot().catch((error: unknown) => {
  setStatus("Failed to start.");
  errorBox.hidden = false;
  errorBox.textContent = error instanceof Error ? error.message : String(error);
});
