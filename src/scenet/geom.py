"""Geometry primitives.

A note on annotations: self- and forward-references are quoted. Before Python 3.14 and
PEP 649, a bare `-> Point` inside `class Point` is evaluated at definition time and
raises NameError, and BBox and Circle refer to each other mutually so no ordering
fixes it. `Self` is not used here: these methods construct their class by name, so
`Self` would promise subclass-preserving behaviour the bodies do not deliver.

Frozen and slotted: these are created in tight loops by the balloon placement search,
and immutability means a resolved layout cannot be mutated behind the emitter's back.

All values are in panel units. The coordinate system is SVG's: x rightward, y
*downward*, origin at the panel's top-left. Every angle is in degrees and measured
clockwise, to stay consistent with that downward y.
"""

import math
from dataclasses import dataclass

# Coordinates are rounded to this many decimals on emission. Two decimals is far below
# the visible threshold at any sane panel size, and it makes output byte-identical
# across platforms whose floating-point formatting differs in the last digit.
PRECISION = 2


def rounded(value: float) -> float:
    """Round for emission. Adding 0.0 normalises -0.0 to 0.0, which would otherwise
    produce spurious diffs in golden files."""
    return round(value, PRECISION) + 0.0


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy)

    def rotated_around(self, origin: "Point", degrees: float) -> "Point":
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        dx, dy = self.x - origin.x, self.y - origin.y
        return Point(origin.x + dx * cos - dy * sin, origin.y + dx * sin + dy * cos)

    def distance_to(self, other: "Point") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def as_tuple(self) -> tuple[float, float]:
        return (rounded(self.x), rounded(self.y))


@dataclass(frozen=True, slots=True)
class Vector:
    dx: float
    dy: float

    @property
    def length(self) -> float:
        return math.hypot(self.dx, self.dy)

    def normalised(self) -> "Vector":
        length = self.length
        if length == 0:
            # A zero vector has no direction; returning it unchanged lets callers
            # treat "no gaze" as a neutral term rather than special-casing None.
            return self
        return Vector(self.dx / length, self.dy / length)

    def mirrored_x(self) -> "Vector":
        return Vector(-self.dx, self.dy)

    def dot(self, other: "Vector") -> float:
        return self.dx * other.dx + self.dy * other.dy

    def as_tuple(self) -> tuple[float, float]:
        return (rounded(self.dx), rounded(self.dy))


@dataclass(frozen=True, slots=True)
class BBox:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def centre(self) -> "Point":
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    @property
    def area(self) -> float:
        return self.width * self.height

    def contains(self, other: "BBox") -> bool:
        return (
            other.x >= self.x
            and other.y >= self.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def overlap_area(self, other: "BBox") -> float:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def intersects_circle(self, circle: "Circle") -> bool:
        """True if the circle overlaps this box, via the closest-point test."""
        nearest_x = max(self.x, min(circle.cx, self.right))
        nearest_y = max(self.y, min(circle.cy, self.bottom))
        return math.hypot(circle.cx - nearest_x, circle.cy - nearest_y) < circle.r

    def expanded(self, margin: float) -> "BBox":
        return BBox(
            self.x - margin, self.y - margin, self.width + 2 * margin, self.height + 2 * margin
        )

    def moved_to(self, x: float, y: float) -> "BBox":
        return BBox(x, y, self.width, self.height)


@dataclass(frozen=True, slots=True)
class Circle:
    cx: float
    cy: float
    r: float

    @property
    def centre(self) -> "Point":
        return Point(self.cx, self.cy)

    def contains_point(self, point: "Point") -> bool:
        return math.hypot(point.x - self.cx, point.y - self.cy) < self.r

    def as_bbox(self) -> "BBox":
        return BBox(self.cx - self.r, self.cy - self.r, 2 * self.r, 2 * self.r)


def segment_intersects_circle(start: Point, end: Point, circle: Circle) -> bool:
    """Whether the line segment start->end passes through the circle.

    Used to decide whether a straight balloon tail would cross a face, which is the
    condition that forces a curved tail instead.
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
