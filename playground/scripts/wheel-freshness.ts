/**
 * Is the built wheel older than the source it was built from?
 *
 * `npm run assets` copies whatever is in `../dist`. If you edit the compiler and forget
 * `uv build`, the playground silently serves the previous version -- and since it still
 * works, nothing looks wrong. That happened, and the hour it cost was spent looking at
 * caches and deployments rather than at the obvious.
 *
 * The check lives here rather than inline in `fetch-assets.ts` because it got the answer
 * wrong for several days and nothing could catch it: comparing the wheel against *every*
 * file under `src/` meant comparing it against `__pycache__`, which Python writes as a
 * side effect of importing. In CI the Pages workflow builds the wheel and then builds the
 * documentation, and Sphinx's `autodoc` imports `scenet` -- so the bytecode was always
 * newer than the wheel and the guard fired on every deploy. See issue #14.
 *
 * What matters is the source that goes *into* the wheel, so that is what gets walked.
 */

import { readdir, stat } from "node:fs/promises";
import { extname, join } from "node:path";

/**
 * Directories that never contribute to the wheel.
 *
 * `__pycache__` is the one that mattered: it is written by the interpreter on import, so
 * its mtime tracks the last time anything *read* the source rather than the last time
 * anybody changed it. The rest are here because a tool cache has the same property and
 * there is no reason to wait for each one to cause its own outage.
 */
export const IGNORED_DIRECTORIES: ReadonlySet<string> = new Set([
  "__pycache__",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".ty_cache",
]);

/**
 * Extensions that are by-products of importing rather than sources.
 *
 * Deliberately not `.pyd`: that is a compiled extension module, which is a real build
 * artifact and does ship in a wheel.
 */
export const IGNORED_EXTENSIONS: ReadonlySet<string> = new Set([".pyc", ".pyo"]);

/** A file and when it was last modified. */
export interface DatedFile {
  /** Absolute path, so a diagnostic can name the file that tripped the check. */
  readonly path: string;
  /** Modification time in milliseconds since the epoch. */
  readonly mtimeMs: number;
}

/**
 * The most recently modified source file beneath `dir`.
 *
 * Returns `null` for a tree containing no source at all, which a caller should treat as
 * "nothing to compare against" rather than as an ancient timestamp -- returning 0 would
 * silently pass the freshness check instead of reporting that the walk found nothing.
 *
 * @param dir - Directory to walk, recursively.
 * @returns The newest file and its mtime, or `null` if the tree holds no source files.
 */
export async function newestSource(dir: string): Promise<DatedFile | null> {
  let newest: DatedFile | null = null;

  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);

    if (entry.isDirectory()) {
      if (IGNORED_DIRECTORIES.has(entry.name)) continue;
      const deepest = await newestSource(full);
      if (deepest && (!newest || deepest.mtimeMs > newest.mtimeMs)) newest = deepest;
      continue;
    }

    if (IGNORED_EXTENSIONS.has(extname(entry.name))) continue;
    const { mtimeMs } = await stat(full);
    if (!newest || mtimeMs > newest.mtimeMs) newest = { path: full, mtimeMs };
  }

  return newest;
}

/**
 * Explain why a wheel is stale, or `null` if it is fresh.
 *
 * The message names the offending file. The previous version said only "older than
 * `src/`", which is what made issue #14 take an afternoon: the file responsible was
 * bytecode nobody thought to look at, and the diagnostic pointed at a directory
 * containing four hundred others.
 *
 * @param wheel - The wheel's filename, for the message.
 * @param wheelMtimeMs - When the wheel was built.
 * @param sources - Directory holding the source it was built from.
 * @returns A ready-to-throw explanation, or `null` when the wheel is up to date.
 */
export async function stalenessReason(
  wheel: string,
  wheelMtimeMs: number,
  sources: string,
): Promise<string | null> {
  const newest = await newestSource(sources);
  if (!newest || newest.mtimeMs <= wheelMtimeMs) return null;

  return (
    `${wheel} is older than ${newest.path} -- run \`uv build --wheel\` from the ` +
    "repository root. Serving it would run a compiler that no longer matches this checkout."
  );
}
