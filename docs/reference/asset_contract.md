# Asset contract

What a character must declare for the compiler to place it.

## The central rule

**The solver never sees artwork.** It sees only a geometric contract. Everything the layout engine
needs — how tall the figure is, where its mouth is, which region a balloon must not cover, which way
it is looking — is declared as data. Rendering consumes the same contract afterwards.

This is what keeps rendering swappable: the same panel can be emitted as debug wireframes, as vector
puppets, or eventually as hand-drawn artwork, with byte-identical layout in every case.

## Skeletal puppets

A character is a skeleton plus parametric limbs, not a picture. A **pose** is a named set of joint
angles, so `pointing` is data rather than a drawing — which avoids the combinatorial explosion of
one image per pose per expression per facing direction.

```yaml
units_per_head: 100

landmarks:          # vertical offsets from head_top -- the crop lines
  head_top: 0
  eyes: 40
  chin: 100
  shoulders: 130
  chest: 200
  waist: 330
  mid_thigh: 470
  knees: 560
  feet: 750         # 7.5 heads, standard adult proportion

joints: {root, pelvis, spine, neck, head, shoulder_l, elbow_l, wrist_l, ...}

parts:
  - {bone: upper_arm_l, shape: capsule, length: 90, width: 24}

face:
  radius: 65                # balloons may never overlap this circle
  features:                 # what is drawn inside it
    brow_l: {offset: [-20, -27], size: 12}
    eye_l:  {offset: [-20, -12], size: 9}
    mouth:  {offset: [0, 25],    size: 16}

gaze:
  origin: eyes
  default_dir: facing

poses:
  standing_neutral: {...joint angles}
  arms_crossed: {...}
  pointing: {...}

expressions:
  neutral: {}
  angry: {brow: angled_in, eyes: narrowed, mouth: frown}
```

## Faces

An **expression** is to features what a pose is to joints: a named record the panel selects by name.
A face *deforms* rather than rotating about bones, which is why an expression is a set of states and
not a set of angles — a nose joint would swing a nose.

### Feature points

`face.features` declares where things are. Each entry is an
[`AnchorSpec`](#skeletal-puppets)-shaped `{joint, offset, size}`, resolved through exactly the same
forward kinematics, mirroring and scaling that anchors get.

They live under `face` rather than in `anchors` deliberately. **Anchors are how the solver addresses
anatomy** — a balloon tail terminates at `mouth` and the solver never learns how a head is drawn.
Features are artwork. Putting drawing landmarks into the one namespace that is supposed to be free of
them would erode the rule the whole tier exists to enforce.

| Feature | `size` means |
|---|---|
| `brow_l`, `brow_r` | Half-width of the eyebrow |
| `eye_l`, `eye_r` | Radius of the eye |
| `nose` | Length of the nose |
| `mouth` | Half-width of the mouth |

Features are optional, individually — a stylised character genuinely may have no eyebrows — but the
paired ones must come in pairs, because a face with one eyebrow is a typo far more often than it is a
character.

**Pupils are derived, not declared.** They are offset inside the eye along the direction of whatever
the character is `looking_at`, so authoring them would mean authoring something the compiler already
knows.

### The names come from MPEG-4's groups, not its point set

The feature names follow the **groups** of the MPEG-4 FBA facial definition parameters. The standard
itself defines 66 displacements over dozens of points, which is a measurement rather than a notation;
the grouping is the reusable part, and it lands at about the right size for a drawn face. The mapping
below is what buys convertibility later without importing 478 landmarks into the language now:

| Scenet feature | MPEG-4 FDP group | MediaPipe Face Mesh landmarks (approx.) |
|---|---|---|
| `brow_l` / `brow_r` | 4 (eyebrows) | 70, 63, 105 / 300, 293, 334 |
| `eye_l` / `eye_r` | 3 (eyes) | 33, 133, 159, 145 / 263, 362, 386, 374 |
| pupil (derived) | 3 (iris) | 468 / 473 |
| `nose` | 9 (nose) | 1, 2, 98, 327 |
| `mouth` | 8 (lips) | 61, 291, 13, 14 |

There is **no jaw group**, which MPEG-4 has. The head is a circle that does not deform, so a jaw
would have no geometry to move. Saying so is better than leaving a group silently missing.

### The expression vocabulary is a drawing convention

```yaml
expressions:
  neutral:  {}
  happy:    {mouth: smile}
  angry:    {brow: angled_in, eyes: narrowed, mouth: frown}
```

Each state comes from a closed set — `brow` from `neutral | raised | lowered | angled_in |
angled_out`, `eyes` from `open | wide | narrowed | half | closed`, `mouth` from `neutral | flat |
smile | grin | frown | open | small`. A state on the wrong feature is an error, not a line quietly
ignored.

The ten names the shipped puppets declare are **Comic Chat's emotion wheel plus `surprise`**:
`neutral`, `happy`, `laughing`, `coy`, `bored`, `scared`, `sad`, `angry`, `shouting`, `surprise`.

They are a **drawing convention** — the small closed set of faces comics actually draw. They are
not a claim that a person feeling anger produces this face, and the docs must never make one; see
[prior art](../explanation/prior_art.md) for the literature that rules it out.

### Level of detail

Below a threshold face radius, no features are drawn at all. At a wide framing a head is a couple of
dozen panel units across, and five features inside it stop being a face and become a smudge — which
is why a cartoonist leaves them out too. `scripts/contact_sheet.py` renders every expression at every
shot type onto one page, which is the only way to decide where that threshold belongs.

## Derived at compile time

Forward kinematics resolves the skeleton into, per actor:

| Output | Used by |
|---|---|
| World position of every joint | Rendering |
| `mouth` anchor | Balloon tail termination |
| Face exclusion circle | Balloon placement (infinite cost) |
| Gaze vector | Balloon placement bias, `looking_at` resolution |
| Gaze *aim* | Pupil direction. Computed after placement, since it needs both actors |
| Face marks | Rendering only. The solver never sees them |
| Bounding polygon (hull) | Occlusion cost, inter-actor spacing |

Face marks are **not** in the hull. The head blob already is, and the features sit inside it, so a
drawn face pushing balloons further away would be a bug rather than a refinement.

`facing` mirrors the puppet about its root X axis; anchors and the gaze vector mirror with it.

## Landmark requirements

Every landmark named in [the shot table](shot_types.md) must be present and monotonically increasing
from `head_top` to `feet`. A puppet missing a landmark cannot be framed with the shot type that
crops there, and validation rejects it rather than guessing.
