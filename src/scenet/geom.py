"""Geometry primitives: points, vectors, boxes and circles.

Everything downstream of the frontend speaks in these four types. They are the whole
vocabulary the solver has for describing a character -- a silhouette is a list of
`Point`, a face is a `Circle`, a balloon is a `BBox`, a gaze is a `Vector` -- which is
what keeps the layout engine from ever needing to know what anything looks like.

**Coordinate system.** SVG's: x runs rightward, y runs *downward*, and the origin is the
panel's top-left corner. Angles are in degrees, measured clockwise, which is what
"clockwise" means once y points down. All lengths are in panel units; a panel declares
its own size, so a unit is whatever fraction of the panel you decide it is.

**Strictness.** Every containment and intersection test here is strict: a point exactly
on a circle's edge is not inside it, and two shapes that merely touch do not intersect.
Applied consistently, a shared boundary belongs to neither shape -- so two balloons
resting edge to edge are legal, and a tail grazing a face outline is not diverted.
Mixing strict and non-strict tests would make those cases depend on which function you
happened to ask. The one deliberate exception is `BBox.contains`, documented there.

**Immutability.** Every type here is frozen and slotted. The balloon search creates
these in tight loops, so the memory layout matters; and a resolved layout that cannot be
mutated is a layout the emitter cannot quietly change on its way out.

A note on annotations: self- and forward-references are quoted (`-> "Point"`). Before
Python 3.14 and PEP 649 a bare `-> Point` inside `class Point` is evaluated at
definition time and raises NameError, and BBox and Circle refer to each other mutually
so no ordering fixes it. `Self` is deliberately not used: these methods construct their
own class by name, so `Self` would promise subclass-preserving behaviour the bodies do
not deliver.
"""

import math
from dataclasses import dataclass

__all__ = [
    "PRECISION",
    "BBox",
    "Circle",
    "Point",
    "Vector",
    "rounded",
    "segment_intersects_circle",
]

# Coordinates are rounded to this many decimals on emission. Two decimals is far below
# the visible threshold at any sane panel size, and it makes output byte-identical
# across platforms whose floating-point formatting differs in the last digit.
PRECISION = 2


def rounded(value: float) -> float:
    """Round a coordinate for emission.

    Uses Python's built-in `round`, which is round-half-to-even -- so `0.125` becomes
    `0.12` and `0.135` becomes `0.14`. That asymmetry looks like a bug the first time
    you meet it in a golden file and is not one: half-to-even is deterministic and
    unbiased, which is exactly what byte-identical output needs.

    Adding `0.0` afterwards normalises `-0.0` to `0.0`. Without it a coordinate that
    rounds to negative zero emits as `-0.0` and produces a spurious diff against an
    otherwise identical file.

    Args:
        value: A coordinate in panel units.

    Returns:
        The value rounded to `PRECISION` decimal places, never negative zero.

    Example:
        >>> from scenet.geom import rounded
        >>> rounded(12.3456)
        12.35
        >>> rounded(-0.001)
        0.0
    """
    return round(value, PRECISION) + 0.0


@dataclass(frozen=True, slots=True)
class Point:
    """A position in panel space.

    The most common type in the codebase. Anchors are points, silhouette hulls are
    sequences of points, and both ends of a balloon tail are points.

    Attributes:
        x: Distance rightward from the panel's left edge.
        y: Distance *downward* from the panel's top edge.

    Example:
        >>> from scenet.geom import Point
        >>> mouth = Point(120.0, 84.0)
        >>> mouth.translated(0, 10)
        Point(x=120.0, y=94.0)
    """

    x: float
    y: float

    def translated(self, dx: float, dy: float) -> "Point":
        """Return this point moved by an offset.

        Args:
            dx: Rightward offset.
            dy: Downward offset.

        Returns:
            A new point; this one is unchanged.
        """
        return Point(self.x + dx, self.y + dy)

    def rotated_around(self, origin: "Point", degrees: float) -> "Point":
        """Return this point rotated about another.

        This is the workhorse of forward kinematics: posing a limb is rotating its far
        end around its joint.

        Args:
            origin: The centre of rotation.
            degrees: Rotation angle, **clockwise** on screen -- which is the positive
                direction once y points downward.

        Returns:
            A new point.

        Example:
            >>> from scenet.geom import Point, rounded
            >>> turned = Point(10.0, 0.0).rotated_around(Point(0.0, 0.0), 90)
            >>> rounded(turned.x), rounded(turned.y)
            (0.0, 10.0)
        """
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        dx, dy = self.x - origin.x, self.y - origin.y
        return Point(origin.x + dx * cos - dy * sin, origin.y + dx * sin + dy * cos)

    def distance_to(self, other: "Point") -> float:
        """Return the straight-line distance to another point.

        Args:
            other: The point to measure to.

        Returns:
            Distance in panel units, never negative.
        """
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        """Return `(x, y)` rounded for emission.

        Returns:
            The pair a Panel Core document stores, already passed through
            [`rounded`][scenet.geom.rounded].
        """
        return (rounded(self.x), rounded(self.y))


