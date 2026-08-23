"""Panel Core: the resolved intermediate format.

Every position is absolute and numeric, but identifiers survive -- which is what
separates this from SVG. A Core document can be read, diffed, hand-adjusted and
re-emitted.

Golden-file tests target this tier rather than the SVG, because it changes only when
layout genuinely changes. Diffing SVG text is brittle: a reordered attribute or a
different path-rounding convention produces a huge diff that means nothing.
"""

import json
from typing import Any, Self

from pydantic import BaseModel, ConfigDict

from scenet.geom import PRECISION, BBox, Circle, Point, Vector, rounded
from scenet.ir import BalloonKind

CORE_FORMAT_VERSION = 1


class CoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Transform(CoreModel):
    """Where a puppet's root joint lands, and how it is scaled and mirrored."""

    x: float
    y: float
    scale: float
    mirrored: bool


class Box(CoreModel):
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

    @classmethod
    def of(cls, bbox: BBox) -> Self:
        return cls(
            x=rounded(bbox.x),
            y=rounded(bbox.y),
            width=rounded(bbox.width),
            height=rounded(bbox.height),
        )

    def as_bbox(self) -> BBox:
        return BBox(self.x, self.y, self.width, self.height)


class Disc(CoreModel):
    cx: float
    cy: float
    r: float

    @classmethod
    def of(cls, circle: Circle) -> Self:
        return cls(cx=rounded(circle.cx), cy=rounded(circle.cy), r=rounded(circle.r))

    def as_circle(self) -> Circle:
        return Circle(self.cx, self.cy, self.r)


class Capsule(CoreModel):
    """A limb segment, as a thick line with rounded ends."""

    start: tuple[float, float]
    end: tuple[float, float]
    width: float


class Blob(CoreModel):
    centre: tuple[float, float]
    radius: float


class CoreActor(CoreModel):
    id: str
    reference: str
    pose: str
    transform: Transform
    anchors: dict[str, tuple[float, float]]
    face_exclusion: Disc
    gaze: tuple[float, float]
    hull: tuple[tuple[float, float], ...]
    capsules: tuple[Capsule, ...] = ()
    blobs: tuple[Blob, ...] = ()
    # Painter's order: lower values are drawn first, so higher values sit in front.
    depth: int = 0

    @property
    def bounds(self) -> BBox:
        xs = [x for x, _ in self.hull]
        ys = [y for _, y in self.hull]
        return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


class Tail(CoreModel):
    """The pointer from a balloon to its speaker's mouth.

    `control` is present only when the straight route was obstructed and the tail had
    to bend, which keeps the common case honest about being a simple straight line.
    """

    start: tuple[float, float]
    end: tuple[float, float]
    control: tuple[float, float] | None = None
    width: float = 14.0

    @property
    def is_curved(self) -> bool:
        return self.control is not None


class CoreBalloon(CoreModel):
    id: str
    speaker: str
    order: int
    kind: BalloonKind
    box: Box
    # The *resolved* line breaking, not the source string. Wrapping is decided during
    # compilation using real font metrics, so the emitter never re-measures and can
    # never disagree with the solver about how wide the balloon needed to be.
    lines: tuple[str, ...]
    font_size: float
    line_height: float
    tail: Tail


class PanelCore(CoreModel):
    """A fully resolved panel, ready to emit."""

    format_version: int = CORE_FORMAT_VERSION
    width: float
    height: float
    actors: tuple[CoreActor, ...] = ()
    balloons: tuple[CoreBalloon, ...] = ()

    @property
    def bounds(self) -> BBox:
        return BBox(0.0, 0.0, self.width, self.height)

    def actor(self, actor_id: str) -> CoreActor:
        for actor in self.actors:
            if actor.id == actor_id:
                return actor
        raise KeyError(f"no actor '{actor_id}' in panel")

    def to_json(self) -> str:
        """Serialise deterministically.

        Keys are sorted and floats already rounded at construction, so the same input
        yields byte-identical output on any platform. A trailing newline keeps the
        file well-formed for line-oriented tools like git diff.
        """
        payload: Any = self.model_dump(mode="json")
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Self:
        return cls.model_validate(json.loads(text))


def point_pair(point: Point) -> tuple[float, float]:
    return point.as_tuple()


def vector_pair(vector: Vector) -> tuple[float, float]:
    return vector.as_tuple()


def round_pairs(points: tuple[Point, ...]) -> tuple[tuple[float, float], ...]:
    return tuple(point.as_tuple() for point in points)


__all__ = [
    "CORE_FORMAT_VERSION",
    "PRECISION",
    "Blob",
    "Box",
    "Capsule",
    "CoreActor",
    "CoreBalloon",
    "Disc",
    "PanelCore",
    "Tail",
    "Transform",
    "point_pair",
    "round_pairs",
    "vector_pair",
]
