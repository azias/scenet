# Command line

```
scenet [--version] <command> [options]
```

Two commands: `build` compiles a document, `schema` emits the JSON Schema. A bare
`scenet` prints help to stderr and exits **2** — it did nothing, and a script chaining off
its status should not read that as success.

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
