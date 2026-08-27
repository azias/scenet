"""Panel Core: the resolved intermediate format.

Every position is absolute and numeric, but identifiers survive -- which is what
separates this from SVG. A Core document can be read, diffed, hand-adjusted and
re-emitted.

Golden-file tests target this tier rather than the SVG, because it changes only when
layout genuinely changes. Diffing SVG text is brittle: a reordered attribute or a
different path-rounding convention produces a huge diff that means nothing.
"""

import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict

from scenet.geom import PRECISION, BBox, Circle, Point, Vector, rounded
from scenet.ir import BalloonKind, CaptionKind, MassKind, Plane, TimeOfDay, Weather

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

    The serialisable twin of :class:`BBox <scenet.geom.BBox>`. The geometry code works in
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

    Usually a face exclusion zone -- the region no balloon may cover. Also a fleck of
    falling snow, which is the same shape and wants the same rounding.

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


class FaceStroke(CoreModel):
    """One line of a drawn face, already sampled into straight segments.

    Curves are sampled during compilation rather than emitted as Bezier control
    points, so that everything an expression does is a number here. A face can then be
    read, diffed and hand-adjusted exactly like the rest of this tier, and the emitter
    has nothing left to decide.

    Attributes:
        mark: Always `stroke`. What distinguishes this from a `FaceDisc`.
        id: Which feature this draws -- `brow_l`, `mouth`, and so on.
        points: The polyline, in panel coordinates.
        width: Stroke width in panel units.
        closed: Whether the last point joins back to the first, which is what makes an
            open mouth a shape rather than a stray arc.
    """

    mark: Literal["stroke"] = "stroke"
    id: str
    points: tuple[tuple[float, float], ...]
    width: float
    closed: bool = False


class FaceDisc(CoreModel):
    """A round mark on a face -- an eye, or the pupil inside it.

    Attributes:
        mark: Always `disc`.
        id: Which feature this draws.
        centre: `(x, y)` of the centre.
        radius: Radius in panel units.
        filled: Filled marks are pupils; outlined ones are the eyes around them.
        width: Outline width in panel units, ignored when `filled`.
    """

    mark: Literal["disc"] = "disc"
    id: str
    centre: tuple[float, float]
    radius: float
    filled: bool = False
    width: float = 0.0


#: One mark on a drawn face. Tagged by a defaulted literal rather than a pydantic
#: discriminator, for the same reason `ScriptEvent` is: a discriminator would require
#: the tag in every hand-written document.
FaceMark = FaceStroke | FaceDisc


class CoreMass(CoreModel):
    """One tonal mass of the backdrop, resolved to a numeric polygon.

    The same discipline as `capsules`, `blobs` and `face_marks`: everything the emitter
    needs is a number by the time it gets here, so drawing a backdrop involves no layout
    decision at all.

    Attributes:
        id: Stable identifier, `m0`, `m1`, ... back to front.
        kind: What the mass is made of. Carried so a Core document stays readable -- it
            is not consulted when drawing, since the tone is already resolved.
        plane: How far back it sits.
        depth: Painter's order, shared with the actors. Backdrop planes are negative;
            a foreground mass sits above the frontmost actor.
        tone: The `#rrggbb` fill, already chosen from the value ladder.
        polygon: The silhouette, in panel coordinates.
    """

    id: str
    kind: MassKind
    plane: Plane
    depth: int
    tone: str
    polygon: tuple[tuple[float, float], ...]


class CoreVeil(CoreModel):
    """The atmospheric noise layer, as parameters rather than as pixels.

    SVG has Perlin noise built in through `feTurbulence`, and the specification includes
    reference code, so a fixed `seed` is reproducible **by definition**: the emitted text
    is byte-identical. Browsers agree only approximately on what to paint from it, which
    is fine and is exactly why the determinism contract is on the SVG text and has never
    been on pixels.

    Attributes:
        tone: The `#rrggbb` the veil is tinted.
        opacity: How much of it lands, `0 .. 1`.
        frequency: `baseFrequency`, per panel unit.
        octaves: `numOctaves`.
        seed: `seed`, derived from the declared content and the panel size.
    """

    tone: str
    opacity: float
    frequency: float
    octaves: int
    seed: int


class CoreStreak(CoreModel):
    """One streak of falling rain.

    The width is on :class:`CoreAtmosphere <scenet.core.CoreAtmosphere>` rather than
    here: every streak in a panel shares it, and repeating it per streak would make the
    file longer without making it say anything more.
    """

    start: tuple[float, float]
    end: tuple[float, float]


class CoreAtmosphere(CoreModel):
    """What the air is doing, resolved.

    Attributes:
        time: When the panel happens. Recorded rather than re-derived, for the same
            reason `CoreCaption.italic` is: the emitter must not be able to draw
            something the solver did not resolve.
        weather: What is falling, if anything.
        tone: The atmosphere's own value at this hour.
        veil: The noise layer -- fog, or cloud for rain and snow.
        streaks: Rain, every streak at the same angle.
        flecks: Snow.
        streak_width: Stroke width for a streak, in panel units.
        fall_tone: What rain and snow are drawn in -- ink over a bright sky, paper over
            a dark one. Resolved rather than left to the emitter, because which one
            reads is a fact about this panel.
    """

    time: TimeOfDay
    weather: Weather
    tone: str
    veil: CoreVeil | None = None
    streaks: tuple[CoreStreak, ...] = ()
    flecks: tuple[Disc, ...] = ()
    streak_width: float = 0.0
    fall_tone: str = ""


