import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_RATIO, MIN_RATIO, clampRatio } from "./splitter.ts";

test("the split never squeezes either pane out of existence", () => {
  assert.equal(clampRatio(0), MIN_RATIO);
  assert.equal(clampRatio(1), MAX_RATIO);
  assert.equal(clampRatio(0.37), 0.37);
  assert.equal(clampRatio(Number.NaN), 0.5);
});
