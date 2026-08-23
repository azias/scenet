"""Actor placement: ordering, anchors, grounding, facing and draw order.

Several of these assert on *priority resolution* rather than on exact coordinates --
that two actors asked to stand in the same place end up apart, that a crowded panel
loosens rather than fails. Those behaviours are the reason a constraint solver is here
at all, so they are what needs guarding.
"""

from itertools import pairwise

import pytest

from scenet.assets.contract import PuppetLibrary, default_library
from scenet.assets.kinematics import resolve
from scenet.frontends.yaml_front import parse_panel
from scenet.geom import BBox
from scenet.ir import AnchorX
from scenet.solve.staging import (
    ANCHOR_FRACTIONS,
    LayoutError,
    Placement,
    depth_order,
    horizontal_order,
    solve_staging,
)

PANEL = 1000.0


@pytest.fixture(scope="module")
def library() -> PuppetLibrary:
    return default_library()


def bounds_of(placement: Placement, library: PuppetLibrary) -> BBox:
    return resolve(
        library.get(placement.reference),
        pose=placement.pose,
        facing_right=placement.facing_right,
        scale=placement.scale,
        origin=placement.origin,
    ).bounds


def solve(source: str, library: PuppetLibrary) -> dict[str, Placement]:
    placements, _ = solve_staging(parse_panel(source), library)
    return {placement.actor_id: placement for placement in placements}


TWO_ACTORS = """
camera: {shot: full_shot}
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: bob,   at: right_third}
"""


class TestHorizontalOrder:
    def test_declared_order_is_honoured(self, library: PuppetLibrary):
        panel = parse_panel("""
cast:
  a: {reference: alice, at: right_third}
  b: {reference: bob,   at: left_third}
staging:
  - a left_of b
""")
        assert horizontal_order(panel) == ("a", "b")

    def test_undeclared_order_falls_back_to_anchors(self, library: PuppetLibrary):
        panel = parse_panel("""
cast:
  a: {reference: alice, at: right_third}
  b: {reference: bob,   at: left_third}
""")
        assert horizontal_order(panel) == ("b", "a")

    def test_equal_anchors_break_by_id_for_determinism(self):
        panel = parse_panel("""
cast:
  zeta:  {reference: alice, at: center}
  alpha: {reference: bob,   at: center}
""")
        assert horizontal_order(panel) == ("alpha", "zeta")


class TestAnchors:
    def test_a_lone_actor_lands_on_its_anchor(self, library: PuppetLibrary):
        """With nothing to conflict with, the weak anchor preference is met exactly."""
        placements = solve(
            "camera: {shot: full_shot}\ncast:\n  a: {reference: alice, at: left_third}\n", library
        )
        centre = bounds_of(placements["a"], library).centre.x
        assert centre == pytest.approx(PANEL * ANCHOR_FRACTIONS[AnchorX.LEFT_THIRD], abs=1.0)

    @pytest.mark.parametrize("anchor", ["left_edge", "left_third", "center", "right_third"])
    def test_each_anchor_places_the_actor_where_it_says(self, library: PuppetLibrary, anchor: str):
        placements = solve(
            f"camera: {{shot: full_shot}}\ncast:\n  a: {{reference: alice, at: {anchor}}}\n",
            library,
        )
        centre = bounds_of(placements["a"], library).centre.x
        assert centre == pytest.approx(PANEL * ANCHOR_FRACTIONS[AnchorX(anchor)], abs=1.0)


class TestNonOverlap:
    def test_actors_never_overlap(self, library: PuppetLibrary):
        placements = solve(TWO_ACTORS, library)
        left = bounds_of(placements["alice"], library)
        right = bounds_of(placements["bob"], library)
        assert left.right < right.x

    def test_actors_sharing_an_anchor_are_pushed_apart(self, library: PuppetLibrary):
        """The reason for a constraint solver: a required non-overlap must beat a
        weak anchor preference without anyone writing a special case for it."""
        placements = solve(
            """
camera: {shot: full_shot}
cast:
  a: {reference: alice, at: center}
  b: {reference: bob,   at: center}
""",
            library,
        )
        left = bounds_of(placements["a"], library)
        right = bounds_of(placements["b"], library)
        assert left.right < right.x

    def test_a_crowded_panel_loosens_the_shot_rather_than_failing(self, library: PuppetLibrary):
        """Four actors at a close-up cannot fit; the camera must retreat."""
        source = "camera: {shot: close_up}\ncast:\n" + "\n".join(
            f"  a{i}: {{reference: alice}}" for i in range(4)
        )
        placements, camera = solve_staging(parse_panel(source), library)
        assert camera.was_pulled_back
        ordered = sorted(
            (bounds_of(placement, library) for placement in placements), key=lambda b: b.x
        )
        for earlier, later in pairwise(ordered):
            assert earlier.right < later.x


