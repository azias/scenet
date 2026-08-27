# The Scenet language

> **Status:** this is the specification. It is not a report of what is implemented — see
> [implementation status](../explanation/status.md#implementation-status), which is authoritative on
> what actually runs. Panels and sequences compile end to end today, from either frontend; page
> composition and the style layer do not exist yet.

A panel source is a YAML document describing **what is in a panel**, never **where things are drawn**.
Coordinates do not appear anywhere in the language; producing them is the compiler's entire job.

## The layers

A panel description has five authored layers. A sixth — resolution — is computed, and a seventh —
rendering — is emitted.

| Layer | Block | What it says |
|---|---|---|
| Frame | `panel` | Size and margins of the panel |
| Camera | `camera` | How the scene is framed |
| Setting | `setting` | Where and when it happens |
| Cast and staging | `cast`, `staging` | Who is present, and how they relate |
| Narrative | `script` | What is said, and in what order |

Layers are separable on purpose. Changing `camera.shot` re-frames the same scene without touching
anything else, exactly as transposing a score changes its key without rewriting the melody.

## A complete example

```yaml
panel:
  size: [1000, 1000]

camera:
  shot: medium_shot
  angle: eye_level

setting:
  place: docks
  time: night
  weather: rain

cast:
  alice: {reference: alice, pose: pointing,     at: left_third,  facing: right}
  bob:   {reference: bob,   pose: arms_crossed, at: right_third, facing: left}

staging:
  - alice left_of bob
  - alice looking_at bob
  - alice ground_shared_with bob

script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know."}
```

## `panel`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `size` | `[width, height]` | required | Panel dimensions in panel units |
| `margin` | number | `0` | Inset all content by this much |

Panel units are arbitrary and internally consistent; they become SVG user units.

## `camera`

| Key | Values | Default |
|---|---|---|
| `shot` | see [shot types](shot_types.md) | `medium_shot` |
| `angle` | `low`, `eye_level`, `high` | `eye_level` |

`shot` determines the **scale** of every actor, by naming where the frame cuts the body rather than
what fraction of the panel a figure fills. This is the single most consequential value in a panel.

## `setting`

Where and when the panel happens, drawn as **tonal masses** rather than as geometry.

```yaml
setting:
  place: docks       # a named place, which expands into masses
  horizon: mid       # high | mid | low
  time: night        # dawn | day | dusk | night
  weather: rain      # clear | rain | fog | snow
```

A panel with no `setting` renders exactly as it always did: figures on white.

### Backdrops are never author-drawn

Two reasons, and the first is structural. Crisp architecture needs a vanishing point, and this is
deliberately a flat, orthographic compiler — a tilted camera does not foreshorten anything — so
drawn buildings would fight the compiler's own model. Soft tonal masses have no perspective to get
wrong.

The second is that this is how comics actually establish place:

- **[Notan](https://mitchalbala.com/the-wisdom-of-notan/)**, the Japanese light/dark mass
  principle, which entered Western art teaching through Arthur Wesley Dow's *Composition* (1899):
  place is read from the *arrangement of masses*, not from rendered detail.
- **Layered silhouette depth**: foreground near-black, each receding plane paler.
- **[Aerial perspective](https://en.wikipedia.org/wiki/Aerial_perspective)** supplies the
  parametric rule for free — with distance, value contrast drops toward the atmosphere. Two numbers
  per hour, monotonic in depth. That is notation, not interpretation, which is why it belongs in a
  compiler.

### `masses`

A place is a convenience. Underneath it is a list of masses, which stays authorable whenever you
want control — and which is *exactly* what a place expands into:

```yaml
setting:
  horizon: mid
  masses:
    - {kind: building, plane: far,  spans: full}
    - {kind: plant,    plane: mid,  spans: left}
    - {kind: ground,   plane: near, spans: full}
```

| Key | Values | Default | Meaning |
|---|---|---|---|
| `kind` | see below | required | What the mass is made of, which decides its silhouette |
| `plane` | `foreground`, `near`, `mid`, `far` | `mid` | How far back it sits |
| `spans` | `full`, `left`, `center`, `right` | `full` | How much of the width it covers |

**`kind`** is subsetted from the *supercategories* of
[COCO-Stuff](https://arxiv.org/pdf/1612.03716), the canonical taxonomy of **stuff** — "amorphous
background regions" as opposed to *things* with a well-defined shape. Taken from an existing
vocabulary for the same reason the predicates were taken from Visual Genome. Twelve of them, seven
outdoor and five indoor:

| | Kinds |
|---|---|
| Outdoor | `building` `ground` `plant` `sky` `solid` `structural` `water` |
| Indoor | `ceiling` `floor` `furniture` `wall` `window` |

Deliberately *not* COCO-Stuff's leaf names. Its actual classes are `building-other`, `sky-other`,
`wall-brick`, `water-other`; the `-other` suffix marks the catch-all inside a supercategory, and
`building-other` is not a word anyone should have to type. Its `textile`, `food` and `rawmaterial`
supercategories are left out: drapery and objects, not scene-defining masses.

**`plane`** decides two things at once, and neither is a new mechanism. It maps onto the same
integer painter's order `in_front_of` already uses — the three backdrop planes take negative
depths, and `foreground` takes one above the frontmost actor, so a foreground mass draws over the
cast the way a silhouetted doorway does. And it decides **value**: reading front to back, a mass
never gets darker.

Value comes from the plane and from **nothing else** — not from the kind. That is what keeps the
notan reading literal: masses at one distance read as one mass, and their arrangement is what
carries the place. Two kinds sit off their own plane's rung, and both stay on the ladder rather
than beside it: `sky` is at infinite distance so it always takes the atmosphere's value, and
`window` is a hole showing a more distant plane so it takes the rung one step farther back.

A **nearer plane is also drawn larger**, which is size perspective alongside aerial perspective: a
near hill is not merely darker than a far one, it is bigger.

**`spans`** is an absolute extent, and that is not cosmetic. Any construct that would reintroduce a
left/right *disjunction* has to resolve it before the solver — see
[why ordering must be explicit](#why-ordering-must-be-explicit). A span is an extent rather than a
relation, which is what stops masses becoming an unordered `beside`. `left` and `right` overlap
slightly in the middle so that using both leaves no seam down the centre of the panel.

One authored mass may resolve to **several polygons**: furniture is a few separate blocks, a wall
holds several windows. Joining them into one comb with a zero-height baseline would be a lie about
the shape.

### `place`

The headline surface, because the thing an author wants to write is *where the scene is*, not a
list of shapes.

| Place | Expands into |
|---|---|
| `alley` | sky·far, building·near·left, building·near·right, ground·near, building·foreground·left |
| `desert` | sky·far, solid·far·right, ground·mid, ground·near |
| `docks` | sky·far, building·far·left, water·mid, structural·mid·right, ground·near |
| `field` | sky·far, plant·far, ground·mid, ground·near |
| `forest` | sky·far, plant·far, plant·near·left, plant·near·right, ground·near |
| `mountain` | sky·far, solid·far, solid·mid·left, plant·mid·right, ground·near |
| `office` | wall·far, window·far·center, ceiling·mid, floor·near, furniture·near |
| `room` | wall·far, window·far·right, ceiling·mid, floor·near, furniture·near·left |
| `shore` | sky·far, water·mid, ground·near |
| `street` | sky·far, building·far, building·mid·left, building·mid·right, ground·near |

**The rule that keeps `place:` honest**: a preset expands into a mass list the author could have
written themselves, and is never a second opaque format. A library for convenience, not a parallel
language. The expansion happens in the frontend, exactly as `alice left_of bob` is expanded into a
relation — so by the time anything downstream sees a backdrop, there is one representation of it.

`place` and `masses` are **mutually exclusive**. A place *is* a mass list; writing both asks two
questions at once, and the compiler will not guess which was meant.

**Free prose is deliberately not offered.** `setting: "a rainy street corner at midnight"` needs
language understanding, and the comic-script frontend already refuses to interpret prose on the
grounds that guessing produces panels that are confidently wrong. A named place is the honest
middle: it reads like a description and resolves deterministically. `scenet check` reports an
unmatched name as `unknown-place`, listing the ones that exist.

### `horizon`

One line for the whole panel, which every mass is composed against: masses of the ground sort start
at it and run down, masses that stand in the world rise from it. A **high** horizon sits nearer the
top of the frame, so more ground is in view.

Ground, floor and water all run to the bottom edge, so a near quayside drawn from the horizon would
bury the water behind it. Each starts lower than the plane behind it, and that stack of receding
bands is the depth cue. The exception is the *farthest* one in a panel, which meets the horizon
itself: there is nothing behind it to reveal.

### `time` and `weather`

`time` does not tint a daytime panel. It supplies the two ends of the value ladder — the value of
the foreground and the value of the atmosphere — and the planes are spaced evenly between them in
[OKLab](https://bottosson.github.io/posts/oklab/) lightness, which predicts perceived lightness
well. So `night` is a darker, *narrower* ladder, which is what night does to a drawn scene, and the
ladder stays monotonic in depth at every hour by construction rather than by tuning.

`weather` adds a layer over that. `clouds` and `fog` are first-class stuff in COCO-Stuff, so this
vocabulary did not have to be invented either:

| `weather` | What it does |
|---|---|
| `clear` | Nothing. The panel has no atmosphere layer at all |
| `fog` | A dense, low-frequency noise veil, tinted with the atmosphere itself |
| `rain` | The same veil as cloud — nearer, so darker than the sky — plus slanted streaks |
| `snow` | The same veil, plus flecks |

The veil sits over the backdrop and *under* the cast: fog between the reader and the figures would
be the more literal reading and would bury them. Falling weather goes over everything, because it
**is** between the reader and the panel — which is why it crosses the figures.

Rain flips to ink over a bright sky and to paper over a dark one, as inkers do, because a white
streak over noon is invisible and a black one over midnight is too. Snow never flips: snow is
white, and the overcast veil is what gives it something to read against.


## `cast`

A mapping of actor id to properties. Ids are chosen by the author and referenced everywhere else.

| Key | Type | Meaning |
|---|---|---|
| `reference` | asset name | Which puppet to pull from the library |
| `pose` | pose name | A named joint configuration declared by that puppet |
| `expression` | expression name | A named face declared by that puppet |
| `at` | anchor | Horizontal placement preference |
| `facing` | `left`, `right` | Which way the figure is turned |

`at` accepts `left_third`, `center`, `right_third`, `left_edge`, `right_edge`. It is a
**preference, not a command** — see [conflicts](#when-constraints-conflict).

`expression` is selected by name exactly as `pose` is, because a face is the same kind of thing as a
body: a small closed set of arrangements a character can be in. The shipped puppets declare ten —
`neutral`, `happy`, `laughing`, `coy`, `bored`, `scared`, `sad`, `angry`, `shouting`, `surprise` —
and it defaults to `neutral`. They are a **drawing convention**, the small closed set of faces comics
actually draw, and not a claim about what a person feeling anger looks like. What a face is made of,
and how to give your own puppet one, is in the [asset contract](asset_contract.md#faces).

A character's pupils follow whoever they are `looking_at`. Nothing else about the face depends on the
rest of the panel, and nothing about the face changes the layout: to the solver a face is still one
disc that balloons may not cover.

`reference`, `pose` and `expression` are validated against the puppet library, not just against the
language's own grammar — a misspelled pose is a perfectly good string as far as the grammar is
concerned, so nothing at that level can tell `pointing` from `smirking`. `scenet check` resolves the
library and reports an unmatched name as `unknown-puppet`, `unknown-pose` or `unknown-expression`,
each naming the field and, for `pose` and `expression`, listing the names that puppet does declare.
See [`scenet check`](cli.md#scenet-check).

## `staging`

A list of relations between actors, written `subject predicate object`. This is a scene graph: the
cast are nodes, these are the edges. Predicates come from the spatial subset of the Visual Genome
vocabulary rather than being invented here, so a Scenet scene remains convertible to and from the
scene-graph representations used elsewhere in computer vision.

| Predicate | Effect |
|---|---|
| `left_of`, `right_of` | Fixes horizontal ordering |
| `in_front_of`, `behind` | Fixes draw order and occlusion |
| `looking_at` | Sets the subject's gaze vector toward the object |
| `ground_shared_with` | Places both actors on the same ground line |

### Why ordering must be explicit

`left_of` looks redundant next to `at: left_third`, but it is not. The layout engine is a **linear**
constraint solver, and "A and B must not overlap" is a *disjunction*: A is left of B, **or** B is
left of A. Linear solvers cannot express that choice.

So the language resolves it instead. By the time the solver runs, ordering is already decided — by
`at`, or by an explicit `left_of` — and what reaches the solver is a linear system it can always
solve. This is the reason there is no unordered `beside` predicate, and why any future construct
must resolve its own ordering in the frontend.

## `script`

An ordered list of narrative events, each tagged by a verb. **Order is meaningful**: it is the order
the reader reads them, and it constrains where the boxes may be placed.

There are two verbs. `say` puts a line in a balloon; `caption` puts one in a box.

```yaml
script:
  - caption: {text: "Midnight. The docks.", kind: locale, prefer: top_left}
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know.", kind: whisper}
```

### `say`

| Key | Type | Meaning |
|---|---|---|
| `by` | actor id | Who speaks; the tail points at this actor's mouth |
| `text` | string | The dialogue. Line breaking is computed, not authored |
| `prefer` | zone | A hint about placement, honoured when possible |
| `kind` | `speech`, `thought`, `whisper`, `shout` | Balloon styling |

`text` is never pre-wrapped by the author. Wrapping is computed from real font metrics during
compilation, because a balloon's size determines whether it fits where it is wanted — so the
compiler must decide the line breaks before it can place anything.

### `caption`

A caption is the panel speaking in its own voice. It is what lets a panel say *where* and *when* it
happens without a character having to explain it out loud — which is the thing writers are told not
to do. Comics solved this long before they had reliable backgrounds.

| Key | Type | Meaning |
|---|---|---|
| `text` | string | What the box says. Line breaking is computed, as for dialogue |
| `kind` | `locale`, `monologue`, `spoken`, `editorial` | What the box is doing |
| `tone` | `paper`, `pale`, `ink` | What the box is filled with. Defaults to `paper` |
| `prefer` | zone | Where it would like to sit. Defaults to `top_left` |
| `by` | any name | Who is speaking, for a `spoken` caption only |

The four kinds are the letterers' own vocabulary, taken from Blambot's *Comic Book Grammar &
Tradition* rather than invented — for the same reason the predicates were taken from Visual Genome.
Note that "narration", the obvious guess, is not one of them.

| Kind | What it is | How it is set |
|---|---|---|
| `locale` | Location and time — "Midnight. The docks." | Italic |
| `monologue` | A character's inner voice | Italic |
| `spoken` | Off-panel dialogue | Roman, in quotation marks |
| `editorial` | The voice of the writer or editor | Italic |

`monologue` has largely replaced the thought balloon in modern comics, so a panel has two ways to
render an inner voice: a `monologue` caption and a `thought` balloon. Both are correct. They are
different eras of the same convention, not a duplication.

**Quotation marks are applied by the compiler**, not by you. In a run of consecutive `spoken`
captions, each opens with a quote and only the last one closes — the run is one continuous line of
off-panel speech, and closing every box would read as a series of interruptions. Write the words;
the marks are lettering.

**`by` is the one place an actor id is allowed not to resolve.** Everywhere else, naming somebody
who is not in `cast` is an error. A `spoken` caption's speaker is *off panel* by definition, so
requiring them to be cast would defeat the purpose. It is accepted only on `spoken`; on any other
kind it is a mistake and is rejected.

#### `tone`

A caption box is opaque, so its lettering is never the thing at risk — the text sits on the fill
whatever is behind it. What a tone changes is whether the **box** reads. Against the value ladder
the `setting` block produces, a white box on a noon sky is 1.16:1: legible, and invisible.

| Tone | Fill | Where it comes from | Lettered in |
|---|---|---|---|
| `paper` | `#ffffff` | the paper the panel is printed on — **the default** | ink |
| `pale` | `#adadad` | the `day` row of the value ladder, far plane | ink |
| `ink` | `#090909` | the `day` row of the value ladder, foreground | paper |

Two of the three are rungs of the ladder in `solve/backdrop.py`, taken by index rather than restated
as literals, so lettering and backdrop cannot drift apart as either is tuned. A tone is **fixed, not
a function of the panel's `time`**: a caption's value is a property of the caption, and letting it
follow the hour would make the table below a function of the panel.

`ink` produces what letterers call reversed type. **The inversion is decided by the compiler**, by
contrast, and travels in Panel Core as a resolved value — the same rule and the same reason as
falling rain, which is inked over a bright sky and papered over a dark one.

Two floors, and only the first is a rule every tone must meet:

- **Lettering, 4.5:1.** A caption's text against its own fill, WCAG AA for body text. This is the
  contrast a reader actually gets, and every tone in the palette clears it with room — 18.9:1,
  8.4:1 and 19.9:1 respectively.
- **Separation, 3:1.** The box against the plane behind it. *No tone is required to clear this on
  every rung*, and the default does not: white on a noon sky is the case that motivated the feature.
  What the palette owes you is an escape from every background the compiler can produce — at least
  one tone above 3:1 for every rung of every hour — and that is what the test suite checks.

There is no free-form `fill:`, and no yellow. An open colour field would be this language's one open
vocabulary and would let you produce an unreadable box; the classic yellow `locale` caption would be
the first non-neutral value in the codebase, and there is no colour policy to put it under yet.

**Text is set flush left.** This is a *convention*, not a rule the way reading order is: the
lettering references describe left alignment as the norm while calling it a house preference. It is
the default because it is what letterers do, and it is recorded here as a choice rather than a law —
unlike `shot_types.md`, which is normative. Balloons, by contrast, centre their text.

Captions are placed by the same machinery as balloons — the same face avoidance, the same silhouette
occlusion cost, the same hard reading-order rule — because the placement principles for floating
text are the ones the balloon solver already implements. What differs is the pull toward the frame:
a balloon mildly dislikes hugging the panel edge, and a caption is looking for exactly that corner.

### Reading order is enforced, not suggested

Balloons and captions are placed in script order, in one pass, and a box may never sit
above-and-left of the one before it. Violating this is not a cosmetic flaw: it makes the panel read
in the wrong order, which is a correctness bug in a comic. The constraint is therefore hard, and a
panel whose boxes cannot be placed without breaking it is rejected rather than rendered wrongly.

Captions take their turn in that sequence rather than being placed first as a layer. A caption
written between two lines of dialogue is read between them; one written last is read last.

## When constraints conflict

Placement values are preferences of differing strength, and the solver resolves conflicts by
priority rather than by failing:

| Strength | Examples |
|---|---|
| **Required** | Actors stay inside the panel; balloons never cover a face; reading order holds |
| **Strong** | Declared `left_of` / `right_of` ordering |
| **Weak** | `at:` anchors, `prefer:` balloon hints |

So two actors both asked to stand at `center` will be pushed apart rather than overlapping: the
required non-overlap wins and the weak anchors yield. This is why `at` is documented as a
preference. If you need a guarantee, express it as a relation in `staging`.

## Determinism

The same source always compiles to byte-identical output. No wall-clock time, no unseeded
randomness, no dependence on mapping iteration order. This is what makes a panel description a
durable artifact rather than a prompt: it will render the same in five years as it does today.

Backdrop silhouettes are generated, so they are seeded — from the declared setting and the panel
size, through a content hash. Never a clock, and never Python's `hash()`, which is salted per
process and would agree with itself all day while disagreeing with tomorrow's build.

### The contract is on the SVG text, not on pixels

Worth stating explicitly, because it is exactly the kind of assumption that rots silently.

> **The determinism contract is on the emitted SVG text, which stays byte-identical. It has never
> been on pixels.**

The `feTurbulence` filter that draws fog and cloud is reproducible *by definition* — SVG has Perlin
noise built in, the specification includes reference code, and the `seed` is fixed by the compiler
— so the emitted document is identical every time. In practice browsers agree only
[approximately](https://tympanus.net/codrops/2019/02/19/svg-filter-effects-creating-texture-with-feturbulence/)
on what to paint from it. That is fine, and it was already true of every glyph outline and every
antialiased edge in the file.

Golden-file tests therefore target Panel Core and SVG **text**, never a raster. If a raster check is
ever wanted, [resvg](https://github.com/linebender/resvg) is the candidate: it supports
`feTurbulence`, aims at the whole specification rather than the common cases, and ships around 1600
SVG-to-PNG regression tests — which matters because the W3C SVG test suite was abandoned long ago,
making resvg's the practical conformance reference.
