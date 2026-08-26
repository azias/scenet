# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below `1.0.0`, minor releases may break things. That is what being
below 1.0 means.

## [Unreleased]

## [0.3.0] - 2026-08-26

Diagnostics a machine can read, and the deploy that had quietly been failing for a week.

### Added

- **`scenet check`** validates documents without compiling them, and exits non-zero if
  anything is wrong. It does not stop at the first fault: pydantic reports every field
  error at once, and several files are reported together, because whoever is fixing them
  — a person or an agent — wants the whole list rather than one round trip per mistake.
- **`--format sarif`** emits [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html),
  the OASIS standard GCC, Clang and MSVC emit and GitHub code scanning ingests directly.
  **This matters more than the published JSON Schema does**: the checks that catch what a
  generator actually gets wrong — every actor id resolving to a cast member, the
  `left_of`/`right_of` graph being acyclic — are `model_validator`s, and neither is
  expressible in JSON Schema at all. Structured diagnostics are what make a
  generate/validate/repair loop work.
- **A stable rule catalogue.** Every finding carries a `ruleId` such as
  `scenet/unknown-actor`, and those identifiers do not change across releases — a
  `ruleId` that moves silently closes every alert referencing the old one and opens a
  duplicate under the new one.
- **`scenet.diagnostics`** is a public module: `diagnose_source`, `diagnose_file` and
  `to_sarif` give the same findings without the process boundary.
- **CI checks the gallery** and uploads the result to code scanning, so a broken example
  becomes an annotation on the pull request that broke it.

### Fixed

- **Diagnostics now name the field rather than the document.** pydantic reports a
  model-level validator's location as `()` — the whole document — because a validator has
  no way to say which field it was unhappy about. The two checks that matter most both
  knew the exact path and had nowhere to put it, so an unknown speaker reported
  `at <root>`. It now reports `at script.0.by`, in the prose output as well as in SARIF.
- **The documentation site and playground had not deployed since `6a43750`.** The
  playground refuses a wheel older than the source it was built from — a guard that
  exists because a silently stale playground once cost an hour. Its freshness walk
  covered every file under `src/`, including `__pycache__`, and the Pages workflow builds
  the wheel *then* builds the documentation, where Sphinx `autodoc` imports `scenet` and
  the interpreter writes fresh bytecode. So every deploy compared the wheel against its
  own doc build and refused. `v0.2.0` shipped while this was broken.
- **The stale-wheel error now names the offending file.** "older than `src/`" pointed at a
  directory of four hundred files when the culprit was one nobody thinks about.
- **`scenet check` understands scene documents.** A `panels:` document validated as a
  single panel reported `panels` as an unknown key — a confident, wrong diagnostic on
  every valid scene file in the repository. Found while wiring the gallery into CI.

### Changed

- **`ScriptSyntaxError` carries its line as a number**, not only inside the message text,
  so comic scripts get positions too. Lines only: a script line is prose, and a column
  would imply a precision the parser does not have.
- **`RuleViolationError`** is a new exported error type. It is raised only inside pydantic
  validators and never escapes as itself, so it deliberately does not inherit
  `ScenetError` — that would promise an `except ScenetError` clause could catch it.
- **CI builds the playground assets**, so a break there fails a pull request instead of
  the Pages deploy after merge.

### Upgrading

Nothing was removed and no document stops compiling. Two things a caller might notice:

- Diagnostic messages for unresolved actor ids and ordering cycles now name a path
  instead of `<root>`. Anything asserting on the old `at <root>:` text will need updating.
- `scenet.errors.__all__` gained `RuleViolationError`.

## [0.2.0] - 2026-08-26

A correctness release for the shot ladder, and a pass over the things the project says
about itself. **Panels using `medium_full`, `long_shot`, `full_shot` or `wide` render
differently than they did in 0.1.0** — see below before upgrading.

### Fixed

- **Shots that show feet now actually show them.** The crop lands the `feet` *landmark* on
  the frame edge, but the drawing continues past it: the ankle sits exactly on that
  landmark and the shin is a round-capped stroke, so half its width fell below. At long
  shot that was nine panel units hanging outside a 560-unit panel — the one thing a long
  shot is defined by not doing. `ShotSpec` gains `footroom`, non-zero only for the shots
  that show feet. It is also right compositionally: a figure standing on the exact bottom
  edge reads as falling out of the panel rather than standing on anything.
- **`medium_full` and `cowboy` are no longer the same shot.** Both cropped at `mid_thigh`,
  so the ladder had nine rungs while claiming ten, and two adjacent panels in the gallery
  were identical for no reason a reader could see. Medium full — the three-quarter shot —
  cuts at the **knees**; the cowboy or American shot cuts at **mid-thigh**, a framing that
  comes from 1930s Westerns needing the holster in frame. Two tests asserted they were
  aliases, so the bug was pinned in place by its own test suite.
- **The normative shot-type table was wrong.** `docs/reference/shot_types.md` calls itself
  normative and claimed `long_shot` had a headroom of `0.60`; the code uses `0.14`. It also
  still listed `cowboy` as an alias. A test now parses that table and asserts every crop
  landmark and headroom matches the code — a specification nobody checks is a comment in a
  different file.
