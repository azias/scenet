# Scenet — agent instructions

A compiler that turns a semantic description of a comic panel into SVG. Deterministic geometry and
constraint solving; **no generative image model is involved anywhere**.

## Pipeline

```
*.panel.yaml  →  IR (scene graph)  →  Panel Core (.core.json)  →  SVG
  authored         validated           resolved, numeric          emitted
```

Keep these tiers separate. The frontend never computes coordinates; the solver never touches
artwork; the emitter never makes layout decisions.

## Non-negotiables

- **Determinism.** Identical input must produce byte-identical output. No wall-clock time, no
  unseeded randomness, no reliance on set/dict iteration order, no absolute paths in output. This is
  what makes golden-file tests meaningful.
- **The solver never sees artwork.** It sees a geometric contract only: bounding boxes, named
  anchors, exclusion polygons, gaze vectors. Rendering must stay swappable.
- **Everything is typed.** `ty` is a blocking gate. Bare `# type: ignore` is rejected (`PGH003`);
  use a specific code and a reason.
- **No `from __future__ import annotations`** — it breaks pydantic, which resolves annotations
  at runtime to build validators, and it is on a deprecation path.
- **Quote self- and forward-references** (`-> "Point"` inside `class Point`). Python 3.14
  evaluates annotations lazily (PEP 649) so unquoted works there, but the floor is 3.12, where
  it raises NameError at import. CI runs the suite on 3.12 to catch this; `ruff` targets py312
  so `UP037` does not strip the quotes back off. Do not reach for `Self` to dodge the quoting
  unless the body really does use `cls(...)` — otherwise it promises subclass behaviour the
  code does not deliver, and `ty` will say so.
- **TypeScript, never plain JavaScript**, wherever JS appears — including glue and build scripts.
- **Tests first.** Each module's tests land before its implementation.
- **No personal information in committed files.** Attribute to "Scenet contributors".

## Commands

```bash
uv sync                  # install; uv manages the Python version too
uv run pytest
uv run ruff format . && uv run ruff check --fix .
uv run ty check
```

## Design constraints worth knowing before changing the language

- **Cassowary is linear.** Non-overlap is a disjunction ("A left of B *or* B left of A"), which a
  linear solver cannot express. The DSL resolves ordering at parse time so the solver receives a
  linear system. Any new construct that reintroduces a disjunction must be resolved in the frontend.
- **Shot types are defined by a crop landmark plus a headroom fraction**, in head-height units — not
  by a percentage of panel height. See `docs/spec/shot_types.md`, which is normative.
- **Balloon size depends on real font metrics.** Text is measured with `fontTools` against a font
  supplied as a declared dependency, never a system lookup. Measurement and rendering must agree
  exactly, which is why lettering is emitted as glyph outlines by default.
- **Reading order is a hard constraint**, not a preference: a balloon may never sit above-and-left
  of the one that precedes it in the script.

## Reference

`docs/spec/` is the specification. `docs/knowledge_base/domain/prior_art.md` records which prior work
each design decision came from, and which well-known references were deliberately *not* used.
