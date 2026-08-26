"""Drawn faces: feature points, expressions, and where the pupils look.

The tests that matter here are the ones a type checker cannot stand in for. That every
expression produces *some* marks is nearly free; that the ten of them produce ten
**different** faces is the property that decides whether the vocabulary means anything,
and it is the one that would quietly rot if two states were given the same offsets.

What no test can settle is whether a furrowed brow reads as anger on the page. That is
what `scripts/contact_sheet.py` is for.
"""

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from scenet.assets.contract import (
    ExpressionSpec,
    Feature,
    PuppetLibrary,
    PuppetSpec,
    default_library,
)
from scenet.assets.face import MIN_FEATURE_RADIUS, FaceMark, ResolvedDisc, build_face
from scenet.assets.kinematics import resolve
from scenet.core import FaceDisc, PanelCore
from scenet.geom import Point, Vector
from scenet.pipeline import compile_source

EXPRESSIONS = (
    "neutral",
    "happy",
    "laughing",
    "coy",
    "bored",
    "scared",
    "sad",
    "angry",
    "shouting",
    "surprise",
)


@pytest.fixture(scope="module")
def library() -> PuppetLibrary:
    return default_library()


def face_of(reference: str, expression: str, *, shot: str = "close_up"):
    core = compile_source(
        f"{{camera: {{shot: {shot}}}, "
        f"cast: {{a: {{reference: {reference}, expression: {expression}}}}}}}"
    ).core
    return core.actor("a")


class TestTheContract:
    def test_both_puppets_ship_every_expression(self, library: PuppetLibrary):
        for name in library.names():
            assert set(library.get(name).expressions) == set(EXPRESSIONS)

    def test_the_vocabulary_is_comic_chats(self):
        """Comic Chat's emotion wheel plus `surprise`. A vocabulary proven in a system
        that rendered live conversations, not one borrowed from psychology -- these are
        the faces comics draw, and the docs must not claim more than that."""
        assert set(EXPRESSIONS) == {
            "neutral",
            "happy",
            "laughing",
            "coy",
            "bored",
            "scared",
            "sad",
            "angry",
            "shouting",
            "surprise",
        }

    def test_every_expression_is_a_distinct_record(self, library: PuppetLibrary):
        """Two expressions with the same states are one expression with two names."""
        alice = library.get("alice")
        states = [alice.expression_states(name) for name in EXPRESSIONS]
        assert len(set(states)) == len(EXPRESSIONS)

    def test_an_unknown_expression_lists_the_available_ones(self, library: PuppetLibrary):
        with pytest.raises(KeyError, match="laughing"):
            library.get("alice").expression_states("smouldering")

    def test_features_come_in_pairs(self):
        with pytest.raises(ValueError, match="without its pair"):
            PuppetSpec.model_validate(_minimal(features={"eye_l": {"offset": [-10, 0], "size": 4}}))

    def test_expressions_need_features_to_move(self):
        with pytest.raises(ValueError, match="no face features"):
            PuppetSpec.model_validate(_minimal(expressions={"neutral": {}}))

    def test_expressions_must_include_neutral(self):
        with pytest.raises(ValueError, match="not 'neutral'"):
            PuppetSpec.model_validate(
                _minimal(
                    features={
                        "eye_l": {"offset": [-10, 0], "size": 4},
                        "eye_r": {"offset": [10, 0], "size": 4},
                    },
                    expressions={"happy": {"mouth": "smile"}},
                )
            )

    def test_a_state_on_the_wrong_feature_is_rejected(self):
        with pytest.raises(ValidationError, match="mouth"):
            ExpressionSpec.model_validate({"mouth": "raised"})


