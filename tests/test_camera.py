"""Camera framing.

The tests that matter here are the ones that would pass if scale were defined as a
fraction of panel height. That definition is the tempting wrong answer, so several
tests below exist specifically to fail against it.
"""

import pytest

from scenet.assets.contract import Landmark, PuppetLibrary, PuppetSpec, default_library
from scenet.ir import CameraAngle, ShotType
from scenet.solve.camera import (
    ANGLE_HEADROOM_FACTOR,
    SHOT_TABLE,
    headroom_for,
    solve_camera,
    visible_height,
)

PANEL = 1000.0


@pytest.fixture(scope="module")
def library() -> PuppetLibrary:
    return default_library()


@pytest.fixture(scope="module")
def alice(library: PuppetLibrary) -> PuppetSpec:
    return library.get("alice")


@pytest.fixture(scope="module")
def bob(library: PuppetLibrary) -> PuppetSpec:
    return library.get("bob")


class TestShotTable:
    def test_every_shot_type_is_tabled(self):
        """A shot type with no entry would raise a KeyError deep in the solver."""
        assert set(SHOT_TABLE) == set(ShotType)

    def test_aliases_resolve_identically(self):
        assert SHOT_TABLE[ShotType.WIDE] == SHOT_TABLE[ShotType.LONG_SHOT]
        assert SHOT_TABLE[ShotType.COWBOY] == SHOT_TABLE[ShotType.MEDIUM_FULL]

    def test_tighter_shots_crop_higher_up_the_body(self, alice: PuppetSpec):
        """The ordering that gives shot types their meaning."""
        progression = [
            ShotType.FULL_SHOT,
            ShotType.MEDIUM_FULL,
            ShotType.MEDIUM_SHOT,
            ShotType.MEDIUM_CLOSE_UP,
            ShotType.CLOSE_UP,
            ShotType.BIG_CLOSE_UP,
            ShotType.EXTREME_CLOSE_UP,
        ]
        heights = [visible_height(alice, shot) for shot in progression]
        assert heights == sorted(heights, reverse=True)

    def test_tighter_shots_scale_the_figure_up(self, alice: PuppetSpec):
        wide = solve_camera(
            alice, shot=ShotType.FULL_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        tight = solve_camera(
            alice, shot=ShotType.CLOSE_UP, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        assert tight.scale > wide.scale


class TestCropLandmarkSemantics:
    """Shot types name a crop line on the body, not a fraction of the panel."""

    def test_crop_line_lands_at_the_bottom_of_the_available_area(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        crop = SHOT_TABLE[ShotType.MEDIUM_SHOT].crop
        native_to_crop = alice.landmarks[crop] - alice.landmarks[Landmark.HEAD_TOP]
        crop_y = camera.head_top_y + native_to_crop * camera.scale
        assert crop_y == pytest.approx(PANEL * (1 - camera.footroom))

    def test_differently_proportioned_puppets_get_different_scales(
        self, alice: PuppetSpec, bob: PuppetSpec
    ):
        """The decisive test against 'a medium shot fills 60% of the panel'.

        Alice and Bob have different head-to-waist distances, so framing each at the
        waist requires different scales. A panel-fraction rule would hand them the
        same number and silently erase the difference between their bodies.
        """
        for shot in (ShotType.MEDIUM_SHOT, ShotType.CLOSE_UP):
            a = solve_camera(alice, shot=shot, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL)
            b = solve_camera(bob, shot=shot, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL)
            assert a.scale != b.scale

    def test_head_top_sits_at_the_headroom_fraction(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        assert camera.head_top_y == pytest.approx(PANEL * SHOT_TABLE[ShotType.MEDIUM_SHOT].headroom)


class TestAngle:
    def test_high_angle_leaves_more_air_above(self):
        low = headroom_for(ShotType.MEDIUM_SHOT, CameraAngle.LOW)
        level = headroom_for(ShotType.MEDIUM_SHOT, CameraAngle.EYE_LEVEL)
        high = headroom_for(ShotType.MEDIUM_SHOT, CameraAngle.HIGH)
        assert low < level < high

    def test_eye_level_is_the_tabled_value_untouched(self):
        assert headroom_for(ShotType.MEDIUM_SHOT, CameraAngle.EYE_LEVEL) == pytest.approx(
            SHOT_TABLE[ShotType.MEDIUM_SHOT].headroom
        )

    def test_angle_still_applies_to_a_zero_headroom_shot(self):
        """extreme_close_up has zero headroom, so a naive multiply would leave a high
        angle indistinguishable from eye level."""
        level = headroom_for(ShotType.EXTREME_CLOSE_UP, CameraAngle.EYE_LEVEL)
        high = headroom_for(ShotType.EXTREME_CLOSE_UP, CameraAngle.HIGH)
        assert level == 0.0
        assert high > 0.0

    def test_every_angle_has_a_factor(self):
        assert set(ANGLE_HEADROOM_FACTOR) == set(CameraAngle)


class TestGrounding:
    def test_shared_ground_aligns_feet_not_heads(self, alice: PuppetSpec, bob: PuppetSpec):
        """The point of a ground line: two people of different heights standing
        together have their feet level and their heads at different heights."""
        camera = solve_camera(
            alice, shot=ShotType.FULL_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        alice_root = camera.root_y_framed(alice)
        ground = camera.ground_y_of(alice, alice_root)
        bob_root = camera.root_y_on_ground(bob, ground)

        assert camera.ground_y_of(bob, bob_root) == pytest.approx(ground)
        # Bob is the taller puppet, so his waist sits higher on the same ground.
        assert bob_root < alice_root

    def test_round_trip_between_root_and_ground(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        root = 640.0
        assert camera.root_y_on_ground(alice, camera.ground_y_of(alice, root)) == pytest.approx(
            root
        )


class TestPullback:
    def test_untouched_camera_reports_no_pullback(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        assert camera.pullback == 1.0
        assert not camera.was_pulled_back

    def test_retreating_records_the_ratio(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        pulled = camera.pulled_back_to(camera.scale / 2)
        assert pulled.pullback == pytest.approx(0.5)
        assert pulled.was_pulled_back

    def test_the_camera_never_moves_closer(self, alice: PuppetSpec):
        """Fitting may only loosen a shot. Tightening it would crop the actor more
        than the author asked for, which is a change of meaning rather than of
        composition."""
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        assert camera.pulled_back_to(camera.scale * 2) is camera

    def test_headroom_survives_a_pullback(self, alice: PuppetSpec):
        camera = solve_camera(
            alice, shot=ShotType.MEDIUM_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=PANEL
        )
        pulled = camera.pulled_back_to(camera.scale * 0.5)
        assert pulled.headroom == camera.headroom
        assert pulled.head_top_y == camera.head_top_y


class TestValidation:
    def test_impossible_headroom_is_rejected(self, alice: PuppetSpec):
        with pytest.raises(ValueError, match="no room for the figure"):
            solve_camera(
                alice,
                shot=ShotType.MEDIUM_SHOT,
                angle=CameraAngle.EYE_LEVEL,
                panel_height=PANEL,
                footroom=0.95,
            )
