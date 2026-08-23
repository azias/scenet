# Maintainer guide

For anyone with commit rights, and for the future version of yourself who has forgotten
how any of this works.

| | |
|---|---|
| [Releasing](releasing.md) | How to cut a release, and what happens when you do |
| [Credentials](secrets.md) | Which secrets exist (almost none), and why |

## The gates

Everything below runs in CI on every push and pull request. Run them locally first;
they are fast.

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

`pytest` runs more than the unit tests. It also executes every example in every docstring
and every fenced Python block in the Markdown documentation, so a documented example that
has drifted fails the build. That is deliberate: the commonest complaint about Python
library documentation is examples that do not run, and the only durable fix is to run
them.

Coverage is gated at 90%.

The documentation build is a separate gate:

```bash
uv run sphinx-build -W --keep-going -b html docs docs/_build/html
```

`-W` turns warnings into errors, so a broken cross-reference or a page missing from a
table of contents fails rather than quietly producing a worse site.

## Non-negotiables

These are enforced by tests, not by good intentions:

- **Determinism.** Identical input produces byte-identical output. No wall-clock time, no
  unseeded randomness, no reliance on set or dict iteration order, no absolute paths in
  output. Golden-file tests are meaningless without it.
- **The solver never sees artwork.** It sees a geometric contract only — bounding boxes,
  named anchors, exclusion polygons, gaze vectors. Rendering stays swappable.
- **Everything is typed.** `ty` is a blocking gate. A bare `# type: ignore` is rejected;
  use a specific code and give a reason.
- **Everything public is documented.** `ruff`'s pydocstyle rules are blocking, and a test
  asserts that every name in `scenet.__all__` has a docstring.
- **TypeScript, never plain JavaScript**, wherever JS appears — including build scripts.
- **No personal information in committed files.** Attribution is to "Scenet contributors".
  Commit metadata is a separate matter and carries whatever the author's git config says.

## Python version floor

The floor is **3.12**, and CI runs the suite on both 3.12 and 3.14. This is not
decoration. Before Python 3.14 and PEP 649, annotations are evaluated at definition time,
so a self-referential `-> Point` inside `class Point` raises `NameError` at import.
Developing only on 3.14 hides that completely — it first surfaced in the browser, where
Pyodide ran an older Python, and cost an afternoon.

Self- and forward-references are therefore quoted (`-> "Point"`), and `ruff` targets
`py312` so that `UP037` does not helpfully strip the quotes back off.

Do not reach for `Self` to dodge the quoting unless the body really does use `cls(...)`.
Otherwise it promises subclass-preserving behaviour the code does not deliver, and `ty`
will say so.

```{toctree}
:hidden:
:maxdepth: 1

releasing
secrets
```
