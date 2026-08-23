# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the version is below `1.0.0`, minor releases may break things. That is what being
below 1.0 means.

## [Unreleased]

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

[Unreleased]: https://github.com/azias/scenet/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/azias/scenet/releases/tag/v0.1.0
