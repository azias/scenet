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
preference, the practice of opening a sequence with a wider establishing shot, and — added later —
**the expression vocabulary**. Comic Chat's emotion wheel carried `laughing`, `happy`, `coy`,
`bored`, `scared`, `sad`, `angry` and `shouting`, with `neutral` at its centre. Scenet ships those
nine plus `surprise`.

That set was preferred to Ekman's six deliberately. It comes from a system that actually rendered
faces for live conversations rather than from a psychology of emotion, and it shows: `coy` and
`bored` are cartoonists' categories, and no taxonomy of felt emotion would produce them. Which is
exactly the framing the literature demands — see Barrett below.

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

### MPEG-4 FBA feature *groups* — and only the groups

[Overview (PDF)](https://visagetechnologies.com/uploads/2012/08/MPEG-4FBAOverview.pdf)

The ISO standard defines 66 facial animation parameters over dozens of feature points. That is a
measurement, not a notation, and adopting it wholesale would put more machinery in the language than
a drawn face has detail.

Taken: the **grouping** — brow, eye, iris, nose, mouth, jaw — which is about six named features and
is the right size for this. `docs/reference/asset_contract.md` records the mapping from Scenet's
feature names to MediaPipe landmark indices, which is what would make a real face convertible into a
Scenet expression later without importing 478 points now.

Not taken: the jaw group. The head is a circle that does not deform, so a jaw would have no geometry
to move.

### Barrett et al. 2019 — why the expression names are not an emotion claim

["Emotional Expressions Reconsidered: Challenges to Inferring Emotion From Human Facial
Movements"](https://pmc.ncbi.nlm.nih.gov/articles/PMC6640856/), *Psychological Science in the Public
Interest*.

Recorded here so that a claim this project made in an early draft is never reintroduced. The first
proposal justified Ekman's six as "cross-culturally documented, universal". **That justification does
not survive the literature.** Barrett and colleagues conclude that a specific emotion cannot reliably
be read off a face, and land a methodological hit besides: Ekman's agreement rates came from a forced
choice among six supplied words, and participants given no word list label the "correct" emotion less
than half the time.

It does not sink the feature, because Scenet runs the other way. Barrett's critique is about
*inferring* emotion from a real face. Scenet *synthesises* a drawn face from a declared name, and
comic faces are conventional signs rather than photographs of felt emotion. So the honest framing,
which is also the stronger one for this project:

> These names are a **drawing convention** — the small closed set of faces comics actually draw. They
> are not a claim that a person feeling anger produces this face.

That keeps the notation at the objectifiable level and leaves interpretation to another layer, which
is the thesis of the whole compiler.

### Lettering convention — Blambot, and Balloon Tales

[Comic Book Grammar & Tradition](https://blambot.com/pages/comic-book-grammar-tradition) ·
[Floating text and captions](https://balloontales.com/floating-text-captions/)

Blambot is a letterer's reference rather than an academic one, which is exactly why it is
load-bearing here: it records what the craft actually does. Two things were taken from it directly.

The **caption vocabulary** is theirs — `locale`, `monologue`, `spoken`, `editorial` — including the
finding that "narration", the obvious guess and this project's first proposal, is not one of them.
Same reasoning as taking the predicates from Visual Genome: a vocabulary practitioners already share
beats one invented here.

The **quotation rule for a run of spoken captions** — an opening mark on each, a closing mark only
on the last — is theirs too. It is objective, which makes it testable, which is why it is enforced
by the compiler rather than left to the author.

Balloon Tales supplies the placement principles for floating text: keep off the important figures,
preserve the space the art establishes, keep the reading order flowing. All three were already
implemented for balloons, which is the argument for captions going through the same solver rather
than a parallel one.

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
| **[MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)** | 478 3-D landmarks. A *detection output*, not a notation: 478 points is a measurement of a face, and a drawn face has nothing like that much detail to place. Its landmark indices are useful as a **mapping target**, and are recorded as one in the asset contract. |
| **ARKit / MediaPipe blendshapes** | 52 continuous coefficients that "loosely correspond to FACS Action Units". Continuous blending is the wrong model for comics, which use a small set of conventionalised glyphs rather than interpolations between them. |
| **[FACS](https://www.sciencedirect.com/topics/computer-science/facial-action-coding-system)** | Codes anatomical muscle actions for *observation*, is continuous, and is documented as weak on the lower face. Wrong direction, wrong granularity. |
| **A-star pathfinding for balloon tails** | Frequently suggested, and wrong. A tail is a short tapered stroke from balloon rim to mouth; grid-based A-star produces jagged paths that look nothing like drawn tails. A straight tail with a collision test, bending to a single-control-point Bézier only when obstructed, is both simpler and better. |
