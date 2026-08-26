# The Scenet language

> **Status:** this is the specification. It is not a report of what is implemented — see
> [implementation status](../explanation/status.md#implementation-status), which is authoritative on
> what actually runs. Panels and sequences compile end to end today, from either frontend; page
> composition and the style layer do not exist yet.

A panel source is a YAML document describing **what is in a panel**, never **where things are drawn**.
Coordinates do not appear anywhere in the language; producing them is the compiler's entire job.

## The layers

A panel description has four authored layers. A fifth — resolution — is computed, and a sixth —
rendering — is emitted.

| Layer | Block | What it says |
|---|---|---|
| Frame | `panel` | Size and margins of the panel |
| Camera | `camera` | How the scene is framed |
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