class TestFeaturePoints:
    def test_they_ride_the_head(self, library: PuppetLibrary):
        """Move the figure and the face moves with it, because features are resolved
        through the same forward kinematics as anchors."""
        spec = library.get("alice")
        here = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        there = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(300, 0)
        )
        moved = there.features[Feature.MOUTH].centre.x - here.features[Feature.MOUTH].centre.x
        assert moved == pytest.approx(300.0)

    def test_they_mirror_with_the_figure(self, library: PuppetLibrary):
        spec = library.get("alice")
        facing = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        mirrored = resolve(
            spec, pose="standing_neutral", facing_right=False, scale=1.0, origin=Point(0, 0)
        )
        assert facing.features[Feature.EYE_L].centre.x == pytest.approx(
            -mirrored.features[Feature.EYE_L].centre.x
        )

    def test_they_scale(self, library: PuppetLibrary):
        spec = library.get("alice")
        small = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        big = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=2.0, origin=Point(0, 0)
        )
        assert big.features[Feature.EYE_L].size == pytest.approx(
            small.features[Feature.EYE_L].size * 2
        )

    def test_they_do_not_enter_the_hull(self, library: PuppetLibrary):
        """A face that pushed balloons further away would be a bug: the head blob is
        already in the hull, and the features sit inside it."""
        spec = library.get("alice")
        posed = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        bare = spec.model_copy(update={"face": spec.face.model_copy(update={"features": {}})})
        without = resolve(
            bare, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        assert posed.hull == without.hull


class TestDrawnFaces:
    @pytest.mark.parametrize("expression", EXPRESSIONS)
    @pytest.mark.parametrize("reference", ["alice", "bob"])
    def test_every_expression_draws_something(self, reference: str, expression: str):
        assert face_of(reference, expression).face_marks

    @pytest.mark.parametrize("expression", EXPRESSIONS)
    def test_marks_stay_inside_the_head(self, expression: str):
        """A face drawn outside the head it belongs to is the most obvious possible
        failure, and the easiest to introduce by getting one offset's sign wrong."""
        actor = face_of("alice", expression)
        head = max(actor.blobs, key=lambda blob: blob.radius)
        cx, cy = head.centre
        for mark in actor.face_marks:
            points = [mark.centre] if isinstance(mark, FaceDisc) else list(mark.points)
            for x, y in points:
                assert (x - cx) ** 2 + (y - cy) ** 2 <= head.radius**2

    def test_the_ten_faces_are_ten_different_faces(self):
        """The point of the whole ticket. If two expressions draw the same marks then
        one of them is decorative, and nobody would notice from the type checker."""
        drawn = {
            expression: face_of("alice", expression).model_dump_json(include={"face_marks"})
            for expression in EXPRESSIONS
        }
        assert len(set(drawn.values())) == len(EXPRESSIONS)

    def test_a_puppet_without_features_draws_no_face(self, library: PuppetLibrary):
        spec = library.get("alice")
        bare = spec.model_copy(update={"face": spec.face.model_copy(update={"features": {}})})
        posed = resolve(
            bare, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        assert build_face(posed, ExpressionSpec()) == ()

    def test_marks_are_emitted_in_a_fixed_order(self):
        ids = [mark.id for mark in face_of("alice", "neutral").face_marks]
        assert ids == ["brow_l", "brow_r", "eye_l", "pupil_l", "eye_r", "pupil_r", "nose", "mouth"]


class TestLevelOfDetail:
    def test_a_face_too_small_to_read_is_not_drawn(self, library: PuppetLibrary):
        """Five features inside a head a few units across stop being a face and become
        a smudge. A cartoonist leaves them out; so does this."""
        spec = library.get("alice")
        tiny = resolve(
            spec,
            pose="standing_neutral",
            facing_right=True,
            scale=(MIN_FEATURE_RADIUS * 0.9) / spec.face.radius,
            origin=Point(0, 0),
        )
        assert build_face(tiny, spec.expression_states("angry")) == ()

    def test_just_above_the_threshold_it_is(self, library: PuppetLibrary):
        spec = library.get("alice")
        small = resolve(
            spec,
            pose="standing_neutral",
            facing_right=True,
            scale=(MIN_FEATURE_RADIUS * 1.1) / spec.face.radius,
            origin=Point(0, 0),
        )
        assert build_face(small, spec.expression_states("angry"))

    def test_stroke_width_follows_the_face(self):
        """A face drawn small must not end up with lines as heavy as a face drawn
        large, which is what a fixed width would give it."""
        near = face_of("alice", "angry", shot="close_up")
        far = face_of("alice", "angry", shot="full_shot")
        assert _width_of(near, "mouth") > _width_of(far, "mouth")


class TestPupils:
    def test_they_sit_centred_when_nobody_is_being_looked_at(self):
        actor = face_of("alice", "neutral")
        for side in ("l", "r"):
            eye = _mark(actor, f"eye_{side}")
            pupil = _mark(actor, f"pupil_{side}")
            assert pupil.centre == eye.centre

    def test_they_follow_the_aim(self, library: PuppetLibrary):
        spec = library.get("alice")
        posed = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=4.0, origin=Point(0, 0)
        )
        left = build_face(posed, spec.expression_states("neutral"), Vector(-1.0, 0.0))
        right = build_face(posed, spec.expression_states("neutral"), Vector(1.0, 0.0))
        assert _disc(left, "pupil_l").centre.x < _disc(right, "pupil_l").centre.x

    def test_a_pupil_stays_inside_its_eye(self, library: PuppetLibrary):
        spec = library.get("alice")
        posed = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=4.0, origin=Point(0, 0)
        )
        marks = build_face(posed, spec.expression_states("neutral"), Vector(0.6, -0.8))
        eye, pupil = _disc(marks, "eye_l"), _disc(marks, "pupil_l")
        assert eye.centre.distance_to(pupil.centre) + pupil.radius <= eye.radius + 1e-9

    def test_a_closed_eye_has_no_pupil(self):
        ids = [mark.id for mark in face_of("alice", "laughing").face_marks]
        assert "pupil_l" not in ids


