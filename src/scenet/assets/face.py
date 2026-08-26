"""Drawing a face: feature points plus an expression, resolved into marks.

This is artwork, which is why it lives in the asset layer and not in `solve`. The
solver sees a face as one disc it may not cover, and that is all it will ever see --
the marks here could be replaced by hand-drawn artwork exposing the same feature
points and nothing about layout would change.

**Curves are sampled to polylines here, not in the emitter.** Every consequence of an
expression is therefore a number in Panel Core: a face can be read, diffed and
hand-adjusted like everything else at that tier, and the emitter stays mechanical.

Level of detail is a real constraint rather than an optimisation. At `long_shot` a
head is a couple of dozen panel units across, and five features inside it stop being
a face and become a smudge. Below `MIN_FEATURE_RADIUS` nothing is drawn at all, which
is what a cartoonist does too.
"""

import math
from dataclasses import dataclass

from scenet.assets.contract import BrowState, ExpressionSpec, EyeState, Feature, MouthState
from scenet.assets.kinematics import ResolvedFeature, ResolvedPuppet
from scenet.geom import Point, Vector

#: Face radius in panel units below which no features are drawn. Calibrated by eye
#: against the contact sheet -- `scripts/contact_sheet.py` renders every expression at
#: every shot type for exactly this decision.
MIN_FEATURE_RADIUS = 22.0

#: Pupil radius, as a fraction of the drawn eye radius.
PUPIL_FRACTION = 0.34

#: How far a pupil travels toward the edge of the eye when the character is looking at
#: somebody, as a fraction of the room it has. Short of 1.0 so an aimed eye still reads
#: as an eye rather than as a pupil escaping.
PUPIL_TRAVEL = 0.75

#: Stroke width of a face mark, as a fraction of the face radius. Proportional rather
#: than fixed so that a face drawn small does not end up with lines as heavy as a face
#: drawn large.
STROKE_FRACTION = 0.055

CURVE_SAMPLES = 10
ELLIPSE_SAMPLES = 16


@dataclass(frozen=True, slots=True)
class ResolvedStroke:
    """A line of the face, already sampled into straight segments."""

    id: str
    points: tuple[Point, ...]
    width: float
    closed: bool = False


@dataclass(frozen=True, slots=True)
class ResolvedDisc:
    """A round mark -- an eye, a pupil."""

    id: str
    centre: Point
    radius: float
    filled: bool = False
    width: float = 0.0


FaceMark = ResolvedStroke | ResolvedDisc


def build_face(
    puppet: ResolvedPuppet, states: ExpressionSpec, aim: Vector | None = None
) -> tuple[FaceMark, ...]:
    """Draw one face.

    Args:
        puppet: The posed figure, whose `features` say where everything sits.
        states: What each feature is doing.
        aim: Unit vector from the eyes toward whatever the character is looking at, or
            None when they are looking at nobody in particular. Pupils are offset along
            it, which is the only thing that makes a gaze relation visible on the page.

    Returns:
        Marks in a fixed order -- brows, eyes, pupils, nose, mouth -- so that the same
        face always serialises to the same bytes.

    Example:
        >>> from scenet import compile_source
        >>> core = compile_source(
        ...     "{camera: {shot: close_up}, cast: {a: {reference: alice, expression: angry}}}"
        ... ).core
        >>> any(mark.id == "mouth" for mark in core.actor("a").face_marks)
        True
    """
    if puppet.face.r < MIN_FEATURE_RADIUS or not puppet.features:
        return ()

    width = max(puppet.face.r * STROKE_FRACTION, 0.5)
    side = 1.0 if puppet.facing_right else -1.0
    marks: list[FaceMark] = []

    for feature in (Feature.BROW_L, Feature.BROW_R):
        point = puppet.features.get(feature)
        if point is not None:
            marks.append(_brow(feature, point, states.brow, puppet.face.cx, width))

    for feature in (Feature.EYE_L, Feature.EYE_R):
        point = puppet.features.get(feature)
        if point is not None:
            marks.extend(_eye(feature, point, states.eyes, aim, width))

    nose = puppet.features.get(Feature.NOSE)
    if nose is not None:
        marks.append(_nose(nose, side, width))

    mouth = puppet.features.get(Feature.MOUTH)
    if mouth is not None:
        marks.append(_mouth(mouth, states.mouth, width))

    return tuple(marks)


# Per state: how far the whole brow shifts vertically, how far its inner and outer ends
# move, and how much it arches -- all as multiples of the brow's half-width. Positive y
# is downward, so a negative shift raises.
_BROWS: dict[BrowState, tuple[float, float, float, float]] = {
    BrowState.NEUTRAL: (0.0, 0.0, 0.0, -0.18),
    BrowState.RAISED: (-0.45, 0.0, 0.0, -0.35),
    BrowState.LOWERED: (0.30, 0.0, 0.0, -0.05),
    BrowState.ANGLED_IN: (0.0, 0.45, -0.15, 0.0),
    BrowState.ANGLED_OUT: (0.0, -0.45, 0.15, 0.0),
}


def _brow(
    feature: Feature, point: ResolvedFeature, state: BrowState, face_cx: float, width: float
) -> ResolvedStroke:
    """One eyebrow, as a three-point line.

    Inner and outer are resolved against the face centre rather than against the
    screen, so an angry brow stays angry when the figure is mirrored.
    """
    shift, inner_dy, outer_dy, arch = _BROWS[state]
    half = point.size
    inward = -1.0 if point.centre.x > face_cx else 1.0
    base_y = point.centre.y + shift * half

    inner = Point(point.centre.x + inward * half, base_y + inner_dy * half)
    outer = Point(point.centre.x - inward * half, base_y + outer_dy * half)
    middle = Point((inner.x + outer.x) / 2, (inner.y + outer.y) / 2 + arch * half)
    return ResolvedStroke(id=feature.value, points=(inner, middle, outer), width=width)


