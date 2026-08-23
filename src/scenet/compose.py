"""Sparse override between panels.

Borrowed from OpenUSD's composition arcs, and specifically from `over`: a panel names
a parent and states only what differs from it.

This matters more for comics than it might look. Consecutive panels in a scene are
mostly identical -- the same cast, the same staging, the same camera -- with one thing
changed. Restating all of it per panel is both tedious and a place for inconsistencies
to creep in, which is exactly the continuity error comics readers notice.

    panels:
      p1:
        camera: {shot: medium_shot}
        cast:
          alice: {reference: alice, at: left_third}
      p2:
        over: p1                      # everything from p1...
        camera: {shot: close_up}      # ...except the framing
"""

from typing import Any

# The key naming a panel's parent. Spelled as USD spells it, since the semantics are
# deliberately the same.
OVER_KEY = "over"


class CompositionError(ValueError):
    """An override chain that cannot be resolved."""


def merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `override` onto `base`, with `override` winning.

    Mappings merge recursively so that changing one actor's pose leaves the rest of
    the cast alone. Lists replace wholesale rather than concatenating: `script` and
    `staging` are ordered wholes, and appending to an inherited script would make it
    impossible to write a panel where somebody says less than in the panel before.
    """
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = merge(existing, value)
        else:
            result[key] = value
    return result


def resolve_overrides(panels: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resolve every panel's `over` chain into a self-contained document.

    Panels are resolved lazily with memoisation, so a chain is walked once however
    many panels hang off it, and declaration order does not matter -- a panel may
    inherit from one declared later.
    """
    resolved: dict[str, dict[str, Any]] = {}

    def resolve(name: str, seen: tuple[str, ...]) -> dict[str, Any]:
        if name in resolved:
            return resolved[name]
        if name in seen:
            chain = " -> ".join([*seen, name])
            raise CompositionError(f"'over' chain is cyclic: {chain}")
        if name not in panels:
            raise CompositionError(
                f"panel '{name}' does not exist; declared panels are {sorted(panels)}"
            )

        document = dict(panels[name])
        parent_name = document.pop(OVER_KEY, None)
        if parent_name is None:
            resolved[name] = document
            return document

        if not isinstance(parent_name, str):
            raise CompositionError(
                f"panel '{name}': 'over' must name a single panel, "
                f"found {type(parent_name).__name__}"
            )
        composed = merge(resolve(parent_name, (*seen, name)), document)
        resolved[name] = composed
        return composed

    # Sorted so that an error in a shared ancestor is reported against the same panel
    # on every run.
    for name in sorted(panels):
        resolve(name, ())
    return {name: resolved[name] for name in panels}
