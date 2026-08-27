"""Camera framing.

The tests that matter here are the ones that would pass if scale were defined as a
fraction of panel height. That definition is the tempting wrong answer, so several
tests below exist specifically to fail against it.
"""

from itertools import pairwise
from pathlib import Path

import pytest

from scenet.assets.contract import Landmark, PuppetLibrary, PuppetSpec, default_library
from scenet.ir import CameraAngle, ShotType
from scenet.pipeline import compile_source
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

    def test_wide_is_a_synonym_for_long_shot(self):
        """The literature uses them interchangeably: "a long shot (also called a wide
        shot)". The language keeps both because writers reach for both."""
        assert SHOT_TABLE[ShotType.WIDE] == SHOT_TABLE[ShotType.LONG_SHOT]

    def test_medium_full_and_cowboy_are_different_shots(self):
        """These were the same entry, which silently collapsed a rung of the ladder.

        Medium full -- the three-quarter shot -- cuts at the knees. The cowboy or
        American shot cuts at mid-thigh, from 1930s Western framing that had to include
        the holster. Naming two shots and drawing one is worse than not offering both.
        """
        assert SHOT_TABLE[ShotType.MEDIUM_FULL].crop is Landmark.KNEES
        assert SHOT_TABLE[ShotType.COWBOY].crop is Landmark.MID_THIGH
        assert SHOT_TABLE[ShotType.MEDIUM_FULL] != SHOT_TABLE[ShotType.COWBOY]

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


class TestWhatAShotFramesFitsInThePanel:
    """A shot names where the frame cuts the body -- so that cut had better land inside
    the panel it is cutting.

    Nothing above tests this. Every assertion in this file is *relative* -- one scale
    against another -- and the ladder test only checks that scale never decreases,
    which `extreme_close_up` satisfies while framing the forehead: its head-top and
    crop line landed at y=0 and y=1000 in a 1000-unit panel, with the eyes themselves
    entirely off the bottom edge. `test_marks_stay_inside_the_head` in
    tests/test_faces.py is head-relative and stays green under the same bug, because a
    head drawn below the panel is still a head.
    """

    @pytest.mark.parametrize("shot", list(ShotType))
    @pytest.mark.parametrize("angle", list(CameraAngle))
    @pytest.mark.parametrize("reference", ["alice", "bob"])
    def test_head_top_and_crop_line_land_inside_the_panel(
        self, library: PuppetLibrary, reference: str, shot: ShotType, angle: CameraAngle
    ):
        puppet = library.get(reference)
        camera = solve_camera(puppet, shot=shot, angle=angle, panel_height=PANEL)
        crop = SHOT_TABLE[shot].crop
        crop_y = camera.head_top_y + visible_height(puppet, shot) * camera.scale
        # A crop line at exactly footroom=0 lands on the panel edge by design (the
        # anchoring rule in docs/reference/shot_types.md), which floating-point
        # arithmetic can place a hair past -- tolerance, not slack in the rule itself.
        tolerance = 1e-6 * PANEL
        assert -tolerance <= camera.head_top_y <= PANEL + tolerance, (
            f"{reference} {shot.value} at {angle.value}: head_top_y={camera.head_top_y}"
        )
        assert -tolerance <= crop_y <= PANEL + tolerance, (
            f"{reference} {shot.value} at {angle.value}: {crop.value}_y={crop_y}"
        )


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


class TestTheLadderIsALadder:
    """Reading the shot table from widest to tightest, the figure never gets smaller.

    That is what makes it a ladder, and it is worth a test rather than an inspection.
    `long_shot` and `full_shot` crop at the same landmark, so only headroom separates
    them -- and having those two the wrong way round inverted the ladder at its widest
    end while every other test stayed green.
    """

    ORDER = [
        ShotType.LONG_SHOT,
        ShotType.FULL_SHOT,
        ShotType.MEDIUM_FULL,
        ShotType.MEDIUM_SHOT,
        ShotType.MEDIUM_CLOSE_UP,
        ShotType.CLOSE_UP,
        ShotType.BIG_CLOSE_UP,
        ShotType.EXTREME_CLOSE_UP,
    ]

    def _scales(self) -> list[float]:
        reference = default_library().get("alice")
        return [
            solve_camera(
                reference, shot=shot, angle=CameraAngle.EYE_LEVEL, panel_height=1000.0
            ).scale
            for shot in self.ORDER
        ]

    def test_scale_never_decreases(self):
        scales = self._scales()
        inverted = [
            (self.ORDER[index].value, self.ORDER[index + 1].value)
            for index, (wider, tighter) in enumerate(pairwise(scales))
            if tighter < wider
        ]
        assert inverted == [], "a tighter shot drew the figure smaller than a wider one"

    def test_the_ladder_actually_climbs(self):
        """Monotonic is not enough -- a table of identical values is monotonic."""
        scales = self._scales()
        assert scales[-1] > scales[0] * 4

    def test_a_long_shot_is_meaningfully_wider_than_a_full_shot(self):
        """The two rungs at the widest end used to be degenerate, and the comment in
        `camera.py` admitted it: with nothing behind the figure, "small in its
        environment" and "the whole body" could differ only by a little headroom.

        There is an environment now, so a long shot can mean what it says. This asserts
        the gap is a real rung rather than a nudge -- which is the half of the setting
        work that shows up in the camera rather than in the backdrop.
        """
        scales = dict(zip(self.ORDER, self._scales(), strict=False))
        assert scales[ShotType.LONG_SHOT] <= scales[ShotType.FULL_SHOT] * 0.8

    def test_wide_and_long_shot_are_exact_synonyms(self):
        reference = default_library().get("alice")
        first = solve_camera(
            reference, shot=ShotType.LONG_SHOT, angle=CameraAngle.EYE_LEVEL, panel_height=1000.0
        )
        second = solve_camera(
            reference, shot=ShotType.WIDE, angle=CameraAngle.EYE_LEVEL, panel_height=1000.0
        )
        assert first.scale == second.scale

    def test_cowboy_is_tighter_than_medium_full(self):
        """Mid-thigh is above the knees, so the cowboy shot draws the figure larger."""
        reference = default_library().get("alice")
        looser = solve_camera(
            reference, shot=ShotType.MEDIUM_FULL, angle=CameraAngle.EYE_LEVEL, panel_height=1000.0
        )
        tighter = solve_camera(
            reference, shot=ShotType.COWBOY, angle=CameraAngle.EYE_LEVEL, panel_height=1000.0
        )
        assert tighter.scale > looser.scale


