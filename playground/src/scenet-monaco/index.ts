/**
 * Scenet language support for the Monaco editor.
 *
 * Self-contained on purpose: nothing in this directory imports from the rest of the
 * playground, and its only inputs are a Monaco instance and two schema URLs. That makes
 * it extractable as an npm package the day somebody wants to embed a Scenet editor in
 * their own page — see README.md in this directory for why that has not happened yet.
 *
 * What you get:
 *
 * - **Panel and scene documents**: completion, hover documentation and inline validation,
 *   driven by JSON Schemas that the compiler generates from its own models. What the
 *   editor suggests therefore cannot drift from what compiles.
 * - **Scenet-aware colouring** of panel and scene documents, on top of YAML's: actors,
 *   staging relations and script verbs, as semantic tokens (`./semantic.ts`).
 * - **Comic scripts**: syntax highlighting via a Monarch tokenizer.
 * - **Compiler findings as markers**: {@link toMarkers} turns the diagnostics `scenet
 *   check` produces into squiggles on the right line, with the rule id as the code.
 *
 * Usage:
 *
 * ```ts
 * import * as monaco from "monaco-editor";
 * import { registerScenetLanguages } from "./scenet-monaco";
 *
 * registerScenetLanguages(monaco, {
 *   panelSchemaUrl: new URL("schemas/panel.schema.json", document.baseURI).href,
 *   sceneSchemaUrl: new URL("schemas/scene.schema.json", document.baseURI).href,
 * });
 * ```
 */

import type * as Monaco from "monaco-editor";
import { configureMonacoYaml } from "monaco-yaml";

import {
  SCRIPT_LANGUAGE_ID,
  scriptLanguageConfiguration,
  scriptMonarchTokens,
  scriptThemeRules,
} from "./script-language";
import { SEMANTIC_TOKEN_TYPES, encodeTokens, scenetTokens } from "./semantic";

export { SCRIPT_LANGUAGE_ID } from "./script-language";

/** Names of the editor themes this module defines. */
export const SCENET_THEME_LIGHT = "scenet-light";
export const SCENET_THEME_DARK = "scenet-dark";

/** Virtual filenames used to associate a model with the right schema. */
export const PANEL_MODEL_URI = "inmemory://model/panel.panel.yaml";
export const SCENE_MODEL_URI = "inmemory://model/scene.scene.yaml";
export const SCRIPT_MODEL_URI = "inmemory://model/script.script";

export interface ScenetLanguageOptions {
  /** Absolute URL of `panel.schema.json`. */
  readonly panelSchemaUrl: string;
  /** Absolute URL of `scene.schema.json`. */
  readonly sceneSchemaUrl: string;
}

/**
 * Register everything Scenet needs on a Monaco instance.
 *
 * Safe to call once per page. Calling it twice would register the language twice, which
 * Monaco tolerates but which serves no purpose.
 */
export function registerScenetLanguages(
  monaco: typeof Monaco,
  options: ScenetLanguageOptions,
): void {
  monaco.languages.register({
    id: SCRIPT_LANGUAGE_ID,
    extensions: [".script"],
    aliases: ["Scenet comic script", "scenet-script"],
  });
  monaco.languages.setLanguageConfiguration(SCRIPT_LANGUAGE_ID, scriptLanguageConfiguration);
  monaco.languages.setMonarchTokensProvider(SCRIPT_LANGUAGE_ID, scriptMonarchTokens);

  monaco.editor.defineTheme(SCENET_THEME_LIGHT, {
    base: "vs",
    inherit: true,
    rules: [...scriptThemeRules, ...documentThemeRules(false)],
    colors: {},
  });
  monaco.editor.defineTheme(SCENET_THEME_DARK, {
    base: "vs-dark",
    inherit: true,
    rules: [...scriptThemeRules, ...documentThemeRules(true)],
    colors: {},
  });

  // Only on Scenet documents: a page embedding this next to some other YAML should not
  // find actors highlighted in its CI config.
  monaco.languages.registerDocumentSemanticTokensProvider("yaml", {
    getLegend: () => ({ tokenTypes: [...SEMANTIC_TOKEN_TYPES], tokenModifiers: [] }),
    provideDocumentSemanticTokens: (model) =>
      isScenetDocument(model.uri.path)
        ? { data: encodeTokens(scenetTokens(model.getValue())) }
        : null,
    releaseDocumentSemanticTokens: () => undefined,
  });

  configureMonacoYaml(monaco, {
    enableSchemaRequest: true,
    validate: true,
    hover: true,
    completion: true,
    // An object rather than `true`: this option is FormatterOptions, and `enable`
    // defaults to true within it.
    format: { enable: true, printWidth: 96, singleQuote: false },
    schemas: [
      // `fileMatch` is matched against the model's URI, which is why the models this
      // module documents are named `*.panel.yaml` and `*.scene.yaml` even though they
      // only ever live in memory.
      { uri: options.panelSchemaUrl, fileMatch: ["*.panel.yaml"] },
      { uri: options.sceneSchemaUrl, fileMatch: ["*.scene.yaml"] },
    ],
  });
}

