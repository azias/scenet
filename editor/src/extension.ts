/**
 * VS Code support for Scenet documents.
 *
 * Two capabilities, and neither of them is a language server.
 *
 * Completion and validation come from the JSON Schema in `schemas/`, which is
 * *generated from the compiler's own pydantic models* by `scenet schema`. Writing a
 * server by hand would mean maintaining a second description of the language that
 * slowly drifts from the first; deriving it means what the editor suggests is exactly
 * what compiles, by construction.
 *
 * Preview shells out to the same `scenet build` a user would run. Reimplementing the
 * pipeline in TypeScript would fork the compiler, which is the thing this project
 * consistently refuses to do.
 */

import { execFile } from "node:child_process";
import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import * as vscode from "vscode";

const run = promisify(execFile);

/** Documents this extension knows how to compile. */
const SUPPORTED = /\.(panel|scene)\.yaml$|\.script$/;

interface PreviewState {
  readonly panel: vscode.WebviewPanel;
  source: vscode.Uri;
}

let preview: PreviewState | undefined;

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("scenet.preview", () => void showPreview()),
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((document) => {
      const config = vscode.workspace.getConfiguration("scenet");
      if (!config.get<boolean>("previewOnSave", true)) {
        return;
      }
      if (preview !== undefined && document.uri.toString() === preview.source.toString()) {
        void refresh(preview);
      }
    }),
  );
}

export function deactivate(): void {
  preview?.panel.dispose();
  preview = undefined;
}

async function showPreview(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (editor === undefined) {
    void vscode.window.showWarningMessage("Scenet: open a panel document first.");
    return;
  }
  if (!SUPPORTED.test(editor.document.uri.fsPath)) {
    void vscode.window.showWarningMessage(
      "Scenet: expected a *.panel.yaml, *.scene.yaml or *.script document.",
    );
    return;
  }

  if (preview === undefined) {
    const panel = vscode.window.createWebviewPanel(
      "scenet.preview",
      "Scenet preview",
      vscode.ViewColumn.Beside,
      // No scripts: the webview only ever shows inert SVG, so there is no reason to
      // hand it script execution.
      { enableScripts: false, retainContextWhenHidden: true },
    );
    panel.onDidDispose(() => {
      preview = undefined;
    });
    preview = { panel, source: editor.document.uri };
  } else {
    preview.source = editor.document.uri;
    preview.panel.reveal(vscode.ViewColumn.Beside, true);
  }

  await refresh(preview);
}

async function refresh(state: PreviewState): Promise<void> {
  state.panel.title = `Scenet: ${basename(state.source.fsPath)}`;
  try {
    const { panels, notes } = await compile(state.source.fsPath);
    state.panel.webview.html = page(panels, notes);
  } catch (error) {
    state.panel.webview.html = errorPage(
      error instanceof Error ? error.message : String(error),
    );
  }
}

interface Compiled {
  readonly panels: readonly string[];
  readonly notes: readonly string[];
}

/**
 * Compile a document by invoking the CLI, writing output to a scratch directory.
 *
 * The compiler is deterministic, so a temporary directory is discarded after reading
 * rather than cached: recompiling is cheap and stale output would be worse than none.
 */
async function compile(sourcePath: string): Promise<Compiled> {
  const config = vscode.workspace.getConfiguration("scenet");
  const invocation = config.get<string>("executable", "scenet").trim().split(/\s+/);
  const command = invocation[0] ?? "scenet";
  const leadingArgs = invocation.slice(1);

  const scratch = await fs.mkdtemp(join(tmpdir(), "scenet-preview-"));
  try {
    const target = join(scratch, "preview.svg");
    const { stdout } = await run(command, [
      ...leadingArgs,
      "build",
      sourcePath,
      "-o",
      target,
    ]);

    const written = (await fs.readdir(scratch)).filter((name) => name.endsWith(".svg")).sort();
    const panels = await Promise.all(
      written.map((name) => fs.readFile(join(scratch, name), "utf8")),
    );
    const notes = stdout
      .split(/\r?\n/)
      .filter((line) => line.startsWith("note: "))
      .map((line) => line.slice("note: ".length));
    return { panels, notes };
  } finally {
    await fs.rm(scratch, { recursive: true, force: true });
  }
}

function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const STYLE = `
  body { margin: 0; padding: 12px; font-family: var(--vscode-font-family); }
  .notes { margin: 0 0 10px; padding: 8px 10px; border-radius: 6px;
           background: var(--vscode-inputValidation-infoBackground);
           border: 1px solid var(--vscode-inputValidation-infoBorder);
           font-size: 12px; }
  .notes p { margin: 2px 0; }
  figure { margin: 0 0 14px; }
  /* The panel is white whatever the editor theme: it is a drawing, not chrome. */
  svg { max-width: 100%; height: auto; background: #fff; border-radius: 4px; }
  pre { white-space: pre-wrap; color: var(--vscode-errorForeground);
        font-family: var(--vscode-editor-font-family); font-size: 12px; }
`;

function page(panels: readonly string[], notes: readonly string[]): string {
  const noteBlock =
    notes.length === 0
      ? ""
      : `<div class="notes">${notes.map((n) => `<p>${escapeHtml(n)}</p>`).join("")}</div>`;
  // The SVG is inlined rather than linked so the webview needs no local resource
  // roots, and it is emitted by this project's own compiler rather than fetched.
  const figures = panels.map((svg) => `<figure>${svg}</figure>`).join("");
  return `<!doctype html><html><head><meta charset="utf-8"><style>${STYLE}</style></head>
<body>${noteBlock}${figures}</body></html>`;
}

function errorPage(message: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${STYLE}</style></head>
<body><pre>${escapeHtml(message)}</pre></body></html>`;
}
