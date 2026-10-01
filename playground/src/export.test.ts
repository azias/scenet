/**
 * Download naming and PNG sizing. The browser does the actual rasterising; what is
 * tested here is the arithmetic that keeps a wide strip inside the limits browsers put
 * on a canvas, and the filenames, which follow the command line's conventions.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { MAX_CANVAS_AREA, MAX_CANVAS_SIDE, pngScale, sourceFilename, stemFor } from "./export.ts";

describe("pngScale", () => {
  test("an ordinary panel gets the requested scale", () => {
    assert.equal(pngScale({ width: 1000, height: 800 }, 2), 2);
  });

  test("a wide strip is held to the longest side a canvas allows", () => {
    const scale = pngScale({ width: 4435.2, height: 593.6 }, 2);
    assert.ok(scale < 2);
    assert.ok(4435.2 * scale <= MAX_CANVAS_SIDE);
  });

  test("a large square is held to the canvas area limit", () => {
    const scale = pngScale({ width: 6000, height: 6000 }, 2);
    assert.ok(6000 * scale * 6000 * scale <= MAX_CANVAS_AREA);
  });
});

describe("filenames", () => {
  test("the stem drops the document-kind suffix, as `scenet build` does", () => {
    assert.equal(stemFor("01-two-characters.panel.yaml"), "01-two-characters");
    assert.equal(stemFor("02-shot-ladder.scene.yaml"), "02-shot-ladder");
    assert.equal(stemFor("13-comic-script.script"), "13-comic-script");
    assert.equal(stemFor(undefined), "scenet");
  });

  test("the source keeps the extension the compiler dispatches on", () => {
    assert.equal(sourceFilename("x", "panel"), "x.panel.yaml");
    assert.equal(sourceFilename("x", "scene"), "x.scene.yaml");
    assert.equal(sourceFilename("x", "script"), "x.script");
  });
});