/**
 * Editor option that turns the semantic colouring on. Standalone Monaco leaves it to the
 * theme, and its themes cannot opt in, so it has to be asked for per editor.
 */
export const SEMANTIC_HIGHLIGHTING = { "semanticHighlighting.enabled": true } as const;

/**
 * Colours for YAML and for the semantic tokens.
 *
 * Monaco's own YAML palette is pale enough that the editor reads as plain text at a
 * glance. Keys are made distinct from values, and the three Scenet token types get
 * colours of their own -- the same hue in both themes, adjusted for the background.
 */
function documentThemeRules(dark: boolean): Monaco.editor.ITokenThemeRule[] {
  const palette = dark
    ? {
        key: "9cdcfe",
        value: "ce9178",
        number: "b5cea8",
        comment: "6a9955",
        actor: "c792ea",
        relation: "f0b45a",
        verb: "4fc1d6",
      }
    : {
        key: "0b4f8a",
        value: "a3410f",
        number: "0b7a4b",
        comment: "6a737d",
        actor: "7b2fbf",
        relation: "b45309",
        verb: "0e7490",
      };
  return [
    { token: "type.yaml", foreground: palette.key },
    { token: "string.yaml", foreground: palette.value },
    { token: "number.yaml", foreground: palette.number },
    { token: "keyword.yaml", foreground: palette.number },
    { token: "comment.yaml", foreground: palette.comment, fontStyle: "italic" },
    { token: "actor", foreground: palette.actor, fontStyle: "bold" },
    { token: "relation", foreground: palette.relation, fontStyle: "italic" },
    { token: "verb", foreground: palette.verb, fontStyle: "bold" },
  ];
}

function isScenetDocument(path: string): boolean {
  return path.endsWith(".panel.yaml") || path.endsWith(".scene.yaml");
}

/**
 * One finding from the compiler's checker, as `scenet.diagnostics` reports it.
 *
 * Lines and columns are one-based and the end column is exclusive -- SARIF's convention,
 * which is also Monaco's, so they need no adjustment.
 */
export interface ScenetFinding {
  readonly rule: string;
  readonly message: string;
  readonly line: number;
  readonly column: number;
  readonly endLine: number;
  readonly endColumn: number;
}

/** Owner name for markers set from compiler findings, distinct from the schema's. */
export const SCENET_MARKER_OWNER = "scenet";

/** Turn compiler findings into editor markers. */
export function toMarkers(
  monaco: typeof Monaco,
  findings: readonly ScenetFinding[],
): Monaco.editor.IMarkerData[] {
  return findings.map((finding) => {
    const sameLine = finding.endLine <= finding.line;
    return {
      severity: monaco.MarkerSeverity.Error,
      message: finding.message,
      code: finding.rule,
      source: "scenet",
      startLineNumber: finding.line,
      startColumn: finding.column,
      endLineNumber: Math.max(finding.line, finding.endLine),
      // A zero-width marker is invisible; one character at least.
      endColumn: sameLine ? Math.max(finding.endColumn, finding.column + 1) : finding.endColumn,
    };
  });
}

/** Which of the three document kinds a source string is. */
export type ScenetDocumentKind = "panel" | "scene" | "script";

/**
 * Guess a document's kind from its text.
 *
 * The compiler dispatches on the file extension, which a browser editor does not have.
 * Two cheap signals stand in: a `panels:` key at the left margin means a scene, and a
 * `PANEL` heading means a comic script. Anything else is a single panel, which is also
 * the right answer for an empty buffer.
 */
export function detectKind(source: string): ScenetDocumentKind {
  if (/^\s*PANEL\s+\S+\s*$/m.test(source) || /^---\s*$/m.test(source.split("\n")[0] ?? "")) {
    return "script";
  }
  if (/^panels\s*:/m.test(source)) {
    return "scene";
  }
  return "panel";
}

/** The model URI to use for a document of the given kind. */
export function modelUriFor(kind: ScenetDocumentKind): string {
  if (kind === "scene") return SCENE_MODEL_URI;
  if (kind === "script") return SCRIPT_MODEL_URI;
  return PANEL_MODEL_URI;
}

/** The Monaco language id for a document of the given kind. */
export function languageFor(kind: ScenetDocumentKind): string {
  return kind === "script" ? SCRIPT_LANGUAGE_ID : "yaml";
}