@dataclass(frozen=True, slots=True)
class Vector:
    """A direction and magnitude, with no position.

    Distinct from `Point` on purpose. A gaze direction and an eye position are both
    pairs of floats and mean entirely different things; giving them different types
    means the type checker catches you confusing them.

    Attributes:
        dx: Rightward component.
        dy: Downward component.

    Example:
        >>> from scenet.geom import Vector
        >>> Vector(3.0, 4.0).length
        5.0
        >>> Vector(3.0, 4.0).normalised()
        Vector(dx=0.6, dy=0.8)
    """

    dx: float
    dy: float

    @property
    def length(self) -> float:
        """The vector's magnitude."""
        return math.hypot(self.dx, self.dy)

    def normalised(self) -> "Vector":
        """Return this vector scaled to unit length.

        A zero vector is returned unchanged rather than raising. That lets callers treat
        "this character is not looking at anything" as a neutral term in the arithmetic
        instead of special-casing `None` at every use.

        Returns:
            A unit vector in the same direction, or the zero vector unchanged.
        """
        length = self.length
        if length == 0:
            return self
        return Vector(self.dx / length, self.dy / length)

    def mirrored_x(self) -> "Vector":
        """Return this vector reflected left-to-right.

        Used when an actor faces the other way: the whole puppet is mirrored, and its
        gaze has to come along.

        Returns:
            A new vector with `dx` negated.
        """
        return Vector(-self.dx, self.dy)

    def dot(self, other: "Vector") -> float:
        """Return the dot product with another vector.

        Args:
            other: The vector to project onto.

        Returns:
            Positive when the two point broadly the same way, negative when opposed,
            zero when perpendicular.
        """
        return self.dx * other.dx + self.dy * other.dy

    def as_tuple(self) -> tuple[float, float]:
        """Return `(dx, dy)` rounded for emission."""
        return (rounded(self.dx), rounded(self.dy))


