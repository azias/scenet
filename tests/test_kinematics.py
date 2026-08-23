"""Forward kinematics, and the geometric contract the solver depends on.

The recurring theme: anatomy declared as landmarks must agree with anatomy built from
joints. Those are two independent descriptions of the same body, and if they drift
apart the camera crops in the wrong place while everything still *looks* fine.
"""

import math

import pytest

from scenet.assets.contract import Landmark, PuppetLibrary, PuppetSpec, default_library
from scenet.assets.kinematics import convex_hull, resolve, solve_pose
from scenet.geom import Point


@pytest.fixture(scope="module")
def library() -> PuppetLibrary:
    return default_library()


@pytest.fixture(scope="module")
def alice(library: PuppetLibrary) -> PuppetSpec:
    return library.get("alice")


class TestLibrary:
    def test_ships_two_puppets(self, library: PuppetLibrary):
        assert library.names() == ("alice", "bob")

    def test_unknown_puppet_names_what_is_available(self, library: PuppetLibrary):
        with pytest.raises(KeyError, match="alice"):
            library.get("nobody")

    def test_puppets_have_different_proportions(self, library: PuppetLibrary):
        """Identical proportions would let a camera bug pass unnoticed, because every
        actor would scale the same way regardless of the crop landmark used."""
        alice, bob = library.get("alice"), library.get("bob")
        assert alice.total_height != bob.total_height
        assert alice.landmarks[Landmark.WAIST] != bob.landmarks[Landmark.WAIST]


class TestSkeletonMatchesLandmarks:
    """The declared landmarks and the built skeleton must describe the same body."""

    @pytest.mark.parametrize("name", ["alice", "bob"])
    @pytest.mark.parametrize(
        ("anchor", "landmark"),
        [("head_top", Landmark.HEAD_TOP), ("eyes", Landmark.EYES), ("feet", Landmark.FEET)],
    )
    def test_anchor_agrees_with_landmark(
        self, library: PuppetLibrary, name: str, anchor: str, landmark: Landmark
    ):
        spec = library.get(name)
        posed = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        assert posed.anchor(anchor).y == pytest.approx(posed.landmarks[landmark], abs=1.0)

    @pytest.mark.parametrize("name", ["alice", "bob"])
    def test_knees_landmark_matches_knee_joint(self, library: PuppetLibrary, name: str):
        spec = library.get(name)
        posed = resolve(
            spec, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        assert posed.joints["knee_l"].y == pytest.approx(posed.landmarks[Landmark.KNEES], abs=1.0)


class TestForwardKinematics:
    def test_root_lands_on_the_origin(self, alice: PuppetSpec):
        posed = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(400, 700)
        )
        assert posed.joints["root"] == Point(400, 700)

    def test_neutral_pose_hangs_arms_downward(self, alice: PuppetSpec):
        posed = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        assert posed.joints["wrist_r"].y > posed.joints["elbow_r"].y > posed.joints["shoulder_r"].y

    def test_pointing_extends_the_arm_sideways(self, alice: PuppetSpec):
        """The whole purpose of a skeleton: `pointing` is data, not a drawing."""
        neutral = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        pointing = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        assert pointing.joints["wrist_r"].x > neutral.joints["wrist_r"].x + 100

    def test_rotation_carries_the_whole_subtree(self, alice: PuppetSpec):
        """Bending the elbow must take the forearm and hand with it -- that is what
        makes a joint angle a pose rather than a disconnected limb."""
        posed = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        upper_arm = math.dist(
            (posed.joints["shoulder_r"].x, posed.joints["shoulder_r"].y),
            (posed.joints["elbow_r"].x, posed.joints["elbow_r"].y),
        )
        # Bone lengths are invariant under rotation; if the subtree were left behind
        # the segment would stretch.
        assert upper_arm == pytest.approx(95.0)

    def test_unknown_pose_lists_the_available_ones(self, alice: PuppetSpec):
        with pytest.raises(KeyError, match="standing_neutral"):
            solve_pose(alice, "nonexistent")


