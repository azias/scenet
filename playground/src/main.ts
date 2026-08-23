/**
 * Playground glue.
 *
 * Three moving parts, and this file is the only thing that knows about all three:
 * a Monaco editor (`./scenet-monaco`), a Pyodide-hosted compiler (`./compiler`), and
 * the gallery of examples the build inlined into `examples.json`.
 *
 * No geometry, no layout, no language knowledge beyond telling one document kind from
 * another. Everything else happens in Python.
 */

import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import YamlWorker from "monaco-yaml/yaml.worker?worker";

import { bootCompiler, type CompileResult, type Compiler } from "./compiler";
import {
  SCENET_THEME_DARK,
  SCENET_THEME_LIGHT,
  detectKind,
  languageFor,
  modelUriFor,
  registerScenetLanguages,
  type ScenetDocumentKind,
} from "./scenet-monaco";
import "./style.css";

/** Long enough not to recompile mid-word, short enough to feel live. */
const COMPILE_DELAY_MS = 300;

interface Example {
  readonly title: string;
  readonly kind: ScenetDocumentKind;
  readonly file: string;
  readonly source: string;
}

declare global {
  interface Window {
    MonacoEnvironment?: monaco.Environment;
  }
}

window.MonacoEnvironment = {
  getWorker(_workerId: string, label: string): Worker {
    return label === "yaml" ? new YamlWorker() : new EditorWorker();
  },
};

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (found === null) {
    throw new Error(`playground markup is missing #${id}`);
  }
  return found as T;
}

const editorHost = element<HTMLDivElement>("editor");
const exampleSelect = element<HTMLSelectElement>("examples");
const blurb = element<HTMLParagraphElement>("blurb");
const kindLabel = element<HTMLSpanElement>("kind");
const output = element<HTMLDivElement>("output");
const coreView = element<HTMLPreElement>("core");
const statusLine = element<HTMLParagraphElement>("status");
const notes = element<HTMLSpanElement>("notes");
const errorBox = element<HTMLPreElement>("error");
const tabs = {
  panel: element<HTMLButtonElement>("tab-panel"),
  debug: element<HTMLButtonElement>("tab-debug"),
  core: element<HTMLButtonElement>("tab-core"),
};

type View = keyof typeof tabs;
let view: View = "panel";
let latest: CompileResult | undefined;

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function setStatus(message: string, busy = false): void {
  statusLine.textContent = message;
  statusLine.classList.toggle("busy", busy);
}

/**
 * Show whichever view is selected.
 *
 * The SVG goes in with `innerHTML`. That is safe because the compiler escapes every
 * identifier and every line of dialogue into its attribute or element -- there are
 * regression tests for exactly this, since `xml.sax.saxutils.escape` does not escape
 * quotation marks and an actor id that closed its own attribute used to be a scripting
 * vector.
 */
function render(): void {
  if (latest === undefined || !latest.ok) return;

  const showingCore = view === "core";
  coreView.hidden = !showingCore;
  output.hidden = showingCore;

  if (showingCore) {
    coreView.textContent = latest.core;
  } else {
    output.innerHTML = view === "debug" ? latest.debug : latest.svg;
  }

  for (const [name, button] of Object.entries(tabs)) {
    button.setAttribute("aria-selected", String(name === view));
  }
}

function showResult(result: CompileResult): void {
  latest = result;
  if (result.ok) {
    errorBox.hidden = true;
    notes.textContent = result.notes.join(" · ");
    notes.classList.toggle("has-notes", result.notes.length > 0);
    const count = result.panels.length;
    setStatus(count === 1 ? "Compiled." : `Compiled ${count} panels.`);
    render();
    return;
  }
  // The previous panel stays on screen. Blanking it on every keystroke that leaves the
  // source momentarily invalid makes the page flicker while you type.
  errorBox.hidden = false;
  errorBox.textContent = result.error;
  notes.textContent = "";
  notes.classList.remove("has-notes");
  setStatus("Could not compile.");
}

async function main(): Promise<void> {
  const schemaBase = (name: string): string =>
    new URL(`schemas/${name}`, document.baseURI).href;

  registerScenetLanguages(monaco, {
    panelSchemaUrl: schemaBase("panel.schema.json"),
    sceneSchemaUrl: schemaBase("scene.schema.json"),
  });

  const examples = (await (await fetch(new URL("examples.json", document.baseURI))).json()) as
    readonly Example[];

  examples.forEach((example, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = example.title;
    exampleSelect.append(option);
  });

  // One model per document kind, because monaco-yaml associates a schema by matching
  // the model's URI against a filename pattern. Reusing one model would mean a scene
  // document being validated against the panel schema.
  const models = new Map<ScenetDocumentKind, monaco.editor.ITextModel>();
  const modelFor = (kind: ScenetDocumentKind): monaco.editor.ITextModel => {
    const existing = models.get(kind);
    if (existing !== undefined) return existing;
    const created = monaco.editor.createModel(
      "",
      languageFor(kind),
      monaco.Uri.parse(modelUriFor(kind)),
    );
    models.set(kind, created);
    return created;
  };

  const editor = monaco.editor.create(editorHost, {
    model: modelFor("panel"),
    theme: prefersDark() ? SCENET_THEME_DARK : SCENET_THEME_LIGHT,
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 14,
    lineNumbers: "on",
    scrollBeyondLastLine: false,
    renderWhitespace: "none",
    tabSize: 2,
    wordWrap: "on",
    padding: { top: 12, bottom: 12 },
  });

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () =>
      monaco.editor.setTheme(prefersDark() ? SCENET_THEME_DARK : SCENET_THEME_LIGHT),
    );

  setStatus("Starting the compiler…", true);
  let compiler: Compiler;
  try {
    compiler = await bootCompiler((message) => setStatus(message, true));
  } catch (error: unknown) {
    setStatus("Failed to start.");
    errorBox.hidden = false;
    errorBox.textContent = error instanceof Error ? error.message : String(error);
    return;
  }

  const runCompile = async (): Promise<void> => {
    const source = editor.getValue();
    const kind = detectKind(source);
    kindLabel.textContent = { panel: "panel", scene: "scene", script: "comic script" }[kind];
    setStatus("Compiling…", true);
    showResult(await compiler.compile(source, kind));
  };

  let timer: number | undefined;
  const scheduleCompile = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void runCompile(), COMPILE_DELAY_MS);
  };

  const loadExample = (index: number): void => {
    const example = examples[index];
    if (example === undefined) return;
    const model = modelFor(example.kind);
    model.setValue(example.source);
    editor.setModel(model);
    blurb.textContent = `examples/gallery/${example.file}`;
    void runCompile();
  };

  exampleSelect.addEventListener("change", () => loadExample(Number(exampleSelect.value)));
  editor.onDidChangeModelContent(scheduleCompile);

  for (const [name, button] of Object.entries(tabs)) {
    button.addEventListener("click", () => {
      view = name as View;
      render();
    });
  }

  document.title = `Scenet ${compiler.version} playground`;
  loadExample(0);
}

void main();
