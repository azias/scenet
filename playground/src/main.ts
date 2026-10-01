/**
 * Playground glue.
 *
 * The moving parts, and this file is the only thing that knows about all of them: a
 * Monaco editor (`./scenet-monaco`), a Pyodide-hosted compiler (`./compiler`), the
 * gallery the build inlined into `examples.json`, a zoomable viewer (`./viewport`),
 * downloads (`./export`), and the draft and share links (`./persist`).
 *
 * No geometry, no layout, no language knowledge beyond telling one document kind from
 * another. Everything else happens in Python.
 */

import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import JsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import YamlWorker from "monaco-yaml/yaml.worker?worker";

import {
  bootCompiler,
  type CompileFailure,
  type CompileResult,
  type CompileSuccess,
  type Compiler,
} from "./compiler";
import { download, sourceFilename, stemFor, svgBlob, svgToPng, textBlob } from "./export";
import {
  browserStore,
  clearDraft,
  decodeSource,
  encodeSource,
  loadDraft,
  loadNumber,
  saveDraft,
  saveNumber,
  shareUrl,
  tokenFromHash,
} from "./persist";
import {
  SCENET_MARKER_OWNER,
  SCENET_THEME_DARK,
  SCENET_THEME_LIGHT,
  SEMANTIC_HIGHLIGHTING,
  detectKind,
  languageFor,
  modelUriFor,
  registerScenetLanguages,
  toMarkers,
  type ScenetDocumentKind,
} from "./scenet-monaco";
import { installSplitter } from "./splitter";
import { Viewport } from "./viewport";
import "./style.css";

/** Long enough not to recompile mid-word, short enough to feel live. */
const COMPILE_DELAY_MS = 300;

const KIND_LABEL: Record<ScenetDocumentKind, string> = {
  panel: "panel",
  scene: "scene",
  script: "comic script",
};

interface Example {
  readonly title: string;
  readonly kind: ScenetDocumentKind;
  readonly file: string;
  readonly source: string;
}

/**
 * Where the text in the editor came from, which decides what the blurb says, what
 * Reset goes back to, and what downloads are called. `index` is a gallery example, or
 * -1 for a restored draft that did not start from one.
 */
type Origin =
  | { readonly from: "example"; readonly index: number }
  | { readonly from: "draft"; readonly index: number }
  | { readonly from: "shared" };

declare global {
  interface Window {
    MonacoEnvironment?: monaco.Environment;
  }
}

window.MonacoEnvironment = {
  getWorker(_workerId: string, label: string): Worker {
    if (label === "yaml") return new YamlWorker();
    if (label === "json") return new JsonWorker();
    return new EditorWorker();
  },
};

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (found === null) {
    throw new Error(`playground markup is missing #${id}`);
  }
  return found as T;
}

const workspace = element<HTMLElement>("workspace");
const editorHost = element<HTMLDivElement>("editor");
const exampleSelect = element<HTMLSelectElement>("examples");
const blurb = element<HTMLSpanElement>("blurb");
const resetButton = element<HTMLButtonElement>("reset");
const shareButton = element<HTMLButtonElement>("share");
const kindLabel = element<HTMLSpanElement>("kind");
const splitter = element<HTMLDivElement>("splitter");
const outputPane = element<HTMLElement>("output-pane");
const output = element<HTMLDivElement>("output");
const stage = element<HTMLDivElement>("stage");
const coreHost = element<HTMLDivElement>("core");
const statusLine = element<HTMLParagraphElement>("status");
const notes = element<HTMLParagraphElement>("notes");
const errorBox = element<HTMLDivElement>("error");
const zoomControls = element<HTMLDivElement>("zoom-controls");
const zoomLevel = element<HTMLButtonElement>("zoom-level");
const downloadMenu = element<HTMLDetailsElement>("download-menu");
const fullscreenButton = element<HTMLButtonElement>("fullscreen");
const tabs = {
  panel: element<HTMLButtonElement>("tab-panel"),
  debug: element<HTMLButtonElement>("tab-debug"),
  core: element<HTMLButtonElement>("tab-core"),
};

type View = keyof typeof tabs;

const store = browserStore();

function prefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function setStatus(message: string, busy = false): void {
  statusLine.textContent = message;
  statusLine.classList.toggle("busy", busy);
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
  const kindOf = (model: monaco.editor.ITextModel): ScenetDocumentKind => {
    for (const [kind, candidate] of models) {
      if (candidate === model) return kind;
    }
    return "panel";
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
    ...SEMANTIC_HIGHLIGHTING,
  });

  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () =>
      monaco.editor.setTheme(prefersDark() ? SCENET_THEME_DARK : SCENET_THEME_LIGHT),
    );

  const viewport = new Viewport(output, stage, (transform) => {
    zoomLevel.textContent = `${Math.round(transform.scale * 100)}%`;
  });

  installSplitter(workspace, splitter, loadNumber(store, "split", 0.5), (ratio) =>
    saveNumber(store, "split", ratio),
  );

  let compiler: Compiler | undefined;
  let lastGood: CompileSuccess | undefined;
  let view: View = "panel";
  let origin: Origin = { from: "example", index: 0 };
  let edited = false;
  // True while this file, not the person typing, is changing the editor's text.
  let loading = false;
  // Each compile takes a ticket; a result is shown only if no later compile started.
  let generation = 0;
  let timer: number | undefined;

  // --- Panel Core, in its own read-only editor --------------------------------------

  const coreModel = monaco.editor.createModel(
    "",
    "json",
    monaco.Uri.parse("inmemory://model/panel.core.json"),
  );
  let coreEditor: monaco.editor.IStandaloneCodeEditor | undefined;

  /** Created on first view: a hidden editor has no size to lay out against. */
  const showCore = (text: string): void => {
    coreEditor ??= monaco.editor.create(coreHost, {
      model: coreModel,
      readOnly: true,
      domReadOnly: true,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      scrollBeyondLastLine: false,
      folding: true,
      showFoldingControls: "always",
      renderLineHighlight: "none",
      padding: { top: 8, bottom: 8 },
    });
    if (coreModel.getValue() === text) return;
    // Keep the scroll position and folds across recompiles, so a section folded open
    // to watch one value stays open while the source is edited.
    const state = coreEditor.saveViewState();
    coreModel.setValue(text);
    if (state !== null) coreEditor.restoreViewState(state);
  };

  // --- Showing results ---------------------------------------------------------------

  /**
   * Show whichever view is selected, from the last successful compile.
   *
   * The SVG goes in with `innerHTML` (inside the viewport). That is safe because the
   * compiler escapes every identifier and every line of dialogue into its attribute or
   * element -- there are regression tests for exactly this, since
   * `xml.sax.saxutils.escape` does not escape quotation marks and an actor id that
   * closed its own attribute used to be a scripting vector.
   */
  const render = (): void => {
    for (const [name, button] of Object.entries(tabs)) {
      button.setAttribute("aria-selected", String(name === view));
    }
    const showingCore = view === "core";
    coreHost.hidden = !showingCore;
    output.hidden = showingCore;
    zoomControls.hidden = showingCore;
    if (lastGood === undefined) return;
    if (showingCore) {
      showCore(lastGood.core);
    } else {
      viewport.show(view === "debug" ? lastGood.debug : lastGood.svg);
    }
  };

  const clearMarkers = (): void => {
    for (const model of models.values()) {
      monaco.editor.setModelMarkers(model, SCENET_MARKER_OWNER, []);
    }
  };

  /** Each finding as a line that jumps the editor to where it is. */
  const showFindings = (failure: CompileFailure): void => {
    errorBox.replaceChildren(
      ...failure.findings.map((finding) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "finding";
        button.title = "Show in the editor";
        const where = document.createElement("span");
        where.className = "where";
        where.textContent = `${finding.line}:${finding.column}`;
        const rule = document.createElement("span");
        rule.className = "rule";
        rule.textContent = finding.rule;
        const message = document.createElement("span");
        message.className = "message";
        message.textContent = finding.message;
        button.append(where, rule, message);
        button.addEventListener("click", () => {
          editor.setPosition({ lineNumber: finding.line, column: finding.column });
          editor.revealLineInCenterIfOutsideViewport(finding.line);
          editor.focus();
        });
        return button;
      }),
    );
    errorBox.hidden = false;
  };

  const showResult = (result: CompileResult, model: monaco.editor.ITextModel): void => {
    clearMarkers();
    if (result.ok) {
      lastGood = result;
      errorBox.hidden = true;
      errorBox.replaceChildren();
      notes.textContent = result.notes.join(" · ");
      notes.hidden = result.notes.length === 0;
      const count = result.panels.length;
      setStatus(count === 1 ? "Compiled." : `Compiled ${count} panels.`);
      updateDownloads();
      render();
      return;
    }
    // The previous panel stays on screen. Blanking it on every keystroke that leaves the
    // source momentarily invalid makes the page flicker while you type.
    monaco.editor.setModelMarkers(model, SCENET_MARKER_OWNER, toMarkers(monaco, result.findings));
    showFindings(result);
    notes.hidden = true;
    const count = result.findings.length;
    setStatus(count === 1 ? "Could not compile: 1 problem." : `Could not compile: ${count} problems.`);
  };

  // --- Compiling ---------------------------------------------------------------------

  /**
   * Put the text in the model whose kind it is.
   *
   * The compiler is told the kind by `detectKind`, but the schema the editor validates
   * against is chosen by the model. Without this, a scene pasted over a panel compiles
   * as a scene and is squiggled as a panel.
   */
  const syncModelKind = (): monaco.editor.ITextModel => {
    const current = editor.getModel() ?? modelFor("panel");
    const detected = detectKind(current.getValue());
    if (detected === kindOf(current)) return current;
    const target = modelFor(detected);
    const state = editor.saveViewState();
    loading = true;
    try {
      target.setValue(current.getValue());
    } finally {
      loading = false;
    }
    monaco.editor.setModelMarkers(current, SCENET_MARKER_OWNER, []);
    editor.setModel(target);
    if (state !== null) editor.restoreViewState(state);
    return target;
  };

  const compileNow = async (): Promise<void> => {
    window.clearTimeout(timer);
    if (compiler === undefined) return; // The boot sequence compiles once it is ready.
    const model = syncModelKind();
    const kind = kindOf(model);
    kindLabel.textContent = KIND_LABEL[kind];
    const ticket = ++generation;
    setStatus("Compiling…", true);
    const result = await compiler.compile(model.getValue(), kind);
    if (ticket !== generation) return;
    showResult(result, model);
  };

  const scheduleCompile = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      saveDraft(store, {
        source: editor.getValue(),
        example: origin.from === "shared" ? -1 : origin.index,
      });
      void compileNow();
    }, COMPILE_DELAY_MS);
  };

  // --- Where the text came from ------------------------------------------------------

  const originExample = (): Example | undefined =>
    origin.from === "shared" ? undefined : examples[origin.index];

  const updateBlurb = (): void => {
    const example = originExample();
    const path = example === undefined ? "" : `examples/gallery/${example.file}`;
    if (origin.from === "shared") {
      blurb.textContent = "Opened from a shared link";
    } else if (origin.from === "draft") {
      blurb.textContent = example ? `Your edit of ${path}, restored` : "Your document, restored";
    } else {
      blurb.textContent = edited ? `${path} · edited` : path;
    }
    resetButton.hidden = origin.from === "example" && !edited;
    resetButton.textContent = example ? "Reset to example" : "Back to the gallery";
  };

  const setSource = (text: string, kind: ScenetDocumentKind = detectKind(text)): void => {
    const model = modelFor(kind);
    loading = true;
    try {
      model.setValue(text);
    } finally {
      loading = false;
    }
    if (editor.getModel() !== model) {
      clearMarkers();
      editor.setModel(model);
    }
    kindLabel.textContent = KIND_LABEL[kind];
    // A different document opens fitted. Only edits to the same one keep the zoom.
    viewport.fit();
  };

  /** A share link in the address bar is only true until the first edit. */
  const dropShareLink = (): void => {
    if (tokenFromHash(location.hash) !== undefined) {
      history.replaceState(null, "", location.pathname + location.search);
    }
  };

  /** Ask before throwing away edits that only exist in this tab. */
  const mayDiscard = (): boolean =>
    !edited || window.confirm("Discard your changes to this document?");

  const loadExample = (index: number): void => {
    const example = examples[index];
    if (example === undefined) return;
    setSource(example.source, example.kind);
    origin = { from: "example", index };
    edited = false;
    exampleSelect.value = String(index);
    clearDraft(store);
    dropShareLink();
    updateBlurb();
    void compileNow();
  };

  const openSharedLink = async (): Promise<boolean> => {
    const token = tokenFromHash(location.hash);
    if (token === undefined) return false;
    try {
      setSource(await decodeSource(token));
    } catch {
      setStatus("That link could not be opened: it is damaged or incomplete.");
      return false;
    }
    origin = { from: "shared" };
    edited = false;
    exampleSelect.selectedIndex = -1;
    updateBlurb();
    void compileNow();
    return true;
  };

  // --- Downloads, sharing, full screen -----------------------------------------------

  const updateDownloads = (): void => {
    for (const button of downloadMenu.querySelectorAll<HTMLButtonElement>("[data-download]")) {
      button.disabled = button.dataset["download"] !== "source" && lastGood === undefined;
    }
  };

  const save = async (what: string): Promise<void> => {
    const stem = stemFor(originExample()?.file);
    if (what === "source") {
      const model = editor.getModel() ?? modelFor("panel");
      download(sourceFilename(stem, kindOf(model)), textBlob(model.getValue()));
      return;
    }
    if (lastGood === undefined) {
      setStatus("Nothing has compiled yet, so there is nothing to download.");
      return;
    }
    if (what === "svg") download(`${stem}.svg`, svgBlob(lastGood.svg));
    if (what === "debug") download(`${stem}.debug.svg`, svgBlob(lastGood.debug));
    if (what === "core") download(`${stem}.core.json`, textBlob(lastGood.core, "application/json"));
    if (what === "png") {
      setStatus("Rendering PNG…", true);
      try {
        download(`${stem}.png`, await svgToPng(lastGood.svg));
        setStatus("PNG saved.");
      } catch (error: unknown) {
        setStatus(`Could not make a PNG: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
  };

  const share = async (): Promise<void> => {
    const url = shareUrl(location.href, await encodeSource(editor.getValue()));
    history.replaceState(null, "", url);
    try {
      await navigator.clipboard.writeText(url);
      setStatus("Link copied. Anyone who opens it sees this document.");
    } catch {
      setStatus("The link is in the address bar, ready to copy.");
    }
  };

  const setMaximized = (on: boolean): void => {
    outputPane.classList.toggle("maximized", on);
    syncFullscreenButton(on);
  };
  const syncFullscreenButton = (on: boolean): void => {
    fullscreenButton.setAttribute("aria-pressed", String(on));
    fullscreenButton.title = on ? "Exit full screen (Esc)" : "Full screen";
  };
  const toggleFullscreen = (): void => {
    if (document.fullscreenElement !== null) {
      void document.exitFullscreen();
    } else if (outputPane.classList.contains("maximized")) {
      setMaximized(false);
    } else if (document.fullscreenEnabled) {
      // Falls back to filling the window where the request is refused, as an iframe
      // without `allowfullscreen` does.
      outputPane.requestFullscreen().catch(() => setMaximized(true));
    } else {
      setMaximized(true);
    }
  };

  // --- Wiring ------------------------------------------------------------------------

  editor.onDidChangeModelContent(() => {
    if (loading) return;
    if (!edited) {
      edited = true;
      updateBlurb();
    }
    dropShareLink();
    scheduleCompile();
  });

  exampleSelect.addEventListener("change", () => {
    if (!mayDiscard()) {
      // Put the selection back to what the editor actually holds.
      if (origin.from === "shared") exampleSelect.selectedIndex = -1;
      else exampleSelect.value = String(origin.index);
      return;
    }
    loadExample(Number(exampleSelect.value));
  });

  resetButton.addEventListener("click", () => {
    if (mayDiscard()) loadExample(origin.from === "shared" ? 0 : Math.max(0, origin.index));
  });

  shareButton.addEventListener("click", () => void share());

  for (const [name, button] of Object.entries(tabs)) {
    button.addEventListener("click", () => {
      view = name as View;
      render();
    });
  }

  element<HTMLButtonElement>("zoom-in").addEventListener("click", () => viewport.zoomIn());
  element<HTMLButtonElement>("zoom-out").addEventListener("click", () => viewport.zoomOut());
  element<HTMLButtonElement>("zoom-fit").addEventListener("click", () => viewport.fit());
  zoomLevel.addEventListener("click", () => viewport.actualSize());

  downloadMenu.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-download]");
    if (button === null) return;
    downloadMenu.open = false;
    void save(button.dataset["download"] ?? "");
  });
  document.addEventListener("click", (event) => {
    if (downloadMenu.open && !downloadMenu.contains(event.target as Node)) {
      downloadMenu.open = false;
    }
  });

  fullscreenButton.addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", () =>
    syncFullscreenButton(document.fullscreenElement === outputPane),
  );

  window.addEventListener(
    "keydown",
    (event) => {
      // Ctrl/Cmd+S saves the source rather than the page, which would save the editor.
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save("source");
      } else if (event.key === "Escape") {
        downloadMenu.open = false;
        if (outputPane.classList.contains("maximized")) setMaximized(false);
      }
    },
    { capture: true },
  );

  // A link pasted into this tab's address bar changes only the fragment.
  window.addEventListener("hashchange", () => {
    if (tokenFromHash(location.hash) !== undefined && mayDiscard()) void openSharedLink();
  });

  // --- Start -------------------------------------------------------------------------
  //
  // The document goes into the editor first; the compiler boots behind it. Booting
  // takes ten to twenty seconds on a first visit, and an empty editor for that long
  // reads as a broken page.

  updateDownloads();
  if (!(await openSharedLink())) {
    const draft = loadDraft(store);
    if (draft !== undefined && draft.source.trim() !== "") {
      setSource(draft.source);
      origin = { from: "draft", index: draft.example };
      edited = true;
      if (examples[draft.example] === undefined) exampleSelect.selectedIndex = -1;
      else exampleSelect.value = String(draft.example);
      updateBlurb();
    } else {
      loadExample(0);
    }
  }
  render();

  setStatus("Starting the compiler…", true);
  try {
    compiler = await bootCompiler((message) => setStatus(message, true));
  } catch (error: unknown) {
    setStatus("Failed to start.");
    errorBox.hidden = false;
    errorBox.textContent = error instanceof Error ? error.message : String(error);
    return;
  }

  document.title = `Scenet ${compiler.version} playground`;
  await compileNow();
}

void main();
