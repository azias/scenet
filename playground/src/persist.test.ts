/**
 * Share links and the autosaved draft.
 *
 * A share link is the whole document, compressed into the URL fragment -- so it never
 * reaches a server, and it is exactly what the sender saw. The codec is the part that can
 * silently corrupt someone's work, so it is tested on the characters most likely to break
 * it: quotation marks in dialogue, non-ASCII names, and long input.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  MAX_SOURCE_BYTES,
  decodeSource,
  encodeSource,
  loadDraft,
  loadNumber,
  saveDraft,
  saveNumber,
  shareUrl,
  tokenFromHash,
  type KeyValueStore,
} from "./persist.ts";

class MemoryStore implements KeyValueStore {
  readonly #items = new Map<string, string>();
  getItem(key: string): string | null {
    return this.#items.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.#items.set(key, value);
  }
  removeItem(key: string): void {
    this.#items.delete(key);
  }
}

/** Storage that refuses everything, as a private window or a blocked origin does. */
const BROKEN: KeyValueStore = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceededError");
  },
  removeItem: () => {
    throw new Error("SecurityError");
  },
};

describe("encodeSource and decodeSource", () => {
  const SAMPLES = [
    "",
    "panel:\n  size: [1000, 800]\n",
    'script:\n  - say: {by: alice, text: "She said \\"no\\" — twice."}\n',
    "cast:\n  zoë: {reference: alice}\n  名前: {reference: bob}\n",
    "staging:\n" + "  - alice left_of bob\n".repeat(2000),
  ];

  for (const source of SAMPLES) {
    test(`round-trips ${JSON.stringify(source.slice(0, 24))}…`, async () => {
      assert.equal(await decodeSource(await encodeSource(source)), source);
    });
  }

  test("the token is safe in a URL fragment without escaping", async () => {
    const token = await encodeSource(SAMPLES[3] ?? "");
    assert.match(token, /^[A-Za-z0-9_-]*$/);
  });

  test("compression makes a repetitive document much shorter", async () => {
    const source = SAMPLES[4] ?? "";
    assert.ok((await encodeSource(source)).length < source.length / 10);
  });

  test("a mangled token is rejected rather than decoded into garbage", async () => {
    await assert.rejects(decodeSource("not*base64"));
    await assert.rejects(decodeSource("AAAA"));
  });

  test("a token that inflates past the limit is rejected", async () => {
    // A link is untrusted input; a few hundred bytes must not become gigabytes.
    const bomb = await encodeSource("x".repeat(MAX_SOURCE_BYTES + 1));
    await assert.rejects(decodeSource(bomb), /too large/);
  });
});

describe("tokenFromHash and shareUrl", () => {
  test("a share URL carries the token in the fragment and reads back", () => {
    const url = shareUrl("https://example.test/scenet/playground/?x=1#old", "abc_-1");
    assert.equal(url, "https://example.test/scenet/playground/?x=1#src=abc_-1");
    assert.equal(tokenFromHash(new URL(url).hash), "abc_-1");
  });

  test("a fragment without a source is ignored", () => {
    assert.equal(tokenFromHash(""), undefined);
    assert.equal(tokenFromHash("#"), undefined);
    assert.equal(tokenFromHash("#section-2"), undefined);
    assert.equal(tokenFromHash("#src="), undefined);
  });
});

describe("drafts", () => {
  test("a saved draft loads back", () => {
    const store = new MemoryStore();
    saveDraft(store, { source: "panel: {}\n", example: 3 });
    assert.deepEqual(loadDraft(store), { source: "panel: {}\n", example: 3 });
  });

  test("nothing saved means no draft", () => {
    assert.equal(loadDraft(new MemoryStore()), undefined);
  });

  test("a corrupted entry is ignored rather than trusted", () => {
    const store = new MemoryStore();
    store.setItem("scenet.playground.draft", "{not json");
    assert.equal(loadDraft(store), undefined);
    store.setItem("scenet.playground.draft", JSON.stringify({ source: 42, example: "x" }));
    assert.equal(loadDraft(store), undefined);
  });

  test("storage that throws never breaks the page", () => {
    assert.equal(loadDraft(BROKEN), undefined);
    assert.doesNotThrow(() => saveDraft(BROKEN, { source: "", example: 0 }));
    assert.equal(loadDraft(undefined), undefined);
  });
});

describe("numbers", () => {
  test("a saved number loads back, and anything else gives the fallback", () => {
    const store = new MemoryStore();
    saveNumber(store, "split", 0.4);
    assert.equal(loadNumber(store, "split", 0.5), 0.4);
    assert.equal(loadNumber(store, "missing", 0.5), 0.5);
    store.setItem("scenet.playground.bad", "NaN");
    assert.equal(loadNumber(store, "bad", 0.5), 0.5);
    assert.equal(loadNumber(BROKEN, "split", 0.5), 0.5);
  });
});