class TestGrounding:
    def test_shared_ground_aligns_feet(self, library: PuppetLibrary):
        placements = solve(
            """
camera: {shot: full_shot}
cast:
  alice: {reference: alice}
  bob:   {reference: bob}
staging:
  - alice ground_shared_with bob
""",
            library,
        )
        feet = [
            resolve(
                library.get(placement.reference),
                pose=placement.pose,
                facing_right=placement.facing_right,
                scale=placement.scale,
                origin=placement.origin,
            )
            .anchor("feet")
            .y
            for placement in placements.values()
        ]
        assert feet[0] == pytest.approx(feet[1], abs=0.5)

    def test_taller_actor_sits_higher_on_a_shared_ground(self, library: PuppetLibrary):
        placements = solve(
            """
camera: {shot: full_shot}
cast:
  alice: {reference: alice}
  bob:   {reference: bob}
staging:
  - alice ground_shared_with bob
""",
            library,
        )
        assert bounds_of(placements["bob"], library).y < bounds_of(placements["alice"], library).y


class TestFacing:
    def test_looking_at_turns_an_actor_toward_its_target(self, library: PuppetLibrary):
        placements = solve(
            """
cast:
  alice: {reference: alice, at: left_third, facing: left}
  bob:   {reference: bob,   at: right_third}
staging:
  - alice left_of bob
  - alice looking_at bob
""",
            library,
        )
        # `facing: left` is overridden: alice is left of her target, so she turns right.
        assert placements["alice"].facing_right is True

    def test_explicit_facing_is_used_when_no_gaze_target_exists(self, library: PuppetLibrary):
        placements = solve("cast:\n  a: {reference: alice, facing: left}\n", library)
        assert placements["a"].facing_right is False


class TestDepth:
    def test_unmentioned_actors_share_depth_zero(self):
        panel = parse_panel("cast:\n  a: {reference: alice}\n  b: {reference: bob}\n")
        assert depth_order(panel) == {"a": 0, "b": 0}

    def test_in_front_of_raises_depth(self):
        panel = parse_panel("""
cast:
  a: {reference: alice}
  b: {reference: bob}
staging:
  - a in_front_of b
""")
        depths = depth_order(panel)
        assert depths["a"] > depths["b"]

    def test_behind_is_the_same_relation_from_the_other_end(self):
        panel = parse_panel("""
cast:
  a: {reference: alice}
  b: {reference: bob}
staging:
  - b behind a
""")
        depths = depth_order(panel)
        assert depths["a"] > depths["b"]

    def test_chains_accumulate(self):
        panel = parse_panel("""
cast:
  a: {reference: alice}
  b: {reference: bob}
  c: {reference: alice}
staging:
  - a in_front_of b
  - b in_front_of c
""")
        depths = depth_order(panel)
        assert depths["a"] == 2
        assert depths["b"] == 1
        assert depths["c"] == 0

    def test_placements_come_out_in_draw_order(self, library: PuppetLibrary):
        placements, _ = solve_staging(
            parse_panel("""
cast:
  front: {reference: alice, at: left_third}
  back:  {reference: bob,   at: right_third}
staging:
  - front in_front_of back
"""),
            library,
        )
        assert [placement.actor_id for placement in placements] == ["back", "front"]


class TestErrors:
    def test_an_empty_cast_is_refused(self, library: PuppetLibrary):
        with pytest.raises(LayoutError, match="no cast"):
            solve_staging(parse_panel("panel: {size: [100, 100]}\ncast: {}\n"), library)


class TestDeterminism:
    def test_repeated_solves_are_identical(self, library: PuppetLibrary):
        panel = parse_panel(TWO_ACTORS)
        first, _ = solve_staging(panel, library)
        second, _ = solve_staging(panel, library)
        assert first == second

    def test_cast_declaration_order_does_not_change_geometry(self, library: PuppetLibrary):
        """Actors are keyed by name, so writing them in a different order must not
        move anybody. Only the framing reference depends on declaration order."""
        forward = solve(
            """
camera: {shot: full_shot}
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: alice, at: right_third}
""",
            library,
        )
        backward = solve(
            """
camera: {shot: full_shot}
cast:
  bob:   {reference: alice, at: right_third}
  alice: {reference: alice, at: left_third}
""",
            library,
        )
        assert forward["alice"].x == pytest.approx(backward["alice"].x)
        assert forward["bob"].x == pytest.approx(backward["bob"].x)
