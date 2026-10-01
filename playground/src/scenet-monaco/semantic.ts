/**
 * Scenet-aware highlighting, layered on Monaco's YAML colouring as semantic tokens.
 *
 * The YAML tokenizer sees keys and scalars. It cannot tell that `alice` under `cast:`,
 * in `alice left_of bob` and in `by: alice` is one actor, or that `left_of` is the
 * word carrying the meaning of that sentence. Those are what a reader scans for, so
 * those are what this colours:
 *
 * - **actors** -- declared under `cast:`, named in staging sentences and in `by:`;
 * - **relations** -- the predicate of a staging sentence;
 * - **verbs** -- the key that tags a script entry, `say:` or `caption:`.
 *
 * A line scanner rather than a YAML parse, because it has to keep up with every
 * keystroke on a half-written document that is usually not valid YAML at all. It tracks
 * the chain of enclosing keys by indentation, which is enough to know whether a line is
 * inside a panel's `cast`, `staging` or `script` block -- at the top of a panel
 * document, or one level down inside a scene's `panels:`. What it cannot place, it
 * leaves alone: the YAML colouring underneath is still correct.
 *
 * No Monaco import: this module is plain text in, numbers out, and is tested under Node.
 */

/** Token type names, in legend order. Theme rules colour them by these names. */
export const SEMANTIC_TOKEN_TYPES = ["actor", "relation", "verb"] as const;

const ACTOR = 0;
const RELATION = 1;
const VERB = 2;

/** One coloured span. Lines and columns are zero-based, as Monaco's encoding wants. */
export interface SemanticToken {
  readonly line: number;
  readonly start: number;
  readonly length: number;
  readonly type: number;
}

type Block = "cast" | "staging" | "script";
const BLOCKS: ReadonlySet<string> = new Set<Block>(["cast", "staging", "script"]);

interface Frame {
  readonly indent: number;
  readonly key: string;
}

/** `key:` at the start of a line, optionally as a list item (`- key:`). */
const KEY = /^(\s*)(-\s+)?([A-Za-z_][\w-]*)\s*:(?=\s|$)/;
/** A list item that is not a mapping: `- whatever`. */
const ITEM = /^(\s*)-\s+(?![\w-]+\s*:(?:\s|$))(.*)$/;
/** A staging sentence, three words. */
const SENTENCE = /^(\S+)(\s+)(\S+)(\s+)(\S+)\s*$/;
/** `by: name` inside a script entry, in either block or flow style. */
const BY = /\bby\s*:\s*([A-Za-z_][\w-]*)/g;

export function scenetTokens(text: string): SemanticToken[] {
  const tokens: SemanticToken[] = [];
  const stack: Frame[] = [];

  text.split("\n").forEach((raw, line) => {
    const content = stripComment(raw);
    if (content.trim() === "") return;

    const key = KEY.exec(content);
    const item = key === null ? ITEM.exec(content) : null;
    const indent = (key ?? item)?.[1]?.length ?? content.search(/\S/);
    const listItem = item !== null || (key !== null && key[2] !== undefined);

    // A list item may sit at the same indentation as the key that owns it, so only
    // deeper frames are closed by one. A plain key closes its siblings too.
    while (stack.length > 0 && (stack.at(-1)?.indent ?? 0) >= indent + (listItem ? 1 : 0)) {
      stack.pop();
    }
    const block = enclosingBlock(stack);
    // `script: [{say: {by: alice}}]` opens the block and fills it on the same line.
    let inScript = block === "script";

    if (key !== null) {
      const name = key[3] ?? "";
      const column = (key[1]?.length ?? 0) + (key[2]?.length ?? 0);
      const opensBlock = isBlockPosition(stack);
      if (block === "cast" && !listItem && stack.at(-1)?.key === "cast") {
        tokens.push({ line, start: column, length: name.length, type: ACTOR });
      }
      if (block === "script" && listItem) {
        tokens.push({ line, start: column, length: name.length, type: VERB });
      }
      if (name === "staging" && opensBlock) {
        stagingFlow(content, column + name.length, line, tokens);
      }
      inScript ||= name === "script" && opensBlock;
      stack.push({ indent: column, key: name });
    } else if (item !== null && block === "staging") {
      const rest = item[2] ?? "";
      sentence(rest, content.length - rest.length, line, tokens);
    }

    if (inScript) {
      for (const match of content.matchAll(BY)) {
        const name = match[1] ?? "";
        const start = (match.index ?? 0) + match[0].length - name.length;
        tokens.push({ line, start, length: name.length, type: ACTOR });
      }
    }
  });

  return tokens.sort((a, b) => a.line - b.line || a.start - b.start);
}

