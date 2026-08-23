/**
 * Monaco language definition for Scenet comic scripts.
 *
 * Comic script is a format writers already use, and its structure is carried entirely
 * by line shape: a heading is a word and a number, a speaker cue is a name in capitals
 * on its own line, a directive starts with `@`, and everything else is prose. A Monarch
 * tokenizer -- which is a state machine over regular expressions, line by line -- fits
 * that exactly, and needs no parser.
 *
 * The one rule worth stating twice, because it is the one that trips people up: a
 * speaker cue is recognised by **the name** being in capitals, not the whole line.
 * `BOB (whisper)` is a cue; the parenthetical is lower case and does not disqualify it.
 * The compiler's own frontend makes the same distinction, and got it wrong first.
 */

import type * as Monaco from "monaco-editor";

export const SCRIPT_LANGUAGE_ID = "scenet-script";

/**
 * Bracket pairs, comment syntax and auto-closing behaviour.
 *
 * Comic script has no comment syntax of its own, so none is declared -- offering one
 * would invite people to write comments the compiler then treats as prose.
 */
export const scriptLanguageConfiguration: Monaco.languages.LanguageConfiguration = {
  brackets: [
    ["(", ")"],
    ["[", "]"],
    ["{", "}"],
  ],
  autoClosingPairs: [
    { open: "(", close: ")" },
    { open: "[", close: "]" },
    { open: "{", close: "}" },
    { open: '"', close: '"' },
  ],
  surroundingPairs: [
    { open: "(", close: ")" },
    { open: '"', close: '"' },
  ],
  wordPattern: /[A-Za-z_][\w-]*/,
};

/**
 * The tokenizer.
 *
 * State machine, three states:
 *
 * - `root` — the body of the script.
 * - `frontMatter` — between the opening `---` and its closing pair, handed to the YAML
 *   tokenizer so the preamble is highlighted as the YAML it is.
 * - `dialogue` — the lines immediately after a speaker cue, so spoken text is visually
 *   distinct from stage prose. Ended by a blank line, which is how the format ends it.
 */
export const scriptMonarchTokens: Monaco.languages.IMonarchLanguage = {
  defaultToken: "",
  tokenPostfix: ".scenet",

  tokenizer: {
    root: [
      // Front matter, but only when it opens the document. A `---` further down is
      // prose -- writers use it as a scene divider.
      [/^---\s*$/, { token: "meta.separator", next: "@frontMatter", nextEmbedded: "yaml" }],

      [/^\s*(PAGE)\s+(.+)$/, ["keyword.page", "string.page"]],
      [/^\s*(PANEL)\s+(\S+)\s*$/, ["keyword.panel", "number.panel"]],

      // A directive: @shot, @angle, or any top-level panel key.
      [/^\s*(@)([A-Za-z_][\w-]*)(\s*:\s*)(.*)$/, ["operator", "attribute.name", "", "attribute.value"]],

      // Speaker cue with a parenthetical: BOB (whisper). Tested before the bare cue so
      // the parenthetical is coloured separately rather than swallowed by the name.
      [
        /^\s*([A-Z][A-Z0-9 _.'-]*[A-Z0-9])(\s*\()([^)]*)(\)\s*)$/,
        ["type.identifier", "delimiter", "annotation", "delimiter", { token: "", next: "@dialogue" }],
      ],
      // Bare speaker cue: ALICE. Requires at least two characters so a stray initial
      // does not turn the following paragraph into dialogue.
      [/^\s*[A-Z][A-Z0-9 _.'-]*[A-Z0-9]\s*$/, { token: "type.identifier", next: "@dialogue" }],

      [/^\s*$/, ""],
      // Everything else is prose. Preserved by the compiler, interpreted by nothing.
      [/.+$/, "comment.prose"],
    ],

    frontMatter: [[/^---\s*$/, { token: "meta.separator", next: "@pop", nextEmbedded: "@pop" }]],

    dialogue: [
      [/^\s*$/, { token: "", next: "@pop" }],
      [/.+$/, "string.dialogue"],
    ],
  },
};

/**
 * Colours for the token classes above.
 *
 * Defined as a theme rather than left to Monaco's defaults because the default palette
 * has no opinion about `comment.prose` or `string.dialogue`, and those two are the ones
 * that matter: a writer scanning a script wants dialogue to stand out from description
 * at a glance.
 */
export const scriptThemeRules: Monaco.editor.ITokenThemeRule[] = [
  { token: "keyword.panel", fontStyle: "bold" },
  { token: "keyword.page", fontStyle: "bold" },
  { token: "type.identifier.scenet", fontStyle: "bold" },
  { token: "annotation.scenet", fontStyle: "italic" },
  { token: "comment.prose.scenet", fontStyle: "italic" },
];
