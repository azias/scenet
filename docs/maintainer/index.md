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

## How a change reaches main

`main` is protected by a repository ruleset. **Direct pushes are rejected** — including
by the maintainer, deliberately, because a rule with an exception for the person most
likely to be in a hurry is not a rule.

```bash
git switch -c fix/whatever
# ... work ...
git push -u origin fix/whatever
gh pr create --fill
gh pr checks --watch      # all six must pass
gh pr merge --squash --delete-branch
```

The ruleset requires:

| Rule | Why |
|---|---|
| Pull request required | Nothing reaches `main` without a diff somebody could have read |
| Six status checks green | Both Python versions, docs, licences, strict types, TypeScript |
| Branch up to date before merge | A green check against a stale base proves nothing |
| Linear history | `main` stays bisectable; a regression can be found by halving |
| No force push, no deletion | History is evidence |

**Approvals are set to zero, on purpose.** GitHub does not let you approve your own pull
request, so on a single-maintainer repository requiring even one approval would make
`main` permanently unmergeable. The status checks are the gate; the pull request is the
record. Add a review requirement the day a second person has commit rights.

Tags matching `v*` are protected too: they cannot be deleted, moved or force-pushed. A
released version number is a promise, and PyPI enforces the same thing from the other
side — a version can never be re-uploaded.

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
