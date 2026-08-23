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
  exclusion_radius: 65      # balloons may never overlap this circle

gaze:
  origin: eyes
  default_dir: facing

poses:
  standing_neutral: {...joint angles}
  arms_crossed: {...}
  pointing: {...}
```

## Derived at compile time

Forward kinematics resolves the skeleton into, per actor:

| Output | Used by |
|---|---|
| World position of every joint | Rendering |
| `mouth` anchor | Balloon tail termination |
| Face exclusion circle | Balloon placement (infinite cost) |
| Gaze vector | Balloon placement bias, `looking_at` resolution |
| Bounding polygon (hull) | Occlusion cost, inter-actor spacing |

`facing` mirrors the puppet about its root X axis; anchors and the gaze vector mirror with it.

## Landmark requirements

Every landmark named in [the shot table](shot_types.md) must be present and monotonically increasing
from `head_top` to `feet`. A puppet missing a landmark cannot be framed with the shot type that
crops there, and validation rejects it rather than guessing.
