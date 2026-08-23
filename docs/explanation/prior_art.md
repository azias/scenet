# Prior art

What already exists, what was taken from it, and — equally important — what was examined and
deliberately not used. Recorded so later contributors need not repeat the search, and so design
decisions can be argued with rather than guessed at.

Three verdicts: **load-bearing** (it changed the code), **future** (real, but not yet),
**not reusable** (examined and rejected, with the reason).

## Load-bearing

### Comic Chat — Kurlander, Skelly & Salesin, SIGGRAPH '96

[Paper](https://grail.cs.washington.edu/wp-content/uploads/2015/08/comics.pdf) ·
[source, MIT, released July 2026](https://github.com/microsoft/comic-chat)

The canonical solution to this exact problem, and largely forgotten. Comic Chat rendered live IRC
conversations as comic strips, automatically choosing which characters appeared in each panel, where
they stood, which way they faced, the camera zoom, the balloon shapes, and — critically — balloon
placement obeying reading order.

Taken: the overall decomposition, the insight that reading order is a hard constraint rather than a
preference, and the practice of opening a sequence with a wider establishing shot.

**Nothing is vendored** — not code, not artwork. See
[THIRD_PARTY_NOTICES](https://github.com/azias/scenet/blob/main/THIRD_PARTY_NOTICES.md) for why.

### Vega-Lite

[Paper](https://idl.cs.washington.edu/files/2017-VegaLite-InfoVis.pdf) ·
[site](https://vega.github.io/vega-lite/)

The closest structural precedent that exists: a declarative high-level grammar compiling to a
*lower-level grammar*, which then emits SVG — with the compiler deriving components (scales, axes,
legends) by rule rather than making the author specify them.

Taken: the two-tier pipeline. Source compiles to [Panel Core](../reference/panel_core.md), which is
then emitted. Scenet's automatically derived components are figure scale, balloon geometry and tail
routing. Leland Wilkinson's *Grammar of Graphics* is the ancestor idea; Vega-Lite is the proof it
survives contact with a real implementation.

### Semantic scene graphs — Visual Genome

[Visual Genome](https://visualgenome.org/)

Modelling an image as nodes (objects with attributes) and directed edges (relations) is the standard
machine-readable representation of image *content* rather than image *pixels*.

Taken: this is the IR. The [`staging`](../reference/language.md#staging) block is literally a set of
relation triples, and its predicate vocabulary is anchored on Visual Genome's spatial subset rather
than invented, so scenes stay convertible in both directions.

### OpenUSD composition arcs

[OpenUSD](https://openusd.org/release/intro.html)

Pixar's scene description format solves a problem comics share: describing many related scenes that
mostly repeat, without duplicating them.

Taken as *semantics*, not as a dependency — three arcs by name. `reference` (a panel pulls a
character from a library), `variantSet` (switchable alternatives; poses now, style later), and
`over`, sparse override, where a panel names a parent and changes only what differs. That last one
matters enormously for comics, where consecutive panels in a scene share nearly all their staging.

`usd-core` is pip-installable and was considered seriously. Rejected: it imposes a 3D stage model,
`Prim`/`Xform` hierarchies and a substantial learning curve on a fundamentally 2D problem. The ideas
transfer; the library does not.

### Visual semiotics — Kress & van Leeuwen, *Reading Images*

Mostly concerned with meaning and interpretation, which is out of scope. But one part is objective
and immediately usable: **vectors** — the lines of sight and action along which a viewer's eye
travels.

Taken: gaze is a real geometric quantity, so it becomes a term in the balloon cost function.
Balloons are drawn toward the gaze direction and penalised for blocking it. The left-to-right
"given to new" reading also serves as a tiebreaker when a script does not specify staging order. The
rest — ideal/real verticality, modality — belongs to the deferred style layer.

### Cassowary constraint solving

Used via [`kiwisolver`](https://kiwisolver.readthedocs.io/). The value is **not** the arithmetic:
scale and rule-of-thirds placement are trivial to compute directly. The value is the
required/strong/weak **priority system**, which resolves conflicts between competing placement
preferences automatically. The alternative is an ever-growing cascade of hand-written special cases.

### Comic script format and Fountain

[Fountain](https://fountain.io/) · [screenplay-tools](https://github.com/wildwinter/screenplay-tools)

Checked and confirmed: Fountain has **no** native panel, caption or SFX support, and there is no
standardised comic script format at all. But the informal industry convention (`PAGE ONE`,
`PANEL 1`, description, `CAPTION`, character cue, `SFX`) is stable across publishers, and
`screenplay-tools` provides a working tokenizer to extend.

Planned as the human-facing frontend in phase 5 — better than inventing a syntax, because writers
already write this one.

## Future

### Shape grammars (Stiny & Gips) and L-systems

Rule-rewriting systems that generate *form*. Useless for panel composition, which is a placement
problem rather than a generative one. Genuinely right for **procedural backgrounds and props** — a
street corner, a room interior, foliage — which is a real future module.

## Examined and not reusable

| Source | Why not |
|---|---|
| **[CBML](https://dcl.luddy.indiana.edu/cbml/)** (TEI) | A scholarly XML vocabulary for *encoding existing* comics for analysis, not for generating them. It has no spatial semantics whatsoever. Its terminology is worth borrowing; its schema is not. |
| **Graphviz / DOT** | Useful only as a debug dump of the scene graph. Graph layout optimises for edge crossings and hierarchy, which has nothing to do with pictorial composition. A dead end as a layout engine. |
| **POV-Ray SDL** | A CSG raytracer scene language. Historically interesting as an early declarative scene description, but nothing transfers. |
| **D3.js** | A DOM data-binding library rather than a layout engine, and this project is Python. Its underlying idea is already covered by Vega-Lite. |
| **A-star pathfinding for balloon tails** | Frequently suggested, and wrong. A tail is a short tapered stroke from balloon rim to mouth; grid-based A-star produces jagged paths that look nothing like drawn tails. A straight tail with a collision test, bending to a single-control-point Bézier only when obstructed, is both simpler and better. |
