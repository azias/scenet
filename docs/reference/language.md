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
| `at` | anchor | Horizontal placement preference |
| `facing` | `left`, `right` | Which way the figure is turned |

`at` accepts `left_third`, `center`, `right_third`, `left_edge`, `right_edge`. It is a
**preference, not a command** — see [conflicts](#when-constraints-conflict).

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

An ordered list of narrative events. **Order is meaningful**: it is the order the reader reads them,
and it constrains where balloons may be placed.

```yaml
script:
  - say: {by: alice, text: "You forgot your umbrella!", prefer: top_left}
  - say: {by: bob,   text: "I know.", kind: whisper}
```

| Key | Type | Meaning |
|---|---|---|
| `by` | actor id | Who speaks; the tail points at this actor's mouth |
| `text` | string | The dialogue. Line breaking is computed, not authored |
| `prefer` | anchor | A hint about placement, honoured when possible |
| `kind` | `speech`, `thought`, `whisper`, `shout` | Balloon styling |

`text` is never pre-wrapped by the author. Wrapping is computed from real font metrics during
compilation, because a balloon's size determines whether it fits where it is wanted — so the
compiler must decide the line breaks before it can place anything.

### Reading order is enforced, not suggested

Balloons are placed in script order, and a balloon may never sit above-and-left of the one before
it. Violating this is not a cosmetic flaw: it makes the panel read in the wrong order, which is a
correctness bug in a comic. The constraint is therefore hard, and a panel whose balloons cannot be
placed without breaking it is rejected rather than rendered wrongly.

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
