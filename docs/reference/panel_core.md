# Panel Core

The resolved intermediate format, between the authored source and emitted SVG.

```
*.panel.yaml   →   IR   →   *.core.json   →   *.svg
authored           validated   resolved         rendered
```

## Why this tier exists

Vega-Lite compiles a high-level grammar into a lower-level one before emitting SVG, rather than
going straight to pixels. The same split pays for itself here, in four ways:

1. **Tests target stable numbers, not markup.** Golden-file tests compare Panel Core JSON, which
   changes only when layout genuinely changes. Diffing SVG text is brittle: reordered attributes or
   a changed path-rounding convention produce enormous diffs that mean nothing.
2. **Layouts can be adjusted by hand.** An artist who wants one balloon two millimetres left can
   edit the Core file, without touching the source or re-running the solver.
3. **One input, several emitters.** SVG, the debug overlay, and later formats all consume the same
   resolved tier.
4. **The high-level grammar stays a strict subset of the low-level one**, so nothing expressible in
   the source is inexpressible after resolution.

## Properties

- **Fully numeric.** Every position, size and scale is an absolute number in panel units. No
  `left_third`, no `medium_shot` — those are resolved away.
- **Still named.** Actors, balloons, captions and anchors keep their source identifiers, so a Core
  file is readable and diffable. This is what separates it from SVG.
- **Deterministic.** Floats are rounded to a fixed precision on emission, so identical input yields
  byte-identical Core output on any platform.

## Shape

```json
{
  "panel": { "width": 1000, "height": 1000 },
  "actors": [
    {
      "id": "alice",
      "reference": "alice",
      "pose": "pointing",
      "transform": { "x": 208.33, "y": 140.0, "scale": 0.72, "mirrored": false },
      "anchors": { "mouth": [263.1, 268.4], "eyes": [259.0, 251.2], "feet": [270.0, 680.0] },
      "face_exclusion": { "cx": 259.0, "cy": 255.0, "r": 46.8 },
      "gaze": [1.0, 0.0],
      "hull": [[180.2, 140.0], [340.5, 140.0], "..."]
    }
  ],
  "balloons": [
    {
      "id": "b0",
      "speaker": "alice",
      "order": 1,
      "box": { "x": 60.0, "y": 55.0, "width": 330.0, "height": 118.0 },
      "lines": ["You forgot your", "umbrella!"],
      "tail": { "kind": "straight", "from": [225.0, 173.0], "to": [263.1, 268.4] }
    }
  ],
  "captions": [
    {
      "id": "c0",
      "order": 0,
      "kind": "locale",
      "box": { "x": 19.0, "y": 19.0, "width": 147.0, "height": 96.0 },
      "lines": ["Midnight.", "The docks."],
      "italic": true,
      "fill": "#ffffff",
      "ink": "#111111"
    }
  ],
  "backdrop": {
    "horizon": 341.0,
    "seed": 3062117294,
    "masses": [
      {
        "id": "m0",
        "kind": "sky",
        "plane": "far",
        "depth": -3,
        "tone": "#4d4d4d",
        "polygon": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 341.0], [0.0, 341.0]]
      }
    ],
    "atmosphere": {
      "time": "night",
      "weather": "rain",
      "tone": "#4d4d4d",
      "veil": { "tone": "#222222", "opacity": 0.3, "frequency": 0.0016, "octaves": 3, "seed": 52939 },
      "streaks": [{ "start": [88.4, 12.0], "end": [99.7, 55.4] }],
      "flecks": [],
      "streak_width": 1.4,
      "fall_tone": "#4d4d4d"
    }
  }
}
```

`lines` is the *resolved* line breaking, not the source string. Wrapping is decided during
compilation using real font metrics, so the emitter never re-measures and never disagrees with the
solver about how wide a balloon needs to be. For a `spoken` caption the quotation marks are part of
those lines for the same reason: marks added afterwards would not fit the box drawn for them.

`italic` is recorded rather than re-derived from `kind`, so the emitter cannot draw a box in a face
the solver did not measure it in. `fill` and `ink` are there for the same reason: a caption's tone
resolves to a value here, and the ink is chosen against it by contrast — so a dark box arrives at the
emitter already lettered in paper, and the emitter is left with no decision about which mark reads.
Both are defaulted to the white and near-black every caption had before tones existed, which is why
adding them needed no `format_version` bump either.

**`order` is one sequence across both lists.** Balloons and captions are placed in a single pass in
script order, so a caption between two lines of dialogue takes the number between theirs and a
balloon list can have gaps in it. A panel with no captions is unaffected, which is why this did not
need a `format_version` bump.

`backdrop` is absent on a panel that says nothing about where it is, which is why adding it did not
need a bump either. Its masses carry **fully resolved numeric polygons and tone values**, the same
discipline as `capsules`, `blobs` and `face_marks`: the emitter is left with no layout decision, and
a backdrop can be read, diffed and hand-adjusted like everything else in this tier. `depth` is the
same painter's order the actors use, so masses and figures sort into one sequence.

`seed` is kept so that a Core document explains itself: two panels with the same masses and
different skylines differ here, and here is where to look.

### Determinism is on this text, and on the SVG text — not on pixels

The atmosphere's `veil` is a set of `feTurbulence` parameters rather than an image, and the filter
is reproducible by specification. What browsers paint from it agrees only approximately. See
[the language reference](language.md#the-contract-is-on-the-svg-text-not-on-pixels), where the
boundary is stated in full; golden-file tests target this tier and the SVG text, never a raster.
