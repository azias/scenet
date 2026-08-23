# Your first panel

By the end of this you will have compiled a two-character panel with dialogue, looked at
what the compiler decided for you, and understood why it decided it.

Allow about fifteen minutes.

## Install

Scenet needs Python 3.12 or newer.

```bash
pip install scenet
```

Or, if you use [uv](https://docs.astral.sh/uv/):

```bash
uv add scenet
```

Check it worked:

```bash
scenet --version
```

## The smallest thing that compiles

A panel needs a cast. Nothing else is required — everything has a default.

Create `hello.panel.yaml`:

```yaml
cast:
  alice: {reference: alice}
```

And compile it:

```bash
scenet build hello.panel.yaml
```

That writes `hello.svg`. Open it: one figure, centred, framed as a medium shot in a
1000×1000 panel. You asked for none of that, and got all of it, because every key in the
language has a default.

Here is the same thing from Python:

```python
from scenet import compile_source, render

result = compile_source("cast: {alice: {reference: alice}}")
core = render(result.core)

assert result.core.width == 1000.0
assert result.core.height == 1000.0
assert len(result.core.actors) == 1
```

Two names carry almost everything you will use: {func}`compile_source
<scenet.pipeline.compile_source>` turns text into a compiled panel, and {func}`render
<scenet.emit.svg.render>` turns the compiled panel into SVG.

## `alice` twice means two different things

Look at that line again:

```yaml
cast:
  alice: {reference: alice}
```

The key `alice` is an **actor id** — the name you use to refer to this person elsewhere
in *this* panel. The `reference: alice` is a **puppet name** — which character from the
library gets drawn.

They happen to match here, which is convenient and also slightly misleading. They are
independent, and that is what lets one puppet play two parts:

```python
from scenet import compile_source

result = compile_source("""
cast:
  guard_left:  {reference: bob, pose: arms_crossed}
  guard_right: {reference: bob, pose: standing_neutral, facing: left}
staging:
  - guard_left left_of guard_right
""")

assert len(result.core.actors) == 2
assert {actor.reference for actor in result.core.actors} == {"bob"}
```

Two actors, one puppet, and the panel can talk about them separately.

## Adding the second character

```yaml
panel:
  size: [1000, 800]

camera:
  shot: medium_shot

cast:
  alice: {reference: alice, pose: pointing,     at: left_third}
  bob:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}

staging:
  - alice left_of bob
  - alice looking_at bob
  - alice ground_shared_with bob
```

Three new ideas, one per staging line.

`alice left_of bob` is an **ordering constraint**, and it is *required*: the solver will
break your `at:` preferences before it breaks this. That distinction matters more than it
looks — see [when constraints conflict](#when-things-conflict) below.

`alice looking_at bob` gives Alice a **gaze vector** pointing at Bob. It changes no
position at all. What it does is make the space in front of her eyes expensive for a
balloon to occupy, because a balloon parked in a character's line of sight reads as an
obstruction.

`alice ground_shared_with bob` puts them on the same **ground line**. Note carefully: it
aligns their *feet*, not their heads. Alice and Bob are deliberately different heights, so
if this aligned heads they would appear to be standing on a staircase.

Let us check that the compiler actually did that:

```python
from scenet import compile_source

result = compile_source("""
panel: {size: [1000, 800]}
camera: {shot: medium_shot}
cast:
  alice: {reference: alice, pose: pointing,     at: left_third}
  bob:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}
staging:
  - alice left_of bob
  - alice ground_shared_with bob
""")

alice = result.core.actor("alice")
bob = result.core.actor("bob")

# Ordering was honoured.
assert alice.transform.x < bob.transform.x

# `facing: left` mirrored Bob, and left Alice alone.
assert bob.transform.mirrored is True
assert alice.transform.mirrored is False

# One camera, one scale. Everybody is drawn at the same size.
assert alice.transform.scale == bob.transform.scale
```

That last assertion is worth pausing on. There is **one camera per panel**, and every
actor is drawn at the scale it implies. The alternative — scaling each actor to its own
crop landmark — would make everyone exactly the same apparent height and erase the body
differences a comic uses to tell characters apart.

## Dialogue

```yaml
script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know."}
```

Two things to notice.

**You do not break the lines.** Write the whole line as one string. Where it breaks is
decided during compilation, measured against the real metrics of the real font, and
scored on how close the resulting block comes to the shape a letterer would choose.

**Script order is reading order,** and reading order is a hard constraint rather than a
preference. A balloon may never sit above *and* left of one that precedes it. Reorder
these two lines and you reorder the panel.

```python
from scenet import compile_source

result = compile_source("""
panel: {size: [1000, 800]}
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: bob,   at: right_third, facing: left}
staging: [alice left_of bob]
script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know."}
""")

first, second = result.core.balloons

assert first.speaker == "alice"
assert second.speaker == "bob"

# "I know." is short enough to stay on one line. The line breaker will not split a
# phrase that fits, even where splitting scores marginally better on aspect ratio,
# because no letterer would.
assert second.lines == ("I know.",)

# The longer line was broken somewhere sensible, and every word survived.
assert " ".join(first.lines) == "You forgot your umbrella!"
```

## Looking at what it decided

The SVG is the output, but it is not where the interesting information lives. Between
your source and the picture sits **Panel Core** — fully resolved, entirely numeric, and
still carrying every name you wrote.

```bash
scenet build duel.panel.yaml --core --debug
```

`--core` writes `duel.core.json`: every coordinate the compiler chose, in a format you can
read, diff and edit. `--debug` writes `duel.debug.svg`: an overlay drawing the geometry
the solver was working against — silhouette hulls, face exclusion zones, named anchors,
gaze vectors and tail routes.

If a panel comes out looking wrong, the debug overlay is almost always where the reason
becomes obvious.

From Python, the same thing is one attribute:

```python
from scenet import compile_source

result = compile_source("""
cast:
  alice: {reference: alice}
script:
  - say: {by: alice, text: "Where does this balloon go?"}
""")

balloon = result.core.balloons[0]

# Where it ended up, and where its tail points.
assert balloon.box.width > 0
assert balloon.tail.start != balloon.tail.end

# A balloon never covers a face. That is a hard rule, not a preference.
face = result.core.actor("alice").face_exclusion
assert not balloon.box.as_bbox().intersects_circle(face.as_circle())
```

## When things conflict

Ask for something impossible and the compiler will not refuse — it will loosen the
weakest thing it can and tell you what it did.

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

assert any("camera retreated" in note for note in result.notes)
```

Two people cannot both fit across a small panel at a close-up. A real camera operator
would step backwards, so that is what happens: everybody gets smaller, more of the body
comes into view, and the requested shot turns out to have been an *upper bound on
tightness* rather than a promise.

The important part is the last line. It is reported in
{attr}`result.notes <scenet.pipeline.CompileResult.notes>` rather than logged and
forgotten, because a camera that retreats silently leaves you with a panel that is quietly
not the shot you asked for — something you would eventually notice and have no way to
explain.

The priority order, in full:

| Priority | What | Example |
|---|---|---|
| Required | Actors never overlap; declared order holds | `alice left_of bob` |
| Required | Balloons never cover a face; reading order holds | |
| Strong | Actors stay inside the panel | |
| Weak | Actors sit on their requested anchor | `at: left_third` |
| Weakest | Balloons sit in their preferred zone | `prefer: top_left` |

Panel bounds are *strong* rather than required on purpose. Letting a figure bleed past the
panel edge is ordinary comics practice, and much better than refusing to compile a crowded
panel.

## Where next

- [How-to guides](../howto/index) for specific jobs — sequences, comic scripts, your own
  characters.
- [The language reference](../reference/language) for every construct.
- [Shot types](../reference/shot_types), which is normative, if you want to know exactly
  what `medium_shot` means.
- [Explanation](../explanation/index) for why any of this is shaped the way it is.