class CoreBackdrop(CoreModel):
    """Where the panel is, resolved: masses, tones, and the air.

    Attributes:
        horizon: Where the ground meets what is behind it, in panel units.
        seed: What every silhouette in here was generated from. Kept so that a Core
            document explains itself: two panels with the same masses and different
            skylines differ here, and here is where to look.
        masses: The tonal masses, back to front.
        atmosphere: The air, or None when the weather is clear.

    Optional on :class:`PanelCore <scenet.core.PanelCore>`, so every document written
    before this existed is still a valid one -- which is why adding it did not need a
    `format_version` bump, the same argument captions made.
    """

    horizon: float
    seed: int
    masses: tuple[CoreMass, ...] = ()
    atmosphere: CoreAtmosphere | None = None


class CoreActor(CoreModel):
    """One character, fully resolved: placed, posed, scaled and measured.

    This is the geometric contract in its final form. Everything the emitter needs to
    draw the figure, and everything the balloon placer needed to avoid it, with no
    reference to artwork of any kind.

    Attributes:
        id: The actor id from the panel source.
        reference: Which puppet was used. Two actors may share one.
        pose: Which named pose was applied.
        expression: Which named expression was applied.
        transform: Where the root joint landed, and the scale and mirroring applied.
        anchors: Named attachment points -- `mouth`, `eyes`, and whatever else the
            puppet declared -- already in panel coordinates.
        face_exclusion: The disc no balloon may overlap.
        gaze: Unit direction the character is facing, `(dx, dy)`. Derived from the
            head's rotation, and what balloon placement reads to keep out of a line of
            sight.
        gaze_aim: Unit direction from the eyes to whoever this character is
            `looking_at`, or None when they are looking at nobody. Separate from
            `gaze` because it is known only after every actor has been placed, and
            because balloon placement must go on reading the same vector it always
            has. This is what aims the pupils.
        face_marks: The drawn face -- brows, eyes, pupils, nose, mouth -- as resolved
            numeric primitives. Empty when the puppet declares no features, or when
            the figure is too small for features to read as anything but a smudge.
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
    expression: str = "neutral"
    gaze_aim: tuple[float, float] | None = None
    face_marks: tuple[FaceMark, ...] = ()
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


class CoreCaption(CoreModel):
    """One caption box, placed and with its lettering already broken into lines.

    Attributes:
        id: Stable identifier, `c0`, `c1`, ... in the order the captions appear.
        order: Position in the panel's reading order. Captions and balloons share one
            sequence, so a caption written between two lines of dialogue takes the
            number between theirs.
        kind: What the box is doing, which is what decides how it is set.
        box: Where it sits.
        lines: The **resolved** line breaking, quotation marks included. A `spoken`
            caption's quotes are part of the text by the time it reaches here, because
            marks added after measurement would not fit the box drawn for them.
        font_size: Type size in panel units.
        line_height: Baseline-to-baseline distance in panel units.
        italic: Whether the lettering is set in the italic face. Recorded rather than
            re-derived from `kind` so the emitter cannot draw the box in a face the
            solver did not measure it in.
        fill: The value the box is filled with, resolved from the declared tone.
        ink: The value the lettering is drawn in. Chosen against `fill` by contrast, so
            a dark box is lettered in paper -- reversed type. Resolved rather than left
            to the emitter for the same reason `italic` is, and the same reason
            :attr:`CoreAtmosphere.fall_tone <scenet.core.CoreAtmosphere>` is: which
            mark reads is a fact about the panel.
        speaker: Who is talking, for a `spoken` caption. **Not an actor id**: the
            speaker is off panel, so this resolves to nobody in `actors`.

    There is no tail. That is the difference that makes this its own type rather than
    a fifth :class:`BalloonKind <scenet.ir.BalloonKind>`.

    `fill` and `ink` are defaulted to the white and the near-black every caption has
    had since captions shipped, so a Core document written before tones existed is
    still a valid one -- which is why adding them needed no `format_version` bump.
    """

    id: str
    order: int
    kind: CaptionKind
    box: Box
    lines: tuple[str, ...]
    font_size: float
    line_height: float
    italic: bool
    fill: str = "#ffffff"
    ink: str = "#111111"
    speaker: str | None = None


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
        captions: Resolved caption boxes, in reading order. Balloons and captions
            share one `order` sequence, since the reader takes them in one sequence.
        backdrop: Where the panel is, or None when it says nothing about that -- which
            is every panel written before the setting layer existed.

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
    captions: tuple[CoreCaption, ...] = ()
    backdrop: CoreBackdrop | None = None

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

        The inverse of :meth:`to_json <scenet.core.PanelCore.to_json>`, and the reason Panel
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
    "CoreAtmosphere",
    "CoreBackdrop",
    "CoreBalloon",
    "CoreCaption",
    "CoreMass",
    "CoreStreak",
    "CoreVeil",
    "Disc",
    "FaceDisc",
    "FaceMark",
    "FaceStroke",
    "PanelCore",
    "Tail",
    "Transform",
    "point_pair",
    "round_pairs",
    "vector_pair",
]