/**
 * Encode tokens as Monaco wants them: five numbers each, positions relative to the
 * previous token -- the line as a delta, and the column as a delta only on the same line.
 */
export function encodeTokens(tokens: readonly SemanticToken[]): Uint32Array {
  const data = new Uint32Array(tokens.length * 5);
  let line = 0;
  let start = 0;
  tokens.forEach((token, index) => {
    const deltaLine = token.line - line;
    const deltaStart = deltaLine === 0 ? token.start - start : token.start;
    data.set([deltaLine, deltaStart, token.length, token.type, 0], index * 5);
    line = token.line;
    start = token.start;
  });
  return data;
}

/**
 * The Scenet block a line is in, if any.
 *
 * A block key counts only where a panel's keys live: at the top of the document, or
 * directly inside one of a scene's `panels:`. Anything else called `cast` -- a panel
 * named `cast`, a key inside `panel:` -- is just a key.
 */
function enclosingBlock(stack: readonly Frame[]): Block | undefined {
  for (let depth = stack.length - 1; depth >= 0; depth -= 1) {
    const frame = stack[depth];
    if (frame !== undefined && BLOCKS.has(frame.key) && isBlockPosition(stack.slice(0, depth))) {
      return frame.key as Block;
    }
  }
  return undefined;
}

function isBlockPosition(ancestors: readonly Frame[]): boolean {
  return ancestors.length === 0 || (ancestors.length === 2 && ancestors[0]?.key === "panels");
}

/** `staging: [a left_of b, c behind d]` -- sentences inside a flow sequence. */
function stagingFlow(content: string, after: number, line: number, tokens: SemanticToken[]): void {
  const open = content.indexOf("[", after);
  const close = content.lastIndexOf("]");
  if (open === -1 || close < open) return;
  let start = open + 1;
  for (const part of content.slice(open + 1, close).split(",")) {
    const leading = part.length - part.trimStart().length;
    sentence(part.trim(), start + leading, line, tokens);
    start += part.length + 1;
  }
}

/** Colour `subject predicate object`, starting at column `at`. */
function sentence(text: string, at: number, line: number, tokens: SemanticToken[]): void {
  const match = SENTENCE.exec(unquote(text));
  if (match === null) return;
  const [, subject = "", gapA = "", predicate = "", gapB = "", object = ""] = match;
  const offset = at + (text.startsWith("'") || text.startsWith('"') ? 1 : 0);
  const predicateAt = offset + subject.length + gapA.length;
  const objectAt = predicateAt + predicate.length + gapB.length;
  tokens.push({ line, start: offset, length: subject.length, type: ACTOR });
  tokens.push({ line, start: predicateAt, length: predicate.length, type: RELATION });
  tokens.push({ line, start: objectAt, length: object.length, type: ACTOR });
}

function unquote(text: string): string {
  const quoted = /^(['"])(.*)\1$/.exec(text);
  return quoted?.[2] ?? text;
}

/** Drop a trailing `# comment`, which YAML only recognises after whitespace. */
function stripComment(line: string): string {
  if (/^\s*#/.test(line)) return "";
  const at = line.search(/\s#/);
  return at === -1 ? line : line.slice(0, at);
}
