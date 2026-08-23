# Work out why a panel looks wrong

A panel that compiles but looks wrong is the common case, and the SVG is the worst place
to investigate it. Three tools, roughly in the order you should reach for them.

## 1. Read the notes

The compiler tells you when it did something you did not ask for:

```python
from scenet import compile_source

result = compile_source("""
panel: {size: [600, 400]}
camera: {shot: close_up}
cast:
  alice: {reference: alice}
  bob:   {reference: bob}
staging: [alice left_of bob]
""")

for note in result.notes:
    assert isinstance(note, str)

assert any("camera retreated" in note for note in result.notes)
```

Two things get reported:

- **`camera retreated to N% of the requested framing`** — the cast would not fit across
  the panel at the shot you asked for, so the camera stepped back. Widen the panel, use a
  looser shot, or accept it.
- **`balloon bN needed a curved tail to clear a face`** — a straight tail would have gone
  through somebody's head. Usually a sign the panel is crowded enough to be worth a second
  look.

On the command line these print as `note:` lines. `--quiet` suppresses them, which you
should not normally want.

## 2. Look at the debug overlay

```bash
scenet build duel.panel.yaml --debug
```

That writes `duel.debug.svg`, drawing what the solver was actually working against:

| Overlay | What it shows |
|---|---|
| Silhouette hulls | The convex outline used for the balloon occlusion cost |
| Face exclusion discs | The regions no balloon may overlap, at all |
| Named anchors | `mouth`, `eyes`, and anything else the puppet declares |
| Gaze vectors | Where each character is looking, and how far that reaches |
| Tail routes | Including the control point, when a tail had to bend |

Most "why is the balloon *there*?" questions answer themselves the moment you see the face
discs and the gaze vectors drawn.

From Python it is {func}`render_debug <scenet.emit.debug_svg.render_debug>`:

```python
from scenet import compile_source, render_debug

result = compile_source("cast: {a: {reference: alice}}")
overlay = render_debug(result.core)
assert overlay.lstrip().startswith("<?xml")
```

## 3. Read the Panel Core

```bash
scenet build duel.panel.yaml --core
```

`duel.core.json` is every decision the compiler made, in a format you can read and diff.
When a layout changes unexpectedly between two versions of your source, diffing two Core
documents tells you exactly what moved. Diffing two SVGs does not — a reordered attribute
or a different path-rounding produces an enormous diff that means nothing.

```python
from scenet import compile_source

result = compile_source("""
cast:
  alice: {reference: alice, at: left_third}
script:
  - say: {by: alice, text: "Why am I here?"}
""")

alice = result.core.actor("alice")
balloon = result.core.balloons[0]

# Where the figure landed, and at what scale.
assert alice.transform.scale > 0

# Where the balloon landed, and where its tail attaches.
assert balloon.box.width > 0
assert balloon.tail.start != balloon.tail.end

# Whether the tail had to bend.
assert balloon.tail.is_curved in (True, False)
```

## Common causes

**"The balloon is nowhere near the speaker."** Check the face discs in the overlay. Every
position near the mouth was probably illegal — covering a face is a hard rule, not a cost
— so the search fell back to a panel corner, which is an ordinary comics solution and
looks deliberate on the page.

**"My `at:` anchor was ignored."** Anchors are *weak*. Non-overlap and declared ordering
are required and will override them without comment. Two actors both asking for `center`
get pushed apart around it.

**"My `prefer:` zone was ignored."** `prefer` is the weakest term in the whole system. It
loses to occlusion, to gaze blocking, and to reading order.

**"The figures are smaller than I asked for."** The camera retreated. Check `result.notes`
— it says so explicitly.

**"A figure is half off the edge."** Panel bounds are *strong*, not required. Letting a
figure bleed past the edge is ordinary comics practice and much better than refusing to
compile a crowded panel. Widen the panel or loosen the shot.

**"Reading order looks wrong."** It cannot be, in the sense the compiler means: a balloon
is never allowed above *and* left of one that precedes it. If it reads wrong anyway, the
script order is probably not what you intended — script order *is* reading order.

## When it will not compile at all

Two error types, and which one you get tells you where to look:

```python
from scenet import SolverError, SourceError, compile_source

# SourceError: the document is wrong. Fix the panel source.
try:
    compile_source("staging: [alice left_of bob]")
except SourceError as exc:
    assert "unknown actor" in str(exc)
```

`SolverError` is the other branch — the document is valid but no layout satisfies it. In
practice that means either a genuinely contradictory ordering, or far too much dialogue
for the panel size. Widen the panel, shorten the line, or split it across two panels.
