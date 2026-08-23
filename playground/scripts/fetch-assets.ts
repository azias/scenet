/**
 * Assemble everything the playground serves that is not built from source.
 *
 * Three things end up in `public/`:
 *
 *   1. The Pyodide runtime, copied out of `node_modules`.
 *   2. The Python wheels Pyodide will load, downloaded once at build time.
 *   3. The JSON Schemas, generated from the compiler's own models.
 *
 * All of it is **self-hosted**. The obvious alternative is to point Pyodide at
 * jsDelivr and let it fetch what it needs at runtime, which is one line instead of
 * this file. It was rejected for three reasons: the page then makes requests to a
 * third-party origin on every load, which rules out a strict Content-Security-Policy;
 * a CDN outage takes the playground down; and the versions a visitor gets are whatever
 * the CDN serves rather than the ones this build was tested against.
 *
 * The cost is about 22 MB in the deployed site, which for a page that ships a Python
 * interpreter is not the line item worth optimising.
 */

import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { copyFile, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { parse as parseYaml } from "yaml";

const here = dirname(fileURLToPath(import.meta.url));
const playground = dirname(here);
const publicDir = join(playground, "public");
const pyodideOut = join(publicDir, "pyodide");

const require = createRequire(import.meta.url);
const pyodideDir = dirname(require.resolve("pyodide/package.json"));

interface PyodidePackage {
  readonly name: string;
  readonly file_name: string;
  readonly depends: readonly string[];
}
interface PyodideLock {
  readonly info: { readonly python: string };
  readonly packages: Record<string, PyodidePackage>;
}

/** Files the browser actually needs. Source maps and the Node entry point are not. */
const RUNTIME_FILES = [
  "pyodide.mjs",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "python_stdlib.zip",
  "pyodide-lock.json",
];

/** Packages Scenet imports that the Pyodide distribution already carries. */
const WANTED = ["micropip", "numpy", "pydantic", "kiwisolver", "shapely", "fonttools", "pyyaml"];

/**
 * The lettering font, which is not part of the Pyodide distribution.
 *
 * Determinism requires that text measures identically everywhere, which a system font
 * lookup cannot promise -- so the font arrives as an ordinary Python dependency. These
 * two are pure-Python wheels from PyPI proper, vendored here for the same reason as
 * everything else: so the page makes no request to any other origin.
 */
const PYPI_WHEELS = ["fonts", "font-source-sans-pro"];

interface PyPiRelease {
  readonly filename: string;
  readonly url: string;
  readonly packagetype: string;
}

/** Resolve and download the newest pure-Python wheel for a PyPI project. */
async function vendorPyPiWheel(name: string, into: string): Promise<string> {
  const response = await fetch(`https://pypi.org/pypi/${name}/json`);
  if (!response.ok) {
    throw new Error(`${response.status} resolving ${name} on PyPI`);
  }
  const meta = (await response.json()) as {
    info: { version: string };
    releases: Record<string, PyPiRelease[]>;
  };
  const files = meta.releases[meta.info.version] ?? [];
  // The Python tag matters. Installing by name lets micropip pick a compatible file,
  // but installing from a URL makes micropip enforce the tag -- and
  // `font-source-sans-pro` publishes a py2 wheel alongside its py3 one, listed first.
  // Taking whichever came first fails at boot with a platform-compatibility error.
  const wheel = files.find(
    (file) =>
      file.packagetype === "bdist_wheel" &&
      file.filename.endsWith("-any.whl") &&
      (file.filename.includes("-py3-") || file.filename.includes("-py2.py3-")),
  );
  if (wheel === undefined) {
    throw new Error(`${name} ${meta.info.version} has no py3 pure-Python wheel`);
  }
  const target = join(into, wheel.filename);
  if (!existsSync(target)) {
    await download(wheel.url, target);
  }
  return wheel.filename;
}

function closure(lock: PyodideLock, wanted: readonly string[]): PyodidePackage[] {
  const found = new Map<string, PyodidePackage>();
  const visit = (name: string): void => {
    // The lockfile keys `pydantic-core` with a hyphen but reports its `name` -- and
    // lists it in other packages' `depends` -- with an underscore. Neither spelling is
    // reliably the key, so try both.
    const lower = name.toLowerCase();
    const entry =
      lock.packages[lower] ??
      lock.packages[lower.replaceAll("_", "-")] ??
      lock.packages[lower.replaceAll("-", "_")];
    if (entry === undefined) {
      throw new Error(`pyodide-lock.json has no package '${name}'`);
    }
    if (found.has(entry.name)) return;
    found.set(entry.name, entry);
    for (const dependency of entry.depends) visit(dependency);
  };
  for (const name of wanted) visit(name);
  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name));
}

