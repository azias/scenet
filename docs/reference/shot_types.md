# Shot types (normative)

How the camera's `shot` value determines the scale of a figure in the panel.

## The unit: head-heights

Figures are measured in **head-heights**, the standard figure-drawing unit. An adult is
conventionally about 7.5 heads tall. Every puppet declares `units_per_head` and a set of vertical
**landmarks** measured downward from `head_top`, so the compiler can reason about anatomy without
knowing anything about the artwork.

## Why not "60% of panel height"

A tempting shortcut is to define each shot as a fixed fraction of panel height. It is wrong, because
what a shot type actually names is **where the frame cuts the body** — the waist, the chest, the
shoulders. The fraction of the panel that a figure then occupies falls out of that crop, and differs
between a child and an adult, or between a standing and a seated pose. Encoding the fraction instead
of the crop line bakes in one body and one pose.

So a shot type is defined by two things: a **crop landmark**, and a **headroom** fraction — the empty
space above the head that stops the figure colliding with the top edge.

## Resolution

```
visible_height_native = landmark[crop].y - landmark[head_top].y
available_height      = panel_height * (1 - headroom - footroom)
scale                 = available_height / visible_height_native
```

The scaled figure is then anchored so its crop line meets the bottom of the available area.
`footroom` defaults to `0.0`; a panel may raise it to lift figures off the lower edge.

This anchoring rule is right whenever the crop landmark sits at the **edge** of what the shot
frames -- feet at the bottom of a long shot, chin at the bottom of a big close-up. It goes wrong at
the one rung where the landmark sits **inside** the thing being framed: `extreme_close_up` crops at
`eyes`, and bottom-anchoring the eyes puts the whole eye region below the panel, framing forehead
and eyebrows instead. Headroom cannot fix this -- it shifts the figure down and shrinks it by
exactly the same amount, so the crop line stays pinned to `panel_height * (1 - footroom)`
regardless of headroom. Footroom is the only lever that moves a crop line up from the bottom edge,
which is why `extreme_close_up` is the one shot in the table that needs it despite showing no feet.

## Table

| `shot` | Crop landmark | Headroom | Footroom | Reads as |
|---|---|---|---|---|
| `long_shot` (alias `wide`) | `feet` | 0.14 | 0.06 | Figure small in its environment |
| `full_shot` | `feet` | 0.05 | 0.04 | Whole body, environment secondary |
| `medium_full` | `knees` | 0.08 | — | The three-quarter shot |
| `cowboy` | `mid_thigh` | 0.08 | — | Stance and confrontation |
| `medium_shot` | `waist` | 0.10 | — | The conversational default |
| `medium_close_up` | `chest` | 0.10 | — | Emphasis on the speaker |
| `close_up` | `shoulders` | 0.08 | — | Emotion; face dominates |
| `big_close_up` | `chin` | 0.05 | — | Intensity |
| `extreme_close_up` | `eyes` | 0.00 | 0.45 | Crops through the face deliberately |

**`wide` is an exact synonym for `long_shot`.** The two are used interchangeably in the
literature and the language keeps both because writers reach for both.

**`medium_full` and `cowboy` are not synonyms**, though they were briefly implemented as
though they were. Medium full — the three-quarter shot — cuts at the knees. The cowboy
or American shot cuts at mid-thigh, a framing that comes from 1930s Westerns needing the
holster in shot. Naming two shots and drawing one collapses a rung of the ladder, and
nothing about the output makes that visible.

**Footroom is space left below the crop line.** For the two shots that show feet, that space
reads as ground, and it is not decoration. The crop lands the `feet` *landmark* on the frame
edge, but the drawing continues past it: the ankle joint sits exactly on that landmark and the
shin is drawn as a round-capped stroke, so half its width falls below. Without footroom a long
shot clipped the feet by nine panel units — the one thing a long shot is defined by not doing.
It is also compositionally right on its own: a figure standing on the exact bottom edge reads
as falling out of the panel rather than standing on anything.

`extreme_close_up` uses footroom for a different reason: its crop landmark (`eyes`) is inside
the face rather than at its edge, and footroom is the only lever that moves a crop line up off
the bottom edge — see **Resolution**, above.

The table is **monotonic**: reading down it, the figure never gets smaller. That is what
makes it a ladder, and it is enforced by a test rather than left to inspection —
`long_shot` and `full_shot` crop at the same landmark, so only headroom separates them,
and having those two the wrong way round inverted the ladder at its widest end without
anything noticing.

A limitation worth stating: with no environment to show, `long_shot` and `full_shot` can
differ only by headroom, so the gap between them is necessarily modest. In film the
distinction is mostly about how much of the world is in frame, which this compiler does
not yet model — see [the setting layer](../explanation/status.md).

## Angle

`angle` selects where the eye-line sits vertically within the panel:

| `angle` | Eye-line | Effect |
|---|---|---|
| `low` | Lower third | Figure looms; viewer looks up |
| `eye_level` | Upper third | Neutral (default) |
| `high` | Upper edge | Figure diminished; viewer looks down |

**Current limitation:** angle shifts the eye-line only. It does not yet apply true perspective
projection or foreshortening, so extreme angles will read as vertical repositioning rather than as a
genuine change of viewpoint. This is a known gap, not an oversight.
