# Write a panel as a comic script

Comic writers already have a format. It is not YAML, it has been in use for decades, and
asking someone to abandon it in order to try a compiler is a poor trade.

So Scenet reads it.

```
PAGE ONE

PANEL 1
@shot: full_shot
CAPTION: Midnight. The docks.
Alice and Bob face each other on a rainy street corner. She is exasperated.

ALICE
You forgot your umbrella!

BOB
I know.

PANEL 2
@shot: medium_close_up
Closer now. Bob will not meet her eye.

BOB (whisper)
I left it on purpose.

ALICE (shouting)
You what?!
```

Save that as `umbrella.script` and compile it exactly like any other document:

```bash
scenet build umbrella.script --strip
```

## The rules

| Line | Means |
|---|---|
| `PANEL 1` | Starts a new panel. Anything before the first one is an error. |
| `@shot: full_shot` | A directive. `@shot` and `@angle` set the camera; anything else sets a top-level panel key. |
| `ALICE` (all caps, alone) | The next lines are dialogue spoken by `ALICE`. |
| `BOB (whisper)` | Same, with a balloon kind. |
| `CAPTION: Midnight.` | A caption box. The text is on the same line. |
| `CAPTION (monologue): ...` | Same, with a caption kind. |
| Anything else | Prose. Preserved, never interpreted. |
| `PAGE ONE` | Ignored. Pages are not modelled yet. |

The one detail that trips people up: **a speaker cue is recognised by the name being all
caps, not the whole line.** `BOB (whisper)` qualifies, because only `BOB` is tested.

`CAPTION` is checked before speaker cues, because as far as the cue pattern is concerned it is a
perfectly good character name. That is also why the text has to be on the same line: a bare
`CAPTION` line is rejected rather than read as a character about to speak.

One thing the YAML syntax can express and this cannot: a `spoken` caption's `by`, naming the
off-panel speaker. Write that panel in YAML, or leave the speaker unnamed — nothing in the drawn
panel depends on it, since a caption has no tail.

## Prose is never interpreted

"Alice and Bob face each other on a rainy street corner" is not parsed, not
natural-language-processed, and does not affect the output in any way. It is kept because
a script is a document people read, and stripping the description would make the file
worse for its primary audience.

If you want the rain, you have to say so in the panel description — and rain is
[not yet a construct in the language](../explanation/status.md).

## Front matter

A script is dialogue and camera direction. It has no way to say who `ALICE` *is*, which
puppet she uses, or where she stands. That comes from a YAML preamble between `---`
fences:

```
---
panel:
  size: [900, 700]
cast:
  ALICE: {reference: alice, pose: pointing,     at: left_third}
  BOB:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}
staging:
  - ALICE left_of BOB
  - ALICE looking_at BOB
  - ALICE ground_shared_with BOB
---

PAGE ONE

PANEL 1
...
```

Everything in the front matter is a default every panel inherits — exactly the same
mechanism as [shared defaults in a sequence](compile_a_sequence.md#shared-defaults).

Note the actor ids are written in caps here, to match the speaker cues. That is a
convention, not a requirement; the ids simply have to agree.

## From Python

```python
from scenet import parse_script

panels = parse_script("""---
cast:
  ALICE: {reference: alice}
---

PANEL 1
@shot: close_up
A quiet room.

ALICE
Is anyone there?

PANEL 2
ALICE (whisper)
Anyone?
""")

# Panels are named by the number in their heading.
assert list(panels) == ["1", "2"]
assert panels["1"].camera.shot.value == "close_up"
assert panels["1"].script[0].text == "Is anyone there?"

# The prose line is preserved in the source and interpreted nowhere.
assert panels["2"].script[0].kind.value == "whisper"
```

Panel names come straight from the heading, so `PANEL 1` becomes `"1"`. The CLI uses
them as filename suffixes: `umbrella.script` compiles to `umbrella.1.svg`,
`umbrella.2.svg`.

{func}`parse_script <scenet.frontends.script_front.parse_script>` gives you IR;
{func}`load_script <scenet.frontends.script_front.load_script>` reads a file; and
{func}`compile_document <scenet.pipeline.compile_document>` dispatches on the `.script`
extension so you do not have to care.

## The front matter is not optional in practice

A script with no cast will not parse at all. Validation is total, so a speaker cue naming
somebody who is not in the cast is an error at parse time rather than a blank balloon
discovered later:

```python
from scenet import ScriptSyntaxError, parse_script

try:
    parse_script("PANEL 1" + chr(10) + "ALICE" + chr(10) + "Hello.")
except ScriptSyntaxError as exc:
    assert "unknown actor" in str(exc)
    assert "ALICE" in str(exc)
```

That is the first error you will hit when adapting an existing script: every speaker cue
needs a matching entry in the front-matter cast.

## Both frontends produce the same IR

This is the point of the whole arrangement. `script_front` computes no coordinates and
knows nothing about geometry; it produces the same
{class}`PanelIR <scenet.ir.PanelIR>` the YAML frontend does, and everything downstream is
unaware that a second syntax exists.

Adding a third syntax means adding a parser and one line in the extension table. Nothing
else changes.
