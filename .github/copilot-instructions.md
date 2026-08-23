# Copilot instructions

Scenet compiles a semantic description of a comic panel (`*.panel.yaml`) into SVG. It is a
deterministic geometry and constraint-solving compiler — never suggest generative image models.

- Python 3.14, fully typed. Do not emit `from __future__ import annotations`: 3.14 evaluates
  annotations lazily (PEP 649/749).
- Prefer PEP 695 syntax (`def f[T](...)`, `type Alias = ...`), `X | None`, `list[T]`, `@override`.
- Runtime validation uses pydantic; everything past parsing is plain typed Python.
- Wherever JavaScript would be used, write **TypeScript** with `strict: true`.
- Output must be deterministic: no clock, no unseeded randomness, no absolute paths.
- The solver operates on geometry contracts (bounding boxes, anchors, exclusion polygons) and never
  on artwork.

Tooling is `uv` + `ruff` + `ty`. See `CLAUDE.md` for the full rules.