class TestMirroring:
    def test_facing_left_reflects_horizontally(self, alice: PuppetSpec):
        right = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        left = resolve(alice, pose="pointing", facing_right=False, scale=1.0, origin=Point(0, 0))
        assert left.joints["wrist_r"].x == pytest.approx(-right.joints["wrist_r"].x)
        assert left.joints["wrist_r"].y == pytest.approx(right.joints["wrist_r"].y)

    def test_gaze_follows_facing(self, alice: PuppetSpec):
        right = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        left = resolve(alice, pose="pointing", facing_right=False, scale=1.0, origin=Point(0, 0))
        assert right.gaze.dx > 0
        assert left.gaze.dx < 0

    def test_mirroring_preserves_vertical_anchors(self, alice: PuppetSpec):
        right = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        left = resolve(alice, pose="pointing", facing_right=False, scale=1.0, origin=Point(0, 0))
        assert left.anchor("mouth").y == pytest.approx(right.anchor("mouth").y)


class TestScaling:
    def test_scale_is_uniform(self, alice: PuppetSpec):
        unit = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        half = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=0.5, origin=Point(0, 0)
        )
        assert half.bounds.width == pytest.approx(unit.bounds.width / 2)
        assert half.bounds.height == pytest.approx(unit.bounds.height / 2)

    def test_face_radius_scales(self, alice: PuppetSpec):
        half = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=0.5, origin=Point(0, 0)
        )
        assert half.face.r == pytest.approx(alice.face.radius * 0.5)


class TestHull:
    def test_hull_encloses_every_joint(self, alice: PuppetSpec):
        """The hull is what balloon placement tests against, so a limb poking outside
        it would let a balloon overlap an arm."""
        posed = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        bounds = posed.bounds
        for name, joint in posed.joints.items():
            assert bounds.x <= joint.x <= bounds.right, name
            assert bounds.y <= joint.y <= bounds.bottom, name

    def test_hull_accounts_for_stroke_width(self, alice: PuppetSpec):
        """Enclosing only the centreline would let balloons overlap limbs by half a
        stroke width."""
        posed = resolve(
            alice, pose="standing_neutral", facing_right=True, scale=1.0, origin=Point(0, 0)
        )
        widest_joint = max(joint.x for joint in posed.joints.values())
        assert posed.bounds.right > widest_joint

    def test_hull_is_counter_clockwise_and_convex(self, alice: PuppetSpec):
        posed = resolve(alice, pose="pointing", facing_right=True, scale=1.0, origin=Point(0, 0))
        hull = posed.hull
        assert len(hull) >= 3
        for i in range(len(hull)):
            a, b, c = hull[i], hull[(i + 1) % len(hull)], hull[(i + 2) % len(hull)]
            cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
            assert cross > 0, "hull must be convex with consistent winding"


class TestConvexHull:
    def test_collinear_points_collapse(self):
        points = [Point(0, 0), Point(1, 0), Point(2, 0)]
        assert len(convex_hull(points)) <= 2

    def test_interior_point_is_excluded(self):
        square = [Point(0, 0), Point(10, 0), Point(10, 10), Point(0, 10)]
        hull = convex_hull([*square, Point(5, 5)])
        assert len(hull) == 4
        assert Point(5, 5) not in hull

    def test_duplicate_points_are_tolerated(self):
        hull = convex_hull([Point(0, 0), Point(0, 0), Point(4, 0), Point(0, 4)])
        assert len(hull) == 3


class TestDeterminism:
    def test_repeated_resolution_is_identical(self, alice: PuppetSpec):
        """Joint traversal is sorted rather than insertion-ordered precisely so that
        floating-point accumulation cannot vary between runs."""
        runs = [
            resolve(alice, pose="pointing", facing_right=True, scale=0.63, origin=Point(11, 23))
            for _ in range(3)
        ]
        assert runs[0].joints == runs[1].joints == runs[2].joints
        assert runs[0].hull == runs[1].hull == runs[2].hull
