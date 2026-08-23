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
    """Base for every Panel Core type: frozen, and rejecting unknown keys.

    Strictness matters more here than in the IR. A Core document is something a user
    may hand-edit and feed back in, and a silently-ignored key would mean their edit
    had no effect with nothing to say so.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class Transform(CoreModel):
    """Where a puppet's root joint lands, and how it is scaled and mirrored."""

    x: float
    y: float
    scale: float
    mirrored: bool


class Box(CoreModel):
    """A rectangle, as stored in a Core document.

    The serialisable twin of [`BBox`][scenet.geom.BBox]. The geometry code works in
    `BBox`; this is what gets written to JSON, with every value already rounded so the
    file is byte-identical across platforms.

    Attributes:
        x: Left edge.
        y: Top edge.
        width: Extent rightward.
        height: Extent downward.
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
        """The bottom edge, `y + height`."""
        return self.y + self.height

    @classmethod
    def of(cls, bbox: BBox) -> Self:
        """Build a `Box` from a geometry `BBox`, rounding for emission.

        Args:
            bbox: The box to convert.

        Returns:
            The serialisable equivalent, with all four values rounded.
        """
        return cls(
            x=rounded(bbox.x),
            y=rounded(bbox.y),
            width=rounded(bbox.width),
            height=rounded(bbox.height),
        )

    def as_bbox(self) -> BBox:
        """Convert back to a geometry `BBox` for further computation."""
        return BBox(self.x, self.y, self.width, self.height)


class Disc(CoreModel):
    """A circle, as stored in a Core document.

    In practice always a face exclusion zone -- the region no balloon may cover.

    Attributes:
        cx: Centre x.
        cy: Centre y.
        r: Radius.
    """

    cx: float
    cy: float
    r: float

    @classmethod
    def of(cls, circle: Circle) -> Self:
        """Build a `Disc` from a geometry `Circle`, rounding for emission.

        Args:
            circle: The circle to convert.

        Returns:
            The serialisable equivalent.
        """
        return cls(cx=rounded(circle.cx), cy=rounded(circle.cy), r=rounded(circle.r))

    def as_circle(self) -> Circle:
        """Convert back to a geometry `Circle` for further computation."""
        return Circle(self.cx, self.cy, self.r)


class Capsule(CoreModel):
    """A limb segment, as a thick line with rounded ends."""

    start: tuple[float, float]
    end: tuple[float, float]
    width: float


class Blob(CoreModel):
    """A rounded mass -- a head, a hand -- drawn as a filled circle.

    Attributes:
        centre: `(x, y)` of the centre.
        radius: Radius in panel units.
    """

    centre: tuple[float, float]
    radius: float


class CoreActor(CoreModel):
    """One character, fully resolved: placed, posed, scaled and measured.

    This is the geometric contract in its final form. Everything the emitter needs to
    draw the figure, and everything the balloon placer needed to avoid it, with no
    reference to artwork of any kind.

    Attributes:
        id: The actor id from the panel source.
        reference: Which puppet was used. Two actors may share one.
        pose: Which named pose was applied.
        transform: Where the root joint landed, and the scale and mirroring applied.
        anchors: Named attachment points -- `mouth`, `eyes`, and whatever else the
            puppet declared -- already in panel coordinates.
        face_exclusion: The disc no balloon may overlap.
        gaze: Unit direction the character is looking, `(dx, dy)`.
        hull: Convex silhouette, used for the soft occlusion cost.
        capsules: Limb segments, as thick rounded lines.
        blobs: Rounded masses such as the head.
        depth: Painter's order. Lower is drawn first, so higher sits in front.
    """

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
        """Axis-aligned bounds of the silhouette."""
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
        """Whether this tail had to bend around an obstacle."""
        return self.control is not None


class CoreBalloon(CoreModel):
    """One balloon, placed and with its lettering already broken into lines.

    Attributes:
        id: Stable identifier, `b0`, `b1`, ... in script order.
        speaker: Actor id of whoever is talking.
        order: Position in reading order, counting from zero.
        kind: Which sort of balloon to draw.
        box: Where it sits.
        lines: The **resolved** line breaking, not the source string.
        font_size: Type size in panel units.
        line_height: Baseline-to-baseline distance in panel units.
        tail: The pointer to the speaker's mouth.

    Storing broken lines rather than the original string is deliberate. Wrapping is
    decided during compilation against real font metrics; if the emitter re-measured,
    it could disagree with the solver about how wide the balloon needed to be, and the
    text would overflow the shape drawn for it.
    """

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
    """A fully resolved panel: numeric, named, and ready to emit.

    The middle tier, and the architectural idea of the project. Every position here is
    absolute and final, but **identifiers survive** -- which is exactly what separates
    this from SVG. You can read a Core document, see that `alice` sits at x=280 with her
    balloon top-left of her head, change one number, and emit it again.

    The approach is borrowed from Vega-Lite, which compiles a high-level grammar into a
    lower-level one before emitting anything drawable.

    Attributes:
        format_version: Bumped when the shape of this document changes incompatibly.
        width: Panel width in panel units.
        height: Panel height in panel units.
        actors: Resolved characters, in declaration order.
        balloons: Resolved balloons, in reading order.

    Golden-file tests target this tier rather than the SVG, because it changes only when
    the layout genuinely changes. Diffing SVG text is brittle -- a reordered attribute or
    a different path-rounding convention produces an enormous diff that means nothing.

    Example:
        >>> from scenet import compile_source
        >>> core = compile_source("{cast: {a: {reference: alice}}}").core
        >>> core.width, core.height
        (1000.0, 1000.0)
        >>> core.actor("a").reference
        'alice'
        >>> core.to_json().splitlines()[0]
        '{'
    """

    format_version: int = CORE_FORMAT_VERSION
    width: float
    height: float
    actors: tuple[CoreActor, ...] = ()
    balloons: tuple[CoreBalloon, ...] = ()

    @property
    def bounds(self) -> BBox:
        """The panel rectangle, origin at `(0, 0)`."""
        return BBox(0.0, 0.0, self.width, self.height)

    def actor(self, actor_id: str) -> CoreActor:
        """Look up one actor by id.

        Args:
            actor_id: The id used in the panel source.

        Returns:
            That actor.

        Raises:
            KeyError: No actor in this panel has that id.
        """
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
        """Read a Core document back in.

        The inverse of [`to_json`][scenet.core.PanelCore.to_json], and the reason Panel
        Core is a real format rather than a private data structure: a layout can be
        exported, adjusted by hand or by another tool, and read back for emission.

        Args:
            text: A Core document.

        Returns:
            The parsed panel.

        Raises:
            pydantic.ValidationError: The document is not a valid Core panel.
            json.JSONDecodeError: The text is not JSON at all.
        """
        return cls.model_validate(json.loads(text))


def point_pair(point: Point) -> tuple[float, float]:
    """Convert a point to the rounded `(x, y)` pair a Core document stores."""
    return point.as_tuple()


def vector_pair(vector: Vector) -> tuple[float, float]:
    """Convert a vector to the rounded `(dx, dy)` pair a Core document stores."""
    return vector.as_tuple()


def round_pairs(points: tuple[Point, ...]) -> tuple[tuple[float, float], ...]:
    """Convert a sequence of points -- a hull, typically -- to rounded pairs."""
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