# Per state: the drawn eye radius as a multiple of the declared one, how flattened it
# is, and how far the pupil sits below centre.
_EYES: dict[EyeState, tuple[float, float, float]] = {
    EyeState.OPEN: (1.0, 1.0, 0.0),
    EyeState.WIDE: (1.25, 1.0, 0.0),
    EyeState.NARROWED: (1.0, 0.45, 0.0),
    EyeState.HALF: (1.0, 0.60, 0.18),
    EyeState.CLOSED: (1.0, 0.0, 0.0),
}


def _eye(
    feature: Feature,
    point: ResolvedFeature,
    state: EyeState,
    aim: Vector | None,
    width: float,
) -> list[FaceMark]:
    """One eye and its pupil.

    A round eye is a disc and a squeezed one is a sampled ellipse, because a disc
    cannot express the flattening -- and a closed eye is neither, it is a single
    downward curve, which is how a closed eye has always been drawn.
    """
    scale, flatten, pupil_drop = _EYES[state]
    radius = point.size * scale
    centre = point.centre
    side = feature.value[-1]

    if state is EyeState.CLOSED:
        return [
            ResolvedStroke(
                id=feature.value,
                points=_quadratic(
                    Point(centre.x - radius, centre.y),
                    Point(centre.x, centre.y + radius * 0.85),
                    Point(centre.x + radius, centre.y),
                ),
                width=width,
            )
        ]

    marks: list[FaceMark] = []
    if flatten == 1.0:
        marks.append(ResolvedDisc(id=feature.value, centre=centre, radius=radius, width=width))
    else:
        marks.append(
            ResolvedStroke(
                id=feature.value,
                points=_ellipse(centre, radius, radius * flatten),
                width=width,
                closed=True,
            )
        )

    pupil_radius = radius * PUPIL_FRACTION
    travel = max(radius * flatten - pupil_radius, 0.0) * PUPIL_TRAVEL
    dx = aim.dx * travel if aim is not None else 0.0
    dy = aim.dy * travel if aim is not None else 0.0
    marks.append(
        ResolvedDisc(
            id=f"pupil_{side}",
            centre=centre.translated(dx, dy + radius * pupil_drop),
            radius=pupil_radius,
            filled=True,
        )
    )
    return marks


def _nose(point: ResolvedFeature, side: float, width: float) -> ResolvedStroke:
    """A nose: a short stroke with a hook, turned the way the figure faces."""
    length = point.size
    centre = point.centre
    return ResolvedStroke(
        id=Feature.NOSE.value,
        points=(
            Point(centre.x, centre.y - length * 0.45),
            Point(centre.x, centre.y + length * 0.30),
            Point(centre.x + side * length * 0.30, centre.y + length * 0.45),
        ),
        width=width,
    )


def _mouth(point: ResolvedFeature, state: MouthState, width: float) -> ResolvedStroke:
    """The mouth, as one line or one closed shape.

    Positive y is downward, so a curve whose middle sags below its ends is a smile and
    one whose middle rises above them is a frown.
    """
    half = point.size
    centre = point.centre

    def at(x: float, y: float) -> Point:
        return Point(centre.x + x * half, centre.y + y * half)

    if state is MouthState.FLAT:
        return ResolvedStroke(id="mouth", points=(at(-1.0, 0.0), at(1.0, 0.0)), width=width)
    if state is MouthState.NEUTRAL:
        points = _quadratic(at(-0.5, 0.0), at(0.0, 0.12), at(0.5, 0.0))
    elif state is MouthState.SMILE:
        points = _quadratic(at(-0.85, -0.10), at(0.0, 0.75), at(0.85, -0.10))
    elif state is MouthState.FROWN:
        points = _quadratic(at(-0.85, 0.15), at(0.0, -0.70), at(0.85, 0.15))
    elif state is MouthState.SMALL:
        points = _quadratic(at(-0.40, 0.0), at(0.0, 0.28), at(0.40, 0.0))
    elif state is MouthState.OPEN:
        return ResolvedStroke(
            id="mouth",
            points=_ellipse(centre, half * 0.62, half * 0.72),
            width=width,
            closed=True,
        )
    else:  # MouthState.GRIN -- an open smile: a straight top, a sagging bottom.
        points = (at(-0.85, 0.0), *_quadratic(at(-0.85, 0.0), at(0.0, 1.05), at(0.85, 0.0)))
        return ResolvedStroke(id="mouth", points=points, width=width, closed=True)

    return ResolvedStroke(id="mouth", points=points, width=width)


def _quadratic(start: Point, control: Point, end: Point) -> tuple[Point, ...]:
    """Sample a quadratic Bezier into straight segments."""
    points: list[Point] = []
    for step in range(CURVE_SAMPLES + 1):
        t = step / CURVE_SAMPLES
        inverse = 1 - t
        points.append(
            Point(
                inverse * inverse * start.x + 2 * inverse * t * control.x + t * t * end.x,
                inverse * inverse * start.y + 2 * inverse * t * control.y + t * t * end.y,
            )
        )
    return tuple(points)


def _ellipse(centre: Point, rx: float, ry: float) -> tuple[Point, ...]:
    """Sample an ellipse into a closed polyline."""
    return tuple(
        Point(
            centre.x + math.cos(2 * math.pi * step / ELLIPSE_SAMPLES) * rx,
            centre.y + math.sin(2 * math.pi * step / ELLIPSE_SAMPLES) * ry,
        )
        for step in range(ELLIPSE_SAMPLES)
    )
