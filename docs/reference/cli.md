# Command line

```
scenet [--version] <command> [options]
```

Three commands: `build` compiles a document, `check` validates one without compiling it,
and `schema` emits the JSON Schema. A bare `scenet` prints help to stderr and exits **2**
— it did nothing, and a script chaining off its status should not read that as success.

## `scenet build`

```
scenet build SOURCE [-o OUTPUT] [--core] [--debug] [--live-text] [--strip] [--quiet]
```

Compiles `SOURCE` to SVG. The frontend is chosen by extension:

| Extension | Read as |
|---|---|
| `.panel.yaml`, `.scene.yaml`, `.yaml`, `.yml` | YAML — single panel or a `panels:` sequence |
| `.script` | Comic script |

### Options

`-o`, `--output PATH`
: Where to write. Defaults to the source's name with an `.svg` extension, alongside it.
  Note that `duel.panel.yaml` becomes `duel.svg`, not `duel.panel.svg`.

`--core`
: Also write the resolved Panel Core as JSON — every coordinate the compiler chose, in a
  format you can read, diff and hand-edit. See [Panel Core](panel_core.md).

`--debug`
: Also write a diagnostic overlay showing the geometry the solver was working against:
  silhouette hulls, face exclusion zones, named anchors, gaze vectors and tail routes.
  This is usually the fastest way to see why a panel came out the way it did.

`--live-text`
: Emit selectable `<text>` elements instead of glyph outlines. Smaller files and
  selectable text, but the result depends on the reader having a metrically compatible
  font installed. The default emits outlines, which makes the file genuinely
  self-contained.

`--strip`
: For a multi-panel document, also lay every panel out side by side in reading order, as
  one extra file. Ignored for a single panel.

`--quiet`
: Suppress the `wrote` and `note:` lines. You do not normally want this: the notes are
  where the compiler tells you it did something you did not ask for.

### Output naming

A single-panel document writes to the requested name. A multi-panel document suffixes each
panel with its own name, so the mapping back to the source stays obvious:

```
sequence.scene.yaml  →  sequence.establishing.svg
                        sequence.reaction.svg
                        sequence.strip.svg          (with --strip)
```

### Exit status

| Code | Meaning |
|---|---|
| 0 | Compiled |
| 1 | The document could not be compiled — reported as a plain message, not a traceback |
| 2 | Usage error, or the source file does not exist |

Every error the compiler raises inherits `ScenetError`, and all of them mean "your panel
cannot be compiled" rather than "scenet broke". They print as one line. A traceback from
`scenet` is a bug worth reporting.

### Examples

```bash
scenet build examples/duel.panel.yaml
```

```bash
scenet build examples/duel.panel.yaml --core --debug
```

```bash
scenet build examples/sequence.scene.yaml --strip
```

```bash
scenet build examples/umbrella.script --strip -o out/umbrella.svg
```

## `scenet check`

```
scenet check SOURCE... [--format {text,sarif}] [-o OUTPUT] [--quiet] [--deep]
```

Reports everything wrong with one or more documents and exits non-zero if anything is.
Nothing is written unless you ask for it — no SVG, no Panel Core.

Unlike `build`, this does not stop at the first fault. pydantic reports every field error
at once and several files are reported together, because whoever is fixing them — a person
or an agent — wants the whole list rather than one round trip per mistake.

Beyond validating the IR, `check` resolves every cast member's `reference`, `pose` and
`expression` against the puppet library — the IR alone cannot tell `pointing` from
`smirking`, since both are just strings until something looks them up. The library is
read once per document, only when there is a cast to check against it, so a document
with no cast pays nothing extra. This is still the cheap pass: no solver, no font
metrics, no balloon placement — those are what `--deep` adds.

### Why this exists

**No JSON Schema can catch the errors that matter most here.** The interesting checks are
`model_validator`s: every actor id in `staging` and `script` resolving to a cast member,
and the `left_of`/`right_of` graph being acyclic. Neither is expressible in JSON Schema,
and both are exactly what a generator gets wrong. So structured diagnostics — not the
published schema — are what make a generate/validate/repair loop work.

### Options

`--format text` (default)
: One line per finding on stderr, `file:line:column: rule: message`. What a person reads.

`--format sarif`
: [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html), the
  OASIS standard GCC, Clang and MSVC emit and GitHub code scanning ingests directly.
  Nothing but the document reaches stdout, so redirecting it produces a file a parser
  accepts.

`-o`, `--output PATH`
: Write the report to a file instead of stdout.

`--quiet`
: Suppress the per-file `ok` line. Findings are always reported — this hides the
  reassurance, never the diagnosis.

`--deep`
: Also run the full compiler on any document that passes every cheap check, to
  additionally catch `layout` and `balloon-placement` — two rules in the catalogue that
  the cheap pass cannot produce, because they only surface once the solver actually
  runs. Off by default: it costs a real compile, including font metrics. Skipped for a
  document the cheap pass already found something wrong with, so a document with a bad
  pose reports that once rather than a second, worse-located finding for the same fault.

### Exit status

| Code | Meaning |
|---|---|
| 0 | Every document is valid |
| 1 | At least one finding |
| 2 | Usage error, or a source file does not exist |

