/**
 * The freshness guard, and the bytecode that used to fool it.
 *
 * These run on Node's built-in test runner through `tsx`, both of which are already
 * here -- no new dependency for the repository's first TypeScript tests.
 */

import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";

import { IGNORED_DIRECTORIES, newestSource, stalenessReason } from "./wheel-freshness.ts";

/** Seconds since the epoch, for `utimes`, which takes seconds rather than milliseconds. */
const AT = {
  old: 1_700_000_000,
  wheel: 1_700_000_100,
  recent: 1_700_000_200,
} as const;

let root: string;
let src: string;

/** Write a file and stamp it, so a test states the ordering it depends on. */
async function writeAt(path: string, when: number): Promise<void> {
  await writeFile(path, "x", "utf-8");
  await utimes(path, when, when);
}

before(async () => {
  root = await mkdtemp(join(tmpdir(), "scenet-freshness-"));
  src = join(root, "src", "scenet");
  await mkdir(join(src, "solve", "__pycache__"), { recursive: true });
});

after(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("newestSource", () => {
  test("ignores bytecode written after the wheel was built", async () => {
    // Exactly the shape of issue #14: the Pages workflow built the wheel, then Sphinx
    // autodoc imported `scenet` and the interpreter wrote fresh `.pyc` files. The guard
    // compared the wheel against its own doc build and refused to deploy for days.
    await writeAt(join(src, "solve", "camera.py"), AT.old);
    await writeAt(join(src, "solve", "__pycache__", "camera.cpython-314.pyc"), AT.recent);

    const newest = await newestSource(src);

    assert.ok(newest, "the walk should have found camera.py");
    assert.match(newest.path, /camera\.py$/);
    assert.equal(newest.mtimeMs, AT.old * 1000);
  });

  test("still notices a genuinely edited source file", async () => {
    // The guard has to keep working. A stale playground is a nasty failure precisely
    // because everything looks correct, which is why this check exists at all.
    const edited = join(src, "solve", "balloons.py");
    await writeAt(edited, AT.recent);

    const newest = await newestSource(src);

    assert.ok(newest);
    assert.match(newest.path, /balloons\.py$/);

    await rm(edited);
  });

  test("returns null for a tree with no source in it", async () => {
    // Distinct from "everything is ancient". Returning 0 here would quietly pass the
    // freshness check rather than reporting that the walk found nothing to compare.
    const empty = join(root, "empty");
    await mkdir(join(empty, "__pycache__"), { recursive: true });
    await writeAt(join(empty, "__pycache__", "stray.pyc"), AT.recent);

    assert.equal(await newestSource(empty), null);
  });

  test("__pycache__ is ignored by name, at any depth", () => {
    assert.ok(IGNORED_DIRECTORIES.has("__pycache__"));
  });
});

describe("stalenessReason", () => {
  test("passes a wheel newer than every source file", async () => {
    assert.equal(await stalenessReason("scenet-0.2.0-py3-none-any.whl", AT.wheel * 1000, src), null);
  });

  test("passes when only bytecode is newer than the wheel", async () => {
    // The regression. Before the fix this returned a message and the deploy failed.
    const reason = await stalenessReason("scenet-0.2.0-py3-none-any.whl", AT.wheel * 1000, src);

    assert.equal(reason, null, `bytecode should not make a wheel stale, got: ${reason}`);
  });

  test("names the file responsible, not just the directory", async () => {
    // "older than src/" is what made #14 expensive: it pointed at a directory of four
    // hundred files and the culprit was one nobody thinks about.
    const edited = join(src, "solve", "staging.py");
    await writeAt(edited, AT.recent);

    const reason = await stalenessReason("scenet-0.2.0-py3-none-any.whl", AT.wheel * 1000, src);

    assert.ok(reason, "an edited source file must still trip the guard");
    assert.match(reason, /staging\.py/);
    assert.match(reason, /uv build --wheel/);

    await rm(edited);
  });
});