class TestTheRetreatNoteNamesTheShot:
    """A diagnostic that says the camera retreated must say retreated *from what*.

    This shipped saying "the requested 'alice' framing" -- naming the puppet the shot
    was composed on rather than the shot itself, which reads as nonsense to anyone who
    did not write the compiler. Caught by reading the notes on the live playground.
    """

    SOURCE = """
panel: {size: [600, 400]}
camera: {shot: close_up}
cast:
  alice: {reference: alice}
  bob:   {reference: bob}
staging: [alice left_of bob]
"""

    def test_the_note_names_the_shot_type(self):
        notes = compile_source(self.SOURCE).notes
        retreat = next(note for note in notes if "camera retreated" in note)
        assert "'close_up'" in retreat

    def test_the_note_does_not_name_a_puppet(self):
        notes = compile_source(self.SOURCE).notes
        retreat = next(note for note in notes if "camera retreated" in note)
        assert "alice" not in retreat
        assert "bob" not in retreat

    def test_the_solution_still_records_which_actor_framed_it(self):
        """The reference is genuinely useful; it was only the wrong thing to print."""
        result = compile_source(self.SOURCE)
        assert result.camera.reference == "alice"
        assert result.camera.shot is ShotType.CLOSE_UP


class TestShotsThatShowFeetActuallyShowThem:
    """A long shot that cuts the feet off is not a long shot.

    The crop lands the FEET *landmark* on the frame edge, but the drawing continues past
    it: the ankle joint sits exactly on that landmark and the shin capsule has a round
    cap, so half its width is drawn below. With no footroom the figure was clipped by
    that much -- 9 panel units at long shot -- which is invisible in the numbers and
    obvious on the page.
    """

    FEET_SHOTS = [ShotType.LONG_SHOT, ShotType.WIDE, ShotType.FULL_SHOT]

    @pytest.mark.parametrize("shot", FEET_SHOTS)
    def test_the_whole_figure_fits_inside_the_panel(self, shot: ShotType):
        result = compile_source(
            f"panel: {{size: [420, 560]}}\ncamera: {{shot: {shot.value}}}\n"
            "cast: {alice: {reference: alice, pose: pointing}}\n"
        )
        bounds = result.core.actor("alice").bounds
        assert bounds.y >= 0, f"{shot.value} clips the head"
        assert bounds.y + bounds.height <= result.core.height, f"{shot.value} clips the feet"

    @pytest.mark.parametrize("shot", FEET_SHOTS)
    def test_they_reserve_ground_beneath_the_feet(self, shot: ShotType):
        """Not merely un-clipped: a figure on the exact bottom edge reads as falling out
        of the panel rather than standing on anything."""
        assert SHOT_TABLE[shot].footroom > 0

    def test_shots_cropping_above_the_feet_reserve_none(self):
        """There is no ground in frame to leave -- except at `eyes`.

        `extreme_close_up` is the one exception: its crop landmark sits *inside* the
        face rather than at its edge, so footroom there is not ground but the only
        lever that pulls the crop line off the bottom edge at all. See
        `ShotSpec.footroom` and docs/reference/shot_types.md.
        """
        for shot, spec in SHOT_TABLE.items():
            if spec.crop not in (Landmark.FEET, Landmark.EYES):
                assert spec.footroom == 0.0, f"{shot.value} crops above the feet"


class TestTheNormativeTableMatchesTheCode:
    """`docs/reference/shot_types.md` calls itself normative, so it had better be true.

    It drifted: it claimed `long_shot` had a headroom of 0.60 when the code used 0.14,
    and listed `cowboy` as an alias of `medium_full` after they had become different
    shots. A specification nobody checks is a comment in a different file.
    """

    DOC = Path(__file__).parent.parent / "docs" / "reference" / "shot_types.md"

    def _row(self, shot: ShotType) -> str:
        """Find the table row for a shot.

        Synonyms share a row -- `long_shot` is written "`long_shot` (alias `wide`)" --
        so the name is looked for anywhere in the first cell rather than at its start.
        """
        for line in self.DOC.read_text(encoding="utf-8").splitlines():
            if not line.startswith("| `"):
                continue
            first_cell = line.split("|")[1]
            if f"`{shot.value}`" in first_cell:
                return line
        raise AssertionError(f"{shot.value} has no row in the normative table")

    @pytest.mark.parametrize("shot", list(ShotType))
    def test_every_shot_has_a_row(self, shot: ShotType):
        assert self._row(shot)

    @pytest.mark.parametrize("shot", list(ShotType))
    def test_the_crop_landmark_matches(self, shot: ShotType):
        assert f"`{SHOT_TABLE[shot].crop.value}`" in self._row(shot)

    @pytest.mark.parametrize("shot", list(ShotType))
    def test_the_headroom_matches(self, shot: ShotType):
        assert f"{SHOT_TABLE[shot].headroom:.2f}" in self._row(shot)