class TestGazeAim:
    def test_looking_at_produces_an_aim(self):
        core = compile_source(
            "{cast: {a: {reference: alice}, b: {reference: bob}},"
            " staging: [a left_of b, a looking_at b]}"
        ).core
        assert core.actor("a").gaze_aim is not None
        assert core.actor("b").gaze_aim is None

    def test_the_aim_points_at_the_target(self):
        """The thing the ticket's own design could not deliver: `gaze` is the head's
        forward direction and is horizontal for every actor in every panel, so it
        cannot distinguish looking up from looking down."""
        core = compile_source(
            "{cast: {a: {reference: alice}, b: {reference: bob}},"
            " staging: [a left_of b, a looking_at b]}"
        ).core
        looker, target = core.actor("a"), core.actor("b")
        aim = looker.gaze_aim
        assert aim is not None
        assert aim[0] > 0, "b is to the right of a, so a looks right"
        towards_x = target.face_exclusion.cx - looker.anchors["eyes"][0]
        assert (aim[0] > 0) == (towards_x > 0)

    def test_it_is_a_unit_vector(self):
        """To Core precision, which is where it stops being exact: components are
        rounded on the way into the document, as every number here is, so a unit
        vector comes back a fraction short."""
        core = compile_source(
            "{cast: {a: {reference: alice}, b: {reference: bob}},"
            " staging: [a left_of b, a looking_at b]}"
        ).core
        aim = core.actor("a").gaze_aim
        assert aim is not None
        assert (aim[0] ** 2 + aim[1] ** 2) == pytest.approx(1.0, abs=0.02)


class TestDeterminism:
    def test_the_same_face_compiles_to_the_same_bytes(self):
        source = "{camera: {shot: close_up}, cast: {a: {reference: alice, expression: scared}}}"
        assert compile_source(source).core.to_json() == compile_source(source).core.to_json()

    def test_a_face_survives_a_round_trip_through_json(self):
        core = face_of("alice", "surprise")
        whole = compile_source(
            "{camera: {shot: close_up}, cast: {a: {reference: alice, expression: surprise}}}"
        ).core
        assert PanelCore.from_json(whole.to_json()) == whole
        assert core.face_marks


def _mark(actor, mark_id: str):
    return next(mark for mark in actor.face_marks if mark.id == mark_id)


def _width_of(actor, mark_id: str) -> float:
    return _mark(actor, mark_id).width


def _disc(marks: Sequence[FaceMark], mark_id: str) -> ResolvedDisc:
    """The one disc with this id. Narrows the union, which the type checker needs and
    the reader does too."""
    return next(mark for mark in marks if mark.id == mark_id and isinstance(mark, ResolvedDisc))


def _minimal(
    features: dict[str, object] | None = None,
    expressions: dict[str, object] | None = None,
) -> dict[str, Any]:
    """The smallest valid puppet, with the face block under test spliced in."""
    face: dict[str, Any] = {"joint": "head", "radius": 60}
    if features is not None:
        face["features"] = features
    document: dict[str, Any] = {
        "name": "test",
        "units_per_head": 100,
        "landmarks": {
            "head_top": 0,
            "eyes": 40,
            "chin": 100,
            "shoulders": 130,
            "chest": 200,
            "waist": 330,
            "mid_thigh": 470,
            "knees": 560,
            "feet": 750,
        },
        "joints": {"root": {"parent": None}, "head": {"parent": "root", "offset": [0, -300]}},
        "anchors": {"eyes": {"joint": "head", "offset": [0, -10]}},
        "face": face,
    }
    if expressions is not None:
        document["expressions"] = expressions
    return document
