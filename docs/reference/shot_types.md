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

## Table

| `shot` | Crop landmark | Headroom | Reads as |
|---|---|---|---|
| `long_shot` (alias `wide`) | `feet` | 0.60 | Figure small in its environment |
| `full_shot` | `feet` | 0.05 | Whole body, environment secondary |
| `medium_full` (alias `cowboy`) | `mid_thigh` | 0.08 | Body language, hands visible |
| `medium_shot` | `waist` | 0.10 | The conversational default |
| `medium_close_up` | `chest` | 0.10 | Emphasis on the speaker |
| `close_up` | `shoulders` | 0.08 | Emotion; face dominates |
| `big_close_up` | `chin` | 0.05 | Intensity |
| `extreme_close_up` | `eyes` | 0.00 | Crops through the face deliberately |

Aliases are exact synonyms and resolve to the same values.

The table is **monotonic**: reading down it, the figure never gets smaller. That is what
makes it a ladder, and it is enforced by a test rather than left to inspection --
`long_shot` and `full_shot` crop at the same landmark, so only headroom separates them,
and having those two the wrong way round inverted the ladder at its widest end without
anything noticing.

A limitation worth stating: with no environment to show, `long_shot` and `full_shot` can
differ only by headroom, so the gap between them is necessarily modest. In film the
distinction is mostly about how much of the world is in frame, which this compiler does
not yet model.

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