- **The language reference no longer says nothing works.** `docs/reference/language.md`
  opened by telling every reader — and every model retrieving it — that "at present,
  nothing compiles", which stopped being true at phase 1, while `status.md` two clicks
  away listed phases 0–6 as done and called itself authoritative. The more-read document
  was the wrong one.

### Changed

- **`wide` remains an exact synonym for `long_shot`**, and the gallery example now says so,
  so the two identical panels read as intentional rather than broken.
- **The playground moved above the fold** in `README.md` and `docs/index.md`, and the
  repository homepage points at it. It runs the real compiler under Pyodide and it was the
  last section of the landing page, below the licence in reading order.
- **`docs/explanation/status.md` gained a Planned section.** Its phase table stopped at 6,
  so everything in the tracker was invisible in the one document claiming to be
  authoritative. The tickets are listed without numbering them into phases, because that
  order is genuinely not decided.
- **`docs/index.md` names Diátaxis.** The four sections always followed it; saying so tells
  a contributor where a new page belongs.

### Upgrading

No document stops compiling and no API changed. What changed is geometry, so identical
input produces different SVG:

- `medium_full` crops at the knees rather than mid-thigh, drawing the figure smaller.
- `long_shot`, `wide` and `full_shot` reserve footroom, which reduces the space available
  to the figure and so its scale.

If you have committed `.core.json` or SVG output for panels using those shots, regenerate
it.

## [0.1.0] - 2026-08-23

First release. A comic panel goes in as a semantic description and comes out as SVG,
deterministically — constraint solving and computational geometry, with no generative
image model anywhere in the pipeline.

### The language

- **Panel documents** (`*.panel.yaml`): panel size and margin, camera shot and angle, a
  cast of characters with poses and anchors, staging relations written as sentences
  (`alice left_of bob`), and dialogue.
- **Sequences** (`*.scene.yaml`) with `over:` sparse override, borrowed from OpenUSD's
  composition arcs: a panel names a parent and states only what differs.
- **Comic script** (`*.script`), the format writers already use, with a YAML preamble for
  what a script has no way to say. Prose descriptions are preserved and never interpreted.

All three produce the same validated IR, so nothing downstream knows there is more than
one syntax.

### The compiler

- **Camera framing** from anatomical crop landmarks — the waist, the chest, the shoulders
  — rather than a fraction of panel height, so a shot type does not bake in one body and
  one pose. One camera and one scale per panel.
- **Actor placement** through a Cassowary solver, with priorities: non-overlap and declared
  ordering are required, panel bounds are strong, requested anchors are weak. A crowded
  panel lets a figure bleed off the edge rather than refusing to compile.
- **The camera retreats** when a cast will not fit across the frame, and says so, because a
  panel that is quietly not the shot you asked for is a panel you cannot debug.
- **Lettering** measured against real font metrics, with line breaking scored on the shape
  a letterer would choose. The font is a declared dependency, never a system lookup —
  determinism requires text to measure identically everywhere.
- **Balloon placement** by scored candidate search: a balloon may never cover a face, and
  reading order is a hard constraint checked against every predecessor rather than only
  the last one.
- **Tail routing** that stops at the face outline instead of the mouth anchor buried
  inside the head, and bends around an obstructing face when it must.

### Three tiers, all of them yours

```
*.panel.yaml  →  IR (scene graph)  →  Panel Core (.core.json)  →  SVG
```

Panel Core is a real, writable format rather than a hidden data structure: a layout can be
exported, read, diffed, hand-adjusted, and read back for emission.

### Tools

- `scenet build`, with `--core`, `--debug`, `--strip` and `--live-text`.
- `scenet schema`, generating the JSON Schema from the compiler's own models.
- A **browser playground** running the compiler unmodified under WebAssembly via Pyodide,
  with a Monaco editor fed that same schema, and fifteen worked examples. Entirely
  self-hosted: it makes no request to any other origin.
- A **VS Code extension** with schema-driven completion, validation and a live preview.

### The library

- `import scenet` exposes a curated public API: compiling, parsing, rendering, both
  intermediate tiers, the describing types, puppets and one error hierarchy rooted at
  `ScenetError`.
- Ships `py.typed`, so downstream type checkers read the annotations directly.

### Documentation

Structured on Diátaxis — tutorial, how-to, reference, explanation — and built with Sphinx.
**Every Python example is executed by the test suite**, so an example that omits an import
or has drifted out of step with the code fails the build.

### Security

- Identifiers and dialogue are escaped into their SVG attributes and elements. An actor id
  containing a quotation mark could previously close its own attribute, which is a
  scripting vector wherever the output is rendered inline.
- Dependency licenses are gated in CI against an explicit allowlist, checked against a
  runtime-only environment.
- Published to PyPI through Trusted Publishing with Sigstore attestations, so the
  repository holds no publishing credential of any kind.

### Known limitations

- Page composition — tiers, panels of varying size, the page-level reading path — is not
  built. `--strip` lays panels in a row and nothing more.
- There is no interpretation layer: a panel has no *style*, and figures render as
  wireframe puppets.
- Prose in a comic script is preserved but never interpreted. Describing rain does not
  produce rain.
- `long_shot` and `full_shot` crop at the same landmark, so with no environment to show
  they can differ only by headroom.

[Unreleased]: https://github.com/azias/scenet/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/azias/scenet/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/azias/scenet/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/azias/scenet/releases/tag/v0.1.0
