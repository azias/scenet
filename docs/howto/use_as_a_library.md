# Use Scenet as a library

The `scenet` command is a thin wrapper over the same functions you can call yourself.
This page covers the public API: what is in it, what is not, and how to reach the parts
the command line does not expose.

## The one function you probably want

```python
from scenet import compile_source, render

result = compile_source("""
panel: {size: [900, 600]}
cast:
  alice: {reference: alice}
script:
  - say: {by: alice, text: "Compiled from a string."}
""")

svg = render(result.core)
assert svg.lstrip().startswith("<?xml")
```

## Choosing an entry point

| You have | Call |
|---|---|
| A panel as a string | {func}`compile_source <scenet.pipeline.compile_source>` |
| A `*.panel.yaml` path | {func}`compile_file <scenet.pipeline.compile_file>` |
| A multi-panel string | {func}`compile_scene <scenet.pipeline.compile_scene>` |
| A `*.scene.yaml` path | {func}`compile_scene_file <scenet.pipeline.compile_scene_file>` |
| Any supported file, unknown type | {func}`compile_document <scenet.pipeline.compile_document>` |
| An already-validated `PanelIR` | {func}`compile_ir <scenet.pipeline.compile_ir>` |

{func}`compile_document <scenet.pipeline.compile_document>` dispatches on the file
extension, which is what the CLI uses. It is the right choice when the syntax is the
user's decision rather than yours.

## Three renderers

```python
from scenet import compile_scene, render, render_debug, render_strip

panels = compile_scene("""
panels:
  wide:  {cast: {a: {reference: alice}}, camera: {shot: full_shot}}
  close: {over: wide, camera: {shot: close_up}}
""")

# One SVG per panel.
each = {name: render(result.core) for name, result in panels.items()}
assert set(each) == {"wide", "close"}

# The diagnostic overlay: hulls, face zones, anchors, gaze vectors, tail routes.
overlay = render_debug(panels["wide"].core)

# All panels laid out side by side, in reading order.
strip = render_strip([(name, result.core) for name, result in panels.items()])
```

`render` takes `live_text=True` if you want selectable `<text>` elements instead of
glyph outlines. The default emits outlines, which makes the file self-contained — no
font to embed and none to be missing — at the cost of a larger file and text you cannot
select.

## Handling errors

Everything the compiler can object to inherits `ScenetError`:

```python
from scenet import ScenetError, compile_source

try:
    compile_source("cast: {ghost: {reference: nobody}}")
except ScenetError as exc:
    message = str(exc.args[0])

assert "nobody" in message
```

The middle tier of the hierarchy answers the question you usually have, which is whose
fault it is:

```python
from scenet import ScenetError, SolverError, SourceError, compile_source

# A malformed document: the person who wrote the panel needs to fix it.
try:
    compile_source("panel: {size: [0, 100]}")
except SourceError as exc:
    assert "must be positive" in str(exc)

# Both branches are catchable as one thing when you do not care which.
assert issubclass(SourceError, ScenetError)
assert issubclass(SolverError, ScenetError)
```

Every concrete error also keeps the built-in base you would have reached for before this
hierarchy existed — `SourceError` is a `ValueError`, `UnknownPuppetError` is a `KeyError`
— so existing handlers keep working.

See {mod}`scenet.errors` for the full tree.

## Reading the layout instead of drawing it

The interesting information is in `result.core`, not in the SVG. Panel Core is fully
resolved and entirely numeric, but every name you wrote survives:

```python
from scenet import compile_source

result = compile_source("""
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: bob,   at: right_third}
staging: [alice left_of bob]
script:
  - say: {by: alice, text: "Look over there."}
""")

alice = result.core.actor("alice")

# Named attachment points, in panel coordinates.
mouth_x, mouth_y = alice.anchors["mouth"]

# The region no balloon may cover.
face = alice.face_exclusion

# Painter's order: higher values are drawn in front.
assert alice.depth >= 0

# And it serialises to something you can diff, edit, and read back.
document = result.core.to_json()
```

```python
from scenet import PanelCore

restored = PanelCore.from_json(document)
assert restored == result.core
```

That round trip is the point of the tier. A layout can leave the compiler, be adjusted by
hand or by another tool, and come back for emission without ever touching the source.

## Supplying your own characters

Both the puppet library and the font are injectable:

```python
from scenet import PuppetLibrary, compile_source, default_library

library = default_library()
assert library.names() == ("alice", "bob")

# A library built by hand takes the same shape.
just_alice = PuppetLibrary({"alice": library.get("alice")})

result = compile_source("cast: {a: {reference: alice}}", library=just_alice)
assert result.core.actors[0].reference == "alice"
```

See [add your own character](add_your_own_character.md) for the file format.

## What is public

`scenet.__all__` is the contract. Names outside it are internal and may change without a
major version bump:

```python
import scenet

assert "compile_source" in scenet.__all__
assert "render" in scenet.__all__

# Reachable, but not promised. Import from these at your own risk.
import scenet.solve.balloons  # noqa: F401
```

If you find yourself needing something that is not exported, that is worth
[raising as an issue](https://github.com/azias/scenet/issues) — it usually means the
public surface has a gap.

## Determinism, and what it buys you

The same input always produces byte-identical output. No wall-clock time, no unseeded
randomness, no reliance on dictionary iteration order, no absolute paths in the output.

```python
from scenet import compile_source, render

source = "cast: {a: {reference: alice}}"
assert render(compile_source(source).core) == render(compile_source(source).core)
```

That is what makes golden-file testing possible, and it is why a Scenet panel can live in
version control as a source file rather than as a binary blob.
