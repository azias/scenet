/**
 * The zoom and pan arithmetic. The pointer handling around it is thin; this is the part
 * that is easy to get subtly wrong -- a zoom that drifts away from the cursor, a fit that
 * is off-centre by the padding -- and the part that can be tested without a browser.
 */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  MAX_SCALE,
  MIN_SCALE,
  actualSize,
  clampScale,
  fitTransform,
  svgSize,
  wheelFactor,
  zoomAt,
} from "./viewport.ts";

describe("fitTransform", () => {
  test("a wide strip is limited by the width and centred vertically", () => {
    const t = fitTransform({ width: 4000, height: 500 }, { width: 500, height: 400 }, 10);
    assert.equal(t.scale, 480 / 4000);
    assert.equal(t.x, 10);
    assert.equal(t.y, (400 - 500 * t.scale) / 2);
  });

  test("a tall panel is limited by the height and centred horizontally", () => {
    const t = fitTransform({ width: 500, height: 1000 }, { width: 800, height: 520 }, 10);
    assert.equal(t.scale, 0.5);
    assert.equal(t.y, 10);
    assert.equal(t.x, (800 - 250) / 2);
  });

  test("a small panel is enlarged to fill the view", () => {
    // Vector output: there is no resolution to lose, so Fit means fit.
    const t = fitTransform({ width: 100, height: 100 }, { width: 420, height: 420 }, 10);
    assert.equal(t.scale, 4);
  });

  test("a collapsed viewport still produces a usable transform", () => {
    const t = fitTransform({ width: 1000, height: 800 }, { width: 0, height: 0 }, 16);
    assert.ok(t.scale >= MIN_SCALE);
    assert.ok(Number.isFinite(t.x) && Number.isFinite(t.y));
  });
});

describe("zoomAt", () => {
  test("the point under the cursor stays under the cursor", () => {
    const before = { scale: 0.5, x: 30, y: 40 };
    const cursor = { x: 200, y: 150 };
    const after = zoomAt(before, 3, cursor);

    // The content coordinate under the cursor, before and after.
    const contentBefore = { x: (cursor.x - before.x) / before.scale, y: (cursor.y - before.y) / before.scale };
    const contentAfter = { x: (cursor.x - after.x) / after.scale, y: (cursor.y - after.y) / after.scale };
    assert.ok(Math.abs(contentBefore.x - contentAfter.x) < 1e-9);
    assert.ok(Math.abs(contentBefore.y - contentAfter.y) < 1e-9);
    assert.equal(after.scale, 1.5);
  });

  test("zooming stops at the limits without drifting", () => {
    const atMax = { scale: MAX_SCALE, x: 5, y: 7 };
    assert.deepEqual(zoomAt(atMax, 2, { x: 100, y: 100 }), atMax);
    const atMin = { scale: MIN_SCALE, x: 5, y: 7 };
    assert.deepEqual(zoomAt(atMin, 0.5, { x: 100, y: 100 }), atMin);
  });
});

describe("actualSize", () => {
  test("shows the content at 100%, centred", () => {
    const t = actualSize({ width: 200, height: 100 }, { width: 600, height: 300 });
    assert.deepEqual(t, { scale: 1, x: 200, y: 100 });
  });
});

describe("clampScale", () => {
  test("keeps the scale inside the limits", () => {
    assert.equal(clampScale(0), MIN_SCALE);
    assert.equal(clampScale(1e9), MAX_SCALE);
    assert.equal(clampScale(1.25), 1.25);
  });
});

describe("wheelFactor", () => {
  test("scrolling down zooms out and up zooms in, symmetrically", () => {
    const out = wheelFactor(100, 0, false);
    const into = wheelFactor(-100, 0, false);
    assert.ok(out < 1 && into > 1);
    assert.ok(Math.abs(out * into - 1) < 1e-12);
  });

  test("a line-mode wheel moves as far as the same distance in pixels", () => {
    assert.equal(wheelFactor(3, 1, false), wheelFactor(48, 0, false));
  });

  test("a trackpad pinch, which arrives as a ctrl-wheel, is more sensitive", () => {
    assert.ok(wheelFactor(-10, 0, true) > wheelFactor(-10, 0, false));
  });
});

describe("svgSize", () => {
  test("reads the root element's width and height", () => {
    const markup = '<?xml version="1.0"?>\n<svg xmlns="x" width="4435.2" height="593.6" viewBox="0 0 4435.2 593.6"><g width="1"/></svg>';
    assert.deepEqual(svgSize(markup), { width: 4435.2, height: 593.6 });
  });

  test("falls back to the viewBox", () => {
    assert.deepEqual(svgSize('<svg viewBox="0 0 640 480">'), { width: 640, height: 480 });
  });

  test("is undefined for something that is not an SVG", () => {
    assert.equal(svgSize("<p>no</p>"), undefined);
  });
});