The status means the same thing in both formats, so CI can key off it without parsing
anything.

### Rules

Every finding carries a stable `ruleId`. These identifiers **do not change across
releases**: a `ruleId` that moves silently closes every alert that referenced the old one
and opens a duplicate under the new one, so renaming one is a breaking change even though
nothing stops compiling.

| Rule | Raised when |
|---|---|
| `scenet/syntax` | The file is not valid YAML, or is empty |
| `scenet/not-a-mapping` | The top level is a list or a scalar |
| `scenet/unknown-key` | A key the language does not define — usually a typo |
| `scenet/missing-field` | A required value was not supplied |
| `scenet/invalid-field` | A known key holding the wrong type or an out-of-range value |
| `scenet/panel-geometry` | Non-positive size, or margins leaving no usable area |
| `scenet/unknown-actor` | An id in `staging` or `script` that is not in `cast` |
| `scenet/reflexive-relation` | A relation relating an actor to itself |
| `scenet/ordering-cycle` | `left_of`/`right_of` relations that form a cycle |
| `scenet/composition` | An `over:` chain that is missing or cyclic |
| `scenet/unknown-puppet` | A `reference` naming a character the library lacks |
| `scenet/unknown-pose` | A `pose` naming one its puppet does not declare |
| `scenet/unknown-expression` | An `expression` naming one its puppet does not declare |
| `scenet/layout` | Valid, but no layout satisfies its required constraints (`--deep` only) |
| `scenet/balloon-placement` | No legal position exists for a balloon (`--deep` only) |
| `scenet/internal` | A failure with no more specific rule — worth reporting |

### Source positions

`yaml.safe_load` discards the position of every value, so the document is composed a
second time with `yaml.compose`, whose node tree carries `start_mark` and `end_mark`. Those
marks are 0-based and SARIF is 1-based; the conversion happens once, at that boundary.

`ruamel.yaml`'s `.lc` marks would do the same job and are what one usually reaches for.
They were not used: PyYAML is already a dependency, so a second YAML implementation in the
runtime — and in the licence gate — would buy nothing.

Comic scripts are line-oriented, so a finding there carries a line and no column. A script
line is prose, and pointing at a character within it would imply a precision the parser
does not have.

### Fingerprints

Each result carries a `partialFingerprints` entry under `scenetDiagnostic/v1`, derived
from the rule, the structural path, the message and the file — deliberately **not** from
the line number. A fingerprint keyed on position changes whenever anybody adds a comment
at the top of the file, which turns one long-standing alert into a new alert on every
edit, and de-duplicating alerts is the entire point of the field.

### Examples

```bash
scenet check examples/duel.panel.yaml
```

```bash
scenet check examples/gallery/*.yaml
```

```bash
scenet check --format sarif examples/duel.panel.yaml > results.sarif
```

```bash
scenet check --deep examples/gallery/*.yaml
```

Uploading to GitHub code scanning, which is how findings become annotations on a pull
request:

```yaml
- run: uv run scenet check --format sarif -o results.sarif examples/gallery/*.yaml
- uses: github/codeql-action/upload-sarif@v4
  with:
    sarif_file: results.sarif
```

### As a library

The same findings are available without the process boundary:

```python
from pathlib import Path

from scenet.diagnostics import diagnose_source, to_sarif

source = """
cast:
  alice: {reference: alice}
script:
  - say: {by: bpb, text: Hello}
"""

found = diagnose_source(source, source=Path("duel.panel.yaml"))
finding = found[0]

assert finding.rule == "unknown-actor"
assert finding.path == ("script", 0, "by")
assert finding.region.start.line == 5

document = to_sarif(found, root=Path.cwd())
assert document["runs"][0]["results"][0]["ruleId"] == "scenet/unknown-actor"
```

The assertions are the point: this block is executed by the test suite, so an example
that stopped being true would fail the build rather than quietly misinform.

`diagnose_file` is the same thing for a path on disk, and picks the frontend by
extension.

`scenet.diagnostics` is a public module. It is not re-exported from the `scenet` package
namespace, because it reads the package version and importing it from `__init__` would
close an import cycle.

## `scenet schema`

```
scenet schema [-o OUTPUT] [--scene]
```

Emits the JSON Schema for a panel document, derived from the same pydantic models the
compiler validates against. Editors use it for completion and inline validation, so what
the editor suggests cannot drift from what compiles — see
[editor support](../howto/editor_support.md).

`-o`, `--output PATH`
: Write to a file instead of stdout.

`--scene`
: Emit the multi-panel scene schema instead of the single-panel one. A scene allows the
  same keys as a panel — where they act as defaults every panel inherits — plus `panels:`,
  whose members may additionally carry `over:`.

```bash
scenet schema -o panel.schema.json
scenet schema --scene -o scene.schema.json
```

The output is sorted and indented, so it is stable under version control.

## `scenet --version`

Prints the installed version and exits 0.

## Determinism

The same input always produces byte-identical output — no wall-clock time, no unseeded
randomness, no absolute paths in the output. Two runs on different machines produce files
you can compare with `cmp`.