@dataclass(frozen=True, slots=True)
class BBox:
    """An axis-aligned rectangle, given as a corner plus a size.

    Balloons are boxes, panel frames are boxes, and every silhouette has one as its
    bounds. Stored as `x, y, width, height` rather than as two corners because that is
    what SVG wants and what the constraint solver's variables map onto directly.

    Attributes:
        x: Left edge.
        y: Top edge.
        width: Extent rightward.
        height: Extent downward.

    Example:
        >>> from scenet.geom import BBox
        >>> balloon = BBox(10.0, 20.0, 100.0, 50.0)
        >>> balloon.right, balloon.bottom
        (110.0, 70.0)
        >>> balloon.centre
        Point(x=60.0, y=45.0)
    """

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        """The right edge, `x + width`."""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """The bottom edge, `y + height`. Larger than `y`, because y runs downward."""
        return self.y + self.height

    @property
    def centre(self) -> "Point":
        """The midpoint of the box."""
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> float:
        """Width times height."""
        return self.width * self.height

    def contains(self, other: "BBox") -> bool:
        """Whether another box lies entirely within this one.

        Edges may coincide: a box exactly filling this one is contained. This is the
        module's one deliberate departure from strictness, because a balloon sitting
        flush against the panel margin is inside the panel.

        Args:
            other: The box to test.

        Returns:
            True if no part of `other` falls outside this box.
        """
        return (
            other.x >= self.x
            and other.y >= self.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def overlap_area(self, other: "BBox") -> float:
        """Return the area shared with another box.

        Args:
            other: The box to intersect with.

        Returns:
            The overlapping area, or `0.0` when the boxes are disjoint or merely touch.

        Example:
            >>> from scenet.geom import BBox
            >>> BBox(0.0, 0.0, 10.0, 10.0).overlap_area(BBox(5.0, 5.0, 10.0, 10.0))
            25.0
            >>> BBox(0.0, 0.0, 10.0, 10.0).overlap_area(BBox(10.0, 0.0, 10.0, 10.0))
            0.0
        """
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def intersects_circle(self, circle: "Circle") -> bool:
        """Whether a circle overlaps this box.

        Uses the closest-point test: clamp the circle's centre to the box, then compare
        that distance against the radius. Strict, so tangency is not an intersection.

        This is the test that keeps a balloon off a face.

        Args:
            circle: The circle to test, typically an actor's face exclusion zone.

        Returns:
            True if the two overlap by any positive amount.
        """
        nearest_x = max(self.x, min(circle.cx, self.right))
        nearest_y = max(self.y, min(circle.cy, self.bottom))
        return math.hypot(circle.cx - nearest_x, circle.cy - nearest_y) < circle.r

    def expanded(self, margin: float) -> "BBox":
        """Return this box grown by `margin` on every side.

        Args:
            margin: Distance to add to each edge. A negative value shrinks the box, and
                a sufficiently negative one inverts it, which is not checked for.

        Returns:
            A new box, `2 * margin` wider and taller than this one.
        """
        return BBox(
            self.x - margin, self.y - margin, self.width + 2 * margin, self.height + 2 * margin
        )

    def moved_to(self, x: float, y: float) -> "BBox":
        """Return this box with the same size at a new top-left corner.

        Args:
            x: New left edge.
            y: New top edge.

        Returns:
            A new box.
        """
        return BBox(x, y, self.width, self.height)


@dataclass(frozen=True, slots=True)
class Circle:
    """A disc, used throughout as a face exclusion zone.

    A head is not a circle, but for layout purposes it is close enough and vastly
    cheaper than the alternative: every "would this balloon cover someone's face?" test
    reduces to one distance comparison.

    Attributes:
        cx: Centre x.
        cy: Centre y.
        r: Radius.

    Example:
        >>> from scenet.geom import Circle, Point
        >>> head = Circle(100.0, 100.0, 30.0)
        >>> head.contains_point(Point(110.0, 100.0))
        True
        >>> head.contains_point(Point(130.0, 100.0))
        False
    """

    cx: float
    cy: float
    r: float

    @property
    def centre(self) -> "Point":
        """The centre, as a point."""
        return Point(self.cx, self.cy)

    def contains_point(self, point: "Point") -> bool:
        """Whether a point lies strictly inside this circle.

        Args:
            point: The point to test.

        Returns:
            True if the point is inside; False if it is outside *or exactly on* the
            edge.
        """
        return math.hypot(point.x - self.cx, point.y - self.cy) < self.r

    def as_bbox(self) -> "BBox":
        """Return the smallest axis-aligned box containing this circle."""
        return BBox(self.cx - self.r, self.cy - self.r, 2 * self.r, 2 * self.r)


def segment_intersects_circle(start: Point, end: Point, circle: Circle) -> bool:
    """Whether the line segment `start` to `end` passes through a circle.

    This is the test that decides whether a straight balloon tail would cross somebody's
    face, and so whether the tail has to bend instead. Implemented by projecting the
    circle's centre onto the segment, clamped to its extent, and comparing that distance
    to the radius -- exact, and cheaper than solving the quadratic.

    Args:
        start: One end of the segment.
        end: The other end.
        circle: The obstacle.

    Returns:
        True if any part of the segment lies strictly inside the circle. A segment that
        only grazes the edge does not count.

    Example:
        >>> from scenet.geom import Circle, Point, segment_intersects_circle
        >>> face = Circle(50.0, 50.0, 20.0)
        >>> segment_intersects_circle(Point(0.0, 50.0), Point(100.0, 50.0), face)
        True
        >>> segment_intersects_circle(Point(0.0, 0.0), Point(100.0, 0.0), face)
        False

    See Also:
        [`Circle.contains_point`][scenet.geom.Circle.contains_point], which this falls
        back to for a zero-length segment.
    """
    dx, dy = end.x - start.x, end.y - start.y
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return circle.contains_point(start)

    # Project the circle centre onto the segment, clamped to its extent.
    t = ((circle.cx - start.x) * dx + (circle.cy - start.y) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    closest = Point(start.x + t * dx, start.y + t * dy)
    return math.hypot(circle.cx - closest.x, circle.cy - closest.y) < circle.r
