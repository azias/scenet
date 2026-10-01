/**
 * Scenet-aware highlighting on top of YAML's.
 *
 * Monaco's YAML tokenizer colours keys and scalars; it cannot know that `alice` in
 * `alice left_of bob` is the same actor declared under `cast:` and named in `by: alice`.
 * These tests pin the three things this layer adds: actors, staging predicates, and
 * script verbs -- in block and flow style, in panels and in scenes.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { SEMANTIC_TOKEN_TYPES, encodeTokens, scenetTokens, type SemanticToken } from "./semantic.ts";

/** Render tokens as `line:text:type` so a failure reads as the document does. */
function describeTokens(source: string): string[] {
  const lines = source.split("\n");
  return scenetTokens(source).map(
    (token) =>
      `${token.line}:${(lines[token.line] ?? "").slice(token.start, token.start + token.length)}:${SEMANTIC_TOKEN_TYPES[token.type]}`,
  );
}

describe("scenetTokens", () => {
  test("a panel: cast, staging sentences and script verbs", () => {
    const source = [
      "cast:",
      "  alice: {reference: alice, pose: pointing}",
      "  bob:   {reference: bob}",
      "staging:",
      "  - alice left_of bob",
      "  - alice looking_at bob",
      "script:",
      '  - say: {by: alice, text: "You forgot your umbrella!"}',
      "  - caption: {text: Later., kind: locale}",
    ].join("\n");

    assert.deepEqual(describeTokens(source), [
      "1:alice:actor",
      "2:bob:actor",
      "4:alice:actor",
      "4:left_of:relation",
      "4:bob:actor",
      "5:alice:actor",
      "5:looking_at:relation",
      "5:bob:actor",
      "7:say:verb",
      "7:alice:actor",
      "8:caption:verb",
    ]);
  });

  test("a scene, where the same blocks sit one level down", () => {
    const source = [
      "panels:",
      "  one:",
      "    cast:",
      "      alice: {reference: alice}",
      "    staging:",
      "    - alice in_front_of bob",
      "    script:",
      "      - say:",
      "          by: alice",
      "          text: Hi",
    ].join("\n");

    assert.deepEqual(describeTokens(source), [
      "3:alice:actor",
      "5:alice:actor",
      "5:in_front_of:relation",
      "5:bob:actor",
      "7:say:verb",
      "8:alice:actor",
    ]);
  });

  test("flow-style staging", () => {
    assert.deepEqual(describeTokens("staging: [a left_of b, b behind c]"), [
      "0:a:actor",
      "0:left_of:relation",
      "0:b:actor",
      "0:b:actor",
      "0:behind:relation",
      "0:c:actor",
    ]);
  });

  test("keys that merely share a name are left alone", () => {
    const source = ["panel:", "  cast: 3", "camera:", "  shot: close_up", "# alice left_of bob"].join("\n");
    assert.deepEqual(describeTokens(source), []);
  });

  test("a list under some other key is not read as staging", () => {
    assert.deepEqual(describeTokens("notes:\n  - alice left_of bob\n"), []);
  });
});

describe("encodeTokens", () => {
  test("positions are relative to the previous token, as Monaco requires", () => {
    const tokens: SemanticToken[] = [
      { line: 1, start: 4, length: 5, type: 0 },
      { line: 1, start: 10, length: 7, type: 1 },
      { line: 3, start: 2, length: 3, type: 2 },
    ];
    assert.deepEqual(Array.from(encodeTokens(tokens)), [1, 4, 5, 0, 0, 0, 6, 7, 1, 0, 2, 2, 3, 2, 0]);
  });
});
