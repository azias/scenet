# Solver and toolchain choices

Non-obvious decisions, with reasoning, so they can be revisited rather than rediscovered.

## Shot types are crop landmarks, not panel fractions

The tempting definition of a medium shot is "the figure fills about 60% of panel height". It is
wrong. A shot type names **where the frame cuts the body** — waist, chest, shoulders. What fraction
of the panel the figure then occupies is a *consequence*, and it differs for a child versus an
adult, or a seated versus a standing pose. Encoding the fraction bakes in one body and one pose.

See [shot_types.md](../reference/shot_types.md), which is normative.

## Cassowary is linear, so the language must resolve disjunctions

Non-overlap between two actors is a disjunction — A left of B, **or** B left of A — and no linear
solver can express a choice. Rather than reaching for a mixed-integer solver, the DSL resolves
ordering at parse time, so the solver always receives a linear system.

This is a *language* constraint, not merely an implementation detail: it is why there is no
unordered `beside` predicate. Any future construct that reintroduces a disjunction must resolve it
in the frontend.

## Balloon placement: candidate scoring, not a grid sweep

Discretising the panel into a cost grid and scanning every cell is the obvious approach, and is both
slower and worse. Balloons belong in a small number of sensible positions relative to their speaker.
So candidates are generated map-labelling style — a ring of directions and radii around the
speaker's head, plus the panel corners — and scored. Fewer evaluations, more natural results.

## Emanata are a soft cost, not part of the hull

Plewds, squeans, grawlixes and briffits are drawn outside the head circle, which is exactly where
balloons go, so they had to mean something to the solver. There were three choices:

- **Enter the hull.** The simplest, and wrong. The hull is also what staging spaces characters by
  and what the camera fits, so a character who started sweating would stand further from everyone
  else, and the framing could retreat. A mark would move people the author never asked to move.
- **Forbid them outright, as a face is.** A face exclusion is affordable because a face is one small
  disc that tails already route around. Emanata ring the head and sit on the ground behind it; making
  all of that illegal turns a crowded panel into `BalloonPlacementError` over a drop of sweat.
- **A cost of their own.** Each mark has a zone, and a balloon or caption pays for the fraction of
  its box that covers one — the same normalisation as hull occlusion, weighted above it, because a
  balloon over a shoulder hides a shoulder and a balloon over a plewd deletes what the panel was
  saying. The speaker gets no discount: their balloon over their own sweat still hides it.

The third is what shipped. Its proof is in `tests/test_emanata.py`: every example in the repository,
recompiled with every mark on every cast member, puts every figure exactly where it was and still
compiles; and a panel without marks is byte-identical to one compiled before marks existed.

The cost of not moving anybody is that the camera makes no room either, so marks over the tallest
head can be cropped at a tight shot. That is reported as a note rather than silently drawn off the
page.

## Text metrics are a hard dependency, not a detail

A balloon's size is a function of its text, wrapped at some measure, in a specific font. Nothing
downstream — placement, occlusion, reading order — can be computed until that size is known. The
font is therefore bundled rather than referenced, and measurement uses `fontTools` against that
exact file. If renderer and measurer disagree even slightly, output stops being deterministic.

## `ty` gates the build; `basedpyright` advises

[`ty`](https://docs.astral.sh/ty/) is Astral's type checker: fast, and consistent with `uv` and
`ruff`. It is also **pre-1.0 and in beta**.

Gating CI on a beta usually risks an upstream change reddening the build unbidden — but `uv.lock`
pins `ty` to an exact version, so it changes only when deliberately bumped. That objection does not
apply here.

The risk pinning does *not* solve is coverage: pre-1.0 `ty` is documented to miss advanced typing
patterns Pyright catches — Protocols, `ParamSpec`, recursive types, complex overloads. Since the IR
is pydantic models throughout and the solver will lean on Protocols, that is the wrong blind spot to
accept silently. So `basedpyright --strict` runs as a **second, non-blocking** job. Anything it
reports that `ty` missed is signal. Delete that job once `ty` reaches 1.0 and closes the gap.

## `TC001`-`TC003` are disabled deliberately

Ruff's flake8-type-checking rules want annotation-only imports moved into `if TYPE_CHECKING` blocks.
Declined, for two reasons:

1. **Pydantic resolves annotations at runtime** to build validators. An import hidden behind
   `TYPE_CHECKING` makes the model fail to build — and the IR is pydantic models throughout, so the
   rule is an active hazard rather than a style preference.
2. The import-time saving it exists for is largely gone in Python 3.14, which already evaluates
   annotations lazily (PEP 649/749).

That same PEP pair is why `from __future__ import annotations` is banned here: forward references
work unquoted, and the future import is on a deprecation path.

## License gate checks runtime dependencies only

Dev tooling is never distributed, so it is out of scope — which matters concretely, because
`hypothesis` is MPL-2.0 and would otherwise fail a permissive-only allowlist for no good reason. CI
therefore syncs with `--no-dev` first.

One trap worth recording: a bare `uv run` **re-syncs the project**, silently reinstalling the dev
dependencies `--no-dev` just pruned, so the gate checks the wrong environment and passes
meaninglessly. `uv run --no-sync` is required. This was caught by running the gate and reading its
output, not by reasoning about it — which is the general lesson.
