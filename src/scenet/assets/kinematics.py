"""Forward kinematics: skeleton plus pose, resolved into concrete geometry.

Everything downstream -- camera scaling, actor placement, balloon avoidance, tail
routing, rendering -- consumes the output of this module and nothing else from the
asset layer. That boundary is the whole point: swap the puppet for hand-drawn
artwork exposing the same anchors and hulls, and layout is unchanged.
"""

import math
from dataclasses import dataclass

from scenet.assets.contract import BlobPart, BonePart, Landmark, PuppetSpec
from scenet.geom import BBox, Circle, Point, Vector


@dataclass(frozen=True, slots=True)
class ResolvedCapsule:
    """A limb segment: a thick line with rounded ends."""

    start: Point
    end: Point
    width: float


@dataclass(frozen=True, slots=True)
class ResolvedBlob:
    """A rounded mass -- head, hand, foot -- after posing.

    Attributes:
        centre: Where it sits, in panel coordinates.
        radius: Radius in panel units, already scaled by the camera.
    """

    centre: Point
    radius: float


@dataclass(frozen=True, slots=True)
class ResolvedPuppet:
    """A posed figure in panel coordinates.

    Produced once per actor per compile, then treated as read-only by every consumer.
    """

    name: str
    pose: str
    facing_right: bool
    scale: float
    joints: dict[str, Point]
    anchors: dict[str, Point]
    landmarks: dict[Landmark, float]
    capsules: tuple[ResolvedCapsule, ...]
    blobs: tuple[ResolvedBlob, ...]
    face: Circle
    gaze: Vector
    hull: tuple[Point, ...]

    @property
    def bounds(self) -> BBox:
        """Axis-aligned bounds of the posed silhouette."""
        xs = [point.x for point in self.hull]
        ys = [point.y for point in self.hull]
        return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def anchor(self, name: str) -> Point:
        """Look up one named attachment point in panel coordinates.

        Args:
            name: An anchor the puppet declared -- `mouth` and `eyes` are the ones the
                compiler itself relies on.

        Returns:
            Where that anchor ended up after posing, scaling and mirroring.

        Raises:
            KeyError: This puppet declares no anchor by that name.
        """
        if name not in self.anchors:
            raise KeyError(
                f"puppet '{self.name}' has no anchor '{name}'; has {sorted(self.anchors)}"
            )
        return self.anchors[name]