async function download(url: string, target: string): Promise<number> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${url}`);
  }
  const bytes = Buffer.from(await response.arrayBuffer());
  await writeFile(target, bytes);
  return bytes.byteLength;
}

interface ManifestEntry {
  readonly file: string;
  readonly title: string;
  readonly kind: "panel" | "scene" | "script";
}

/**
 * Inline the example gallery into a single JSON file the page fetches once.
 *
 * The examples are real files under `examples/gallery/`, and the Python test suite
 * compiles every one of them. So the playground cannot offer an example that does not
 * work -- which is the failure mode of every hand-maintained list of demo strings.
 */
async function writeExamples(): Promise<void> {
  const gallery = join(playground, "..", "examples", "gallery");
  const manifest = parseYaml(await readFile(join(gallery, "manifest.yaml"), "utf8")) as {
    examples: ManifestEntry[];
  };

  const examples = [];
  for (const entry of manifest.examples) {
    // Normalised to LF. Python's text mode does this silently when reading a file, so
    // the test suite never sees CRLF -- but this inlines raw bytes into JSON that the
    // browser then feeds straight to the parser. A CRLF comic script used to be
    // rejected here and nowhere else.
    const source = (await readFile(join(gallery, entry.file), "utf8"))
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n");
    examples.push({ title: entry.title, kind: entry.kind, file: entry.file, source });
  }

  await writeFile(
    join(publicDir, "examples.json"),
    `${JSON.stringify(examples, null, 2)}\n`,
  );
  console.log(`examples: ${examples.length} from examples/gallery/`);
}

async function main(): Promise<void> {
  await mkdir(pyodideOut, { recursive: true });

  for (const name of RUNTIME_FILES) {
    await copyFile(join(pyodideDir, name), join(pyodideOut, name));
  }

  const lock = JSON.parse(
    await readFile(join(pyodideOut, "pyodide-lock.json"), "utf8"),
  ) as PyodideLock;

  // Pinned to the version in node_modules, never "latest". The wheels a visitor runs
  // are the wheels this build resolved. The lockfile itself carries no version -- only
  // the Python and ABI it targets -- so the package manifest is the source of truth.
  const { version } = JSON.parse(
    await readFile(join(pyodideDir, "package.json"), "utf8"),
  ) as { version: string };
  const base = `https://cdn.jsdelivr.net/pyodide/v${version}/full/`;
  const packages = closure(lock, WANTED);

  let total = 0;
  let fetched = 0;
  for (const entry of packages) {
    const target = join(pyodideOut, entry.file_name);
    if (existsSync(target)) {
      total += (await readFile(target)).byteLength;
      continue;
    }
    total += await download(base + entry.file_name, target);
    fetched += 1;
  }

  console.log(
    `pyodide ${version} (Python ${lock.info.python}): ${packages.length} packages ` +
      `(${fetched} downloaded, ${(total / 1e6).toFixed(1)} MB)`,
  );

  const fontWheels: string[] = [];
  for (const name of PYPI_WHEELS) {
    fontWheels.push(await vendorPyPiWheel(name, pyodideOut));
  }
  await writeFile(
    join(publicDir, "font-wheels.json"),
    `${JSON.stringify(fontWheels, null, 2)}\n`,
  );
  console.log(`fonts: ${fontWheels.join(", ")}`);

  // The schemas are generated by the compiler itself, so the completion the playground
  // offers and the validation it applies come from the same models that compile the
  // document. They are copied rather than regenerated here: `editor/schemas` is the
  // committed copy, and a test fails if it goes stale.
  const schemaOut = join(publicDir, "schemas");
  await mkdir(schemaOut, { recursive: true });
  for (const name of ["panel.schema.json", "scene.schema.json"]) {
    const source = join(playground, "..", "editor", "schemas", name);
    await copyFile(source, join(schemaOut, name));
  }

  await writeExamples();

  // The wheel the browser installs is the one `uv build` produced, unmodified. There is
  // no browser-specific build of the compiler, so nothing here can diverge from what
  // the command line runs.
  const dist = join(playground, "..", "dist");
  const wheels = existsSync(dist)
    ? (await readdir(dist)).filter((name) => name.endsWith(".whl"))
    : [];

  if (wheels.length === 0) {
    console.warn("no wheel in ../dist -- run `uv build --wheel` from the repository root");
  } else if (wheels.length > 1) {
    throw new Error(`expected one wheel in ${dist}, found ${wheels.length}: ${wheels.join(", ")}`);
  } else {
    const wheel = wheels[0]!;
    const bytes = await readFile(join(dist, wheel));
    await writeFile(join(publicDir, wheel), bytes);
    // The page discovers the wheel by name at runtime. Hardcoding it in TypeScript
    // would break the playground on the next version bump -- and break it in the
    // browser only, where nothing in CI would notice.
    const digest = createHash("sha256").update(bytes).digest("hex");
    await writeFile(
      join(publicDir, "wheel.json"),
      `${JSON.stringify({ wheel, sha256: digest }, null, 2)}\n`,
    );
    console.log(`wheel: ${wheel} (${(bytes.byteLength / 1e3).toFixed(0)} kB)`);
  }
}

await main();
