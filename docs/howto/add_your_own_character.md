# Add your own character

A character in Scenet is not a picture. It is a skeleton plus parametric limbs, so a pose
is a set of joint angles rather than a drawing — which avoids the combinatorial explosion
of one image per pose per expression per facing direction.

That skeleton is declared in a `*.puppet.yaml` file. This page walks through one.

## The file

```yaml
name: alice
units_per_head: 100
root: root
root_landmark: waist

landmarks:
  head_top: 0
  eyes: 40
  chin: 100
  shoulders: 132
  chest: 200
  waist: 330
  mid_thigh: 470
  knees: 560
  feet: 750

joints:
  root:       {parent: null, offset: [0, 0]}
  spine:      {parent: root, offset: [0, -130]}
  neck:       {parent: spine, offset: [0, -68]}
  head:       {parent: neck, offset: [0, -82]}
  shoulder_l: {parent: neck, offset: [-34, 6]}
  elbow_l:    {parent: shoulder_l, offset: [0, 95]}
  wrist_l:    {parent: elbow_l, offset: [0, 88]}
  # ...and the mirror image on the right, plus hips, knees and ankles.

parts:
  - {from: neck, to: root, width: 72}
  - {from: shoulder_l, to: elbow_l, width: 26}
  - {at: head, radius: 50}

anchors:
  head_top: {joint: head, offset: [0, -50]}
  eyes:     {joint: head, offset: [0, -10]}
  mouth:    {joint: head, offset: [0, 25]}
  feet:     {joint: root, offset: [0, 420]}

face:
  joint: head
  radius: 62

gaze:
  origin: eyes

poses:
  standing_neutral: {elbow_l: -5, elbow_r: 5}
  arms_crossed:     {elbow_l: -25, wrist_l: -75, elbow_r: 25, wrist_r: 75}
```

## Section by section

**`units_per_head`** sets the scale. Everything else is in native units where one head is
100, and the camera converts between those and panel units. Height in head-heights is
derived, not declared:

```python
from scenet import default_library

alice = default_library().get("alice")
assert alice.total_height == 750.0
assert alice.heads_tall == 7.5
```

**`landmarks`** are the crop lines a shot type names, measured downward from the top of the
head. All nine are required — not optional-with-defaults — because any shot type may crop
at any of them, so a puppet missing one is a puppet that cannot be framed at some
perfectly ordinary shot. `head_top` must be `0`, and the rest must increase downward.

**`joints`** form a tree. A joint's pose angle rotates the bone arriving at it *and*
everything below it, which is the formulation that makes posing read naturally: bending
`elbow_l` swings the upper arm and carries the forearm and hand with it.

**`parts`** are what actually gets drawn — a capsule between two joints, or a blob at one.
This is the only place appearance enters, and the solver never looks at it.

**`anchors`** are named attachment points. Two are load-bearing: `mouth`, where a balloon
tail aims, and `eyes`, where a gaze starts. Add whatever else you find useful.

**`face`** is the exclusion zone no balloon may cover. A head is not a circle, but for
layout purposes it is close enough and vastly cheaper — every "would this cover someone's
face?" test becomes one distance comparison.

**`poses`** are named sets of joint angles. Joints you leave out keep their rest angle.

## Loading it

```python
from pathlib import Path

from scenet import PuppetLibrary, compile_source, default_library, load_puppet
from scenet.assets.contract import DEFAULT_LIBRARY_PATH

# One file at a time...
alice = load_puppet(DEFAULT_LIBRARY_PATH / "alice.puppet.yaml")
assert alice.name == "alice"

# ...or a whole directory.
library = PuppetLibrary.from_directory(DEFAULT_LIBRARY_PATH)
assert library.names() == ("alice", "bob")

result = compile_source("cast: {a: {reference: alice}}", library=library)
assert result.core.actors[0].reference == "alice"
```

Your own directory works exactly the same way — point
{meth}`from_directory <scenet.assets.contract.PuppetLibrary.from_directory>` at it. The
files must be named `*.puppet.yaml`, and the `name:` inside each one, not the filename, is
what a cast member's `reference` matches.

## Validation catches the mistakes you will actually make

Puppet files are validated exhaustively at load time, because a puppet that is subtly
wrong produces a figure that is subtly wrong with nothing to point at:

| Mistake | Caught as |
|---|---|
| A landmark missing | "is missing landmarks [...]" |
| Landmarks out of order | "must increase downward from head_top to feet" |
| `head_top` not zero | "head_top must be 0, it is the origin" |
| Root joint has a parent | "root joint must have no parent" |
| A joint naming a parent that does not exist | "names unknown parent" |
| A joint cycle | "sits in a cycle" |
| A part, anchor or pose naming a joint that does not exist | "references unknown joint" |
| `gaze.origin` not among the anchors | "is not a declared anchor" |
| Two files declaring the same `name:` | "duplicate puppet name" |

The cycle and orphan checks are not pedantry. Forward kinematics accumulates each joint's
transform from its parent's, so a cycle would not terminate and an orphan would leave a
limb with no defined position.

```python
import pydantic
import pytest

from scenet import PuppetSpec

with pytest.raises(pydantic.ValidationError, match="missing landmarks"):
    PuppetSpec.model_validate(
        {
            "name": "incomplete",
            "units_per_head": 100,
            "landmarks": {"head_top": 0, "feet": 700},
            "joints": {"root": {"parent": None, "offset": [0, 0]}},
            "face": {"joint": "root", "radius": 10},
        }
    )
```

## Make them different from each other

The two shipped puppets have deliberately different proportions — 7.5 heads and taller.
That is a testing decision as much as an artistic one: a bug in camera scaling cannot hide
behind two figures that happen to be the same height, and neither can a bug in
ground-sharing, which aligns feet rather than heads.

If you add characters, make them differ. Identical puppets are a blindfold.

## What is not modelled

No faces beyond a circle, no hands beyond a blob, no clothing, no expressions, no props.
The asset contract is the *geometric* contract — enough for the solver to place things and
for the emitter to draw a legible wireframe. Real artwork would slot in behind the same
contract without the solver noticing, which is the reason the boundary is drawn where it
is.