def _rotate(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    rad = math.radians(degrees)
    cos, sin = math.cos(rad), math.sin(rad)
    return dx * cos - dy * sin, dx * sin + dy * cos


def _topological_order(spec: PuppetSpec) -> list[str]:
    """Joints ordered parents-first, sorted at each level.

    Sorted rather than insertion-ordered so that the traversal -- and therefore any
    floating-point accumulation -- is identical on every run, which determinism
    requires.
    """
    children: dict[str | None, list[str]] = {}
    for name, joint in spec.joints.items():
        children.setdefault(joint.parent, []).append(name)
    for siblings in children.values():
        siblings.sort()

    order: list[str] = []
    stack = [spec.root]
    while stack:
        node = stack.pop()
        order.append(node)
        stack.extend(reversed(children.get(node, [])))
    return order


def solve_pose(spec: PuppetSpec, pose: str) -> tuple[dict[str, Point], dict[str, float]]:
    """Resolve joint positions in the puppet's own units, root at the origin.

    Returns the joint positions and the accumulated world angle at each joint, the
    latter being what anchors and gaze need in order to ride along with rotation.
    """
    angles = spec.pose_angles(pose)
    positions: dict[str, Point] = {}
    accumulated: dict[str, float] = {}

    for name in _topological_order(spec):
        joint = spec.joints[name]
        local_angle = angles.get(name, 0.0)
        if joint.parent is None:
            accumulated[name] = local_angle
            positions[name] = Point(0.0, 0.0)
            continue
        accumulated[name] = accumulated[joint.parent] + local_angle
        dx, dy = _rotate(joint.offset[0], joint.offset[1], accumulated[name])
        positions[name] = positions[joint.parent].translated(dx, dy)

    return positions, accumulated


def resolve(
    spec: PuppetSpec,
    *,
    pose: str,
    facing_right: bool,
    scale: float,
    origin: Point,
) -> ResolvedPuppet:
    """Pose, mirror, scale and place a puppet.

    `origin` is where the puppet's root joint lands in panel coordinates. Mirroring
    happens in the puppet's own frame before scaling, so a mirrored figure is the
    exact reflection of the original rather than being offset by rounding.
    """
    local, accumulated = solve_pose(spec, pose)
    mirror = 1.0 if facing_right else -1.0

    def to_panel(point: Point) -> Point:
        return Point(origin.x + mirror * point.x * scale, origin.y + point.y * scale)

    def offset_from(joint: str, offset: tuple[float, float]) -> Point:
        dx, dy = _rotate(offset[0], offset[1], accumulated[joint])
        return to_panel(local[joint].translated(dx, dy))

    joints = {name: to_panel(point) for name, point in local.items()}
    anchors = {
        name: offset_from(anchor.joint, anchor.offset) for name, anchor in spec.anchors.items()
    }

    capsules: list[ResolvedCapsule] = []
    blobs: list[ResolvedBlob] = []
    for part in spec.parts:
        if isinstance(part, BonePart):
            capsules.append(
                ResolvedCapsule(
                    start=joints[part.from_joint],
                    end=joints[part.to_joint],
                    width=part.width * scale,
                )
            )
        elif isinstance(part, BlobPart):
            blobs.append(
                ResolvedBlob(centre=offset_from(part.at, part.offset), radius=part.radius * scale)
            )

    face_centre = offset_from(spec.face.joint, spec.face.offset)
    face = Circle(face_centre.x, face_centre.y, spec.face.radius * scale)

    gaze_origin = anchors[spec.gaze.origin]
    forward_dx, forward_dy = _rotate(1.0, 0.0, accumulated[spec.face.joint])
    gaze = Vector(mirror * forward_dx, forward_dy).normalised()

    return ResolvedPuppet(
        name=spec.name,
        pose=pose,
        facing_right=facing_right,
        scale=scale,
        joints=joints,
        anchors=anchors,
        landmarks=_landmarks_in_panel(spec, origin.y, scale),
        capsules=tuple(capsules),
        blobs=tuple(blobs),
        face=face,
        gaze=gaze if gaze.length else Vector(mirror, 0.0),
        hull=convex_hull(_outline_points(capsules, blobs, [gaze_origin])),
    )


def _landmarks_in_panel(spec: PuppetSpec, origin_y: float, scale: float) -> dict[Landmark, float]:
    """Landmark heights as absolute panel y coordinates.

    Landmarks are declared downward from the top of the head, while the skeleton is
    built outward from the root joint. `root_landmark` says where those two frames
    meet, and this converts between them.
    """
    root_offset = spec.landmarks[spec.root_landmark]
    return {
        landmark: origin_y + (value - root_offset) * scale
        for landmark, value in spec.landmarks.items()
    }


def _outline_points(
    capsules: list[ResolvedCapsule], blobs: list[ResolvedBlob], extra: list[Point]
) -> list[Point]:
    """Sample points covering the drawn silhouette.

    Capsule ends are expanded to their four corners plus the rounded cap extremes, so
    the hull encloses the stroke rather than only its centreline -- otherwise
    balloons would be allowed to overlap limbs by half a stroke width.
    """
    points: list[Point] = list(extra)
    for capsule in capsules:
        dx = capsule.end.x - capsule.start.x
        dy = capsule.end.y - capsule.start.y
        length = math.hypot(dx, dy)
        half = capsule.width / 2
        if length == 0:
            points.extend(
                [
                    capsule.start.translated(half, half),
                    capsule.start.translated(-half, half),
                    capsule.start.translated(half, -half),
                    capsule.start.translated(-half, -half),
                ]
            )
            continue
        # Unit normal, and the unit direction used to extend past the rounded caps.
        nx, ny = -dy / length * half, dx / length * half
        ex, ey = dx / length * half, dy / length * half
        for end, sign in ((capsule.start, -1.0), (capsule.end, 1.0)):
            base = end.translated(sign * ex, sign * ey)
            points.append(base.translated(nx, ny))
            points.append(base.translated(-nx, -ny))
    for blob in blobs:
        r = blob.radius
        points.extend(
            [
                blob.centre.translated(r, 0),
                blob.centre.translated(-r, 0),
                blob.centre.translated(0, r),
                blob.centre.translated(0, -r),
                blob.centre.translated(r * 0.7071, r * 0.7071),
                blob.centre.translated(-r * 0.7071, r * 0.7071),
                blob.centre.translated(r * 0.7071, -r * 0.7071),
                blob.centre.translated(-r * 0.7071, -r * 0.7071),
            ]
        )
    return points


def convex_hull(points: list[Point]) -> tuple[Point, ...]:
    """Andrew's monotone chain, returning hull vertices counter-clockwise.

    Implemented here rather than delegated to shapely because it runs on a handful of
    points per actor and the result must be bit-for-bit reproducible; shapely is
    reserved for the genuinely hard polygon work in balloon placement.
    """
    unique = sorted({(point.x, point.y) for point in points})
    if len(unique) <= 2:
        return tuple(Point(x, y) for x, y in unique)

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return tuple(Point(x, y) for x, y in lower[:-1] + upper[:-1])
