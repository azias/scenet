// Assemble `public/` -- the directory GitHub Pages serves.
//
// The wheel is copied rather than rebuilt: the playground installs the exact artefact
// `uv build` produces, so the browser runs the same compiler as the command line and
// there is nothing that could quietly diverge.
import { copyFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const OUT = "public";
const DIST = join("..", "dist");

for (const stale of readdirSync(OUT, { withFileTypes: true })) {
  if (stale.name.endsWith(".whl")) {
    rmSync(join(OUT, stale.name));
  }
}

for (const asset of ["index.html", "style.css"]) {
  copyFileSync(join("src", asset), join(OUT, asset));
}

const wheels = readdirSync(DIST).filter((name) => name.endsWith(".whl"));
if (wheels.length !== 1) {
  throw new Error(
    `expected exactly one wheel in ${DIST}, found ${wheels.length}. ` +
      "Run `uv build --wheel` from the repository root first, and clear stale builds.",
  );
}
const wheel = wheels[0];
copyFileSync(join(DIST, wheel), join(OUT, wheel));

// The page discovers the wheel by name at runtime. Hardcoding it in the TypeScript
// would silently break the playground on the next version bump -- and break it in
// the browser only, where nothing in CI would notice.
writeFileSync(join(OUT, "wheel.json"), `${JSON.stringify({ wheel }, null, 2)}
`);

console.log(`assembled ${OUT}/ with ${wheel}`);
