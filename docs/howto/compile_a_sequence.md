# Compile a sequence of panels

Consecutive panels in a scene are mostly identical — the same cast, the same staging, the
same camera — with one thing changed. Restating all of it per panel is tedious, and it is
where continuity errors come from: the ones readers notice.

So a panel can state only what differs from another one.

## `over:` — sparse override

```yaml
panels:
  establishing:
    camera: {shot: full_shot}
    cast:
      alice: {reference: alice, at: left_third}
      bob:   {reference: bob,   at: right_third, facing: left}
    staging:
      - alice left_of bob

  reaction:
    over: establishing        # same cast, same staging
    camera: {shot: close_up}  # move in
```

The keyword is borrowed from [OpenUSD's composition arcs](../explanation/prior_art.md),
where `over` means exactly this: name a parent, then state the difference.

```python
from scenet import compile_scene

panels = compile_scene("""
panels:
  establishing:
    camera: {shot: full_shot}
    cast:
      alice: {reference: alice, at: left_third}
      bob:   {reference: bob,   at: right_third, facing: left}
    staging: [alice left_of bob]
  reaction:
    over: establishing
    camera: {shot: close_up}
""")

# The cast came through untouched.
assert len(panels["reaction"].core.actors) == 2

# The camera did not: a close-up draws everybody larger.
establishing = panels["establishing"].core.actor("alice").transform.scale
reaction = panels["reaction"].core.actor("alice").transform.scale
assert reaction > establishing
```

## Merge rules

Two rules, and they are worth knowing precisely:

- **Mappings merge recursively.** Overriding one actor's pose leaves the rest of that
  actor, and every other actor, alone.
- **Lists replace wholesale.** Give a panel its own `staging:` and you replace the
  parent's entirely — there is no appending. A list has no keys to merge on, and guessing
  at identity by position would be worse than a clear rule.

```python
from scenet import compile_scene

panels = compile_scene("""
panels:
  base:
    cast:
      alice: {reference: alice, pose: pointing, at: left_third}
      bob:   {reference: bob,   at: right_third}
    staging: [alice left_of bob]
  changed:
    over: base
    cast:
      alice: {pose: arms_crossed}
""")

alice = panels["changed"].core.actor("alice")

# `pose` was overridden; `reference` and `at` survived the merge.
assert alice.pose == "arms_crossed"
assert alice.reference == "alice"
```

## Shared defaults

Anything alongside `panels:` is a default every panel inherits, which saves restating the
panel size on each one:

```python
from scenet import compile_scene

panels = compile_scene("""
panel: {size: [1200, 500]}
camera: {shot: medium_shot}

panels:
  first:  {cast: {a: {reference: alice}}}
  second: {cast: {a: {reference: bob}}}
""")

assert all(result.core.width == 1200.0 for result in panels.values())
```

## Chains and cycles

`over:` chains as deep as you like. A cycle is a compile error rather than a hang:

```python
from scenet import CompositionError, compile_scene

try:
    compile_scene("panels: {a: {over: b}, b: {over: a}}")
except CompositionError as exc:
    assert "cyclic" in str(exc)
```

## Panels are compiled independently

Each panel is compiled on its own, and nothing about its composition depends on what sits
beside it. That is deliberate: if a panel laid out differently in a sequence than it did
alone, panels would not be reusable and golden-file tests would mean nothing.

## Rendering the whole thing

```bash
scenet build sequence.scene.yaml --strip
```

`--strip` writes one extra file laying every panel out side by side in reading order, on
top of the individual SVGs. From Python that is
{func}`render_strip <scenet.emit.strip.render_strip>`:

```python
from scenet import compile_scene, render_strip

panels = compile_scene("""
panels:
  one: {cast: {a: {reference: alice}}}
  two: {over: one, camera: {shot: close_up}}
""")

strip = render_strip([(name, result.core) for name, result in panels.items()])
assert strip.lstrip().startswith("<?xml")
```

Panel order in the output follows declaration order in the source, which is reading order.

## What this is not

`over:` is composition, not animation. There is no interpolation between panels and no
notion of time — a sequence is a set of independent panels that happen to share most of
their description. Page composition proper (tiers, panels of varying size, gutters) is
[not yet built](../explanation/status.md).
