"""Drawing emanata: the marks around a character that say what state they are in.

Plewds, squeans, grawlixes and briffits -- Mort Walker's names, from *The Lexicon of
Comicana*. See :class:`Mark <scenet.ir.Mark>` for what each one says.

Like a face, this is artwork, and lives in the asset layer for the same reason. Unlike
a face, it is drawn **outside** the head circle, in the space balloons are placed in,
so it has to say something to the solver. What it says is a **zone** per mark: a convex
polygon around everything that mark draws. The solver reads the zones as a soft cost
and never sees a plewd. Replace these drawings with hand-drawn ones that occupy the
same zones and no layout changes.

Emanata never enter the hull. The hull is what staging spaces characters by, so a
sweating character would otherwise stand further from everyone else, and the camera
might retreat to fit them -- a mark that moved the people in a panel would be saying
something the author never wrote.

Everything is placed from the face circle, the facing direction and the feet landmark,
which every puppet has. So marks need nothing from a puppet beyond the contract it
already meets, and are not declared per puppet the way expressions are.

**Level of detail** follows the face's rule. A plewd at `long_shot` is a dot: below
`MIN_EMANATA_DETAIL`, each symbol collapses to a filled dot where it would have been
drawn. Below the face's own `MIN_FEATURE_RADIUS`, nothing is drawn -- a character too
small to have a face is too small to be sweating.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from scenet.assets.contract import Landmark
from scenet.assets.face import MIN_FEATURE_RADIUS, FaceMark, ResolvedDisc, ResolvedStroke
from scenet.assets.kinematics import ResolvedPuppet, convex_hull
from scenet.geom import Point
from scenet.ir import Mark

#: Face radius in panel units below which emanata are drawn as dots rather than as
#: shapes. Calibrated by eye against `scripts/contact_sheet.py --marks`: in a
#: 1000-unit panel, `full_shot` (a face radius of about 75) still draws a plewd you
#: can tell is a drop, and `long_shot` (about 51) does not.
MIN_EMANATA_DETAIL = 60.0

#: Stroke width, as a fraction of the face radius. Lighter than a face's own lines:
#: these are small symbols, and drawn at face weight they clot into blots.
STROKE_FRACTION = 0.035

#: How far a zone reaches past what it encloses, as a fraction of the face radius, on
#: top of the stroke width. Enough that a balloon cannot sit flush against a mark.
ZONE_PADDING = 0.05

#: Points sampled around each disc and each padded point when a zone is built. Eight
#: is plenty: the zone feeds a soft cost, not a hard edge.
ZONE_SAMPLES = 8

#: How a drop is sampled: points along its rounded end. Odd, so the samples are
#: symmetric about the drop's own axis and a mirrored figure's sweat is the exact
#: reflection of the original.
DROP_SAMPLES = 11

SPIRAL_SAMPLES = 28

#: The id each mark's primitives are numbered under, `plewd_0`, `plewd_1`, ...
SINGULAR: dict[Mark, str] = {
    Mark.PLEWDS: "plewd",
    Mark.SQUEANS: "squean",
    Mark.GRAWLIXES: "grawlix",
    Mark.BRIFFITS: "briffit",
}


@dataclass(frozen=True, slots=True)
class ResolvedEmanata:
    """Every mark drawn around one character, and the space they take up.

    Attributes:
        marks: The drawing, as the same strokes and discs a face is made of, in a fixed
            order -- by mark, then by position -- so the same marks always serialise
            to the same bytes.
        zones: One convex polygon per mark, enclosing everything it draws. This is the
            whole of what the solver sees.
    """

    marks: tuple[FaceMark, ...] = ()
    zones: tuple[tuple[Point, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class _Symbol:
    """One symbol before it is drawn: where it goes, and how to draw it in full.

    The split is what makes level of detail a one-line decision. A dot needs only the
    centre and the size; the full drawing needs everything.
    """

    centre: Point
    # Radius of the dot this collapses to when the figure is too small for detail, or
    # None if it is left out altogether -- a speed line shrunk to a dot is a speck.
    dot: float | None
    draw: Callable[[float], list[FaceMark]]
    # Whether the simplest drawing of this symbol is still the full one -- a puff of
    # dust is already as simple as a puff of dust gets.
    keeps_shape: bool = False


def build_emanata(puppet: ResolvedPuppet, marks: tuple[Mark, ...]) -> ResolvedEmanata:
    """Draw the marks around one character.

    Args:
        puppet: The posed figure. Its face circle, facing and feet are all that is read.
        marks: Which marks to draw. Order does not matter.

    Returns:
        The drawing and its zones, or nothing at all when there are no marks or the
        figure is too small for them to read.

    Example:
        >>> from scenet import compile_source
        >>> core = compile_source(
        ...     "{camera: {shot: medium_shot}, cast: {a: {reference: alice, marks: [plewds]}}}"
        ... ).core
        >>> core.actor("a").emanata[0].id
        'plewd_0'
    """
    radius = puppet.face.r
    if not marks or radius < MIN_FEATURE_RADIUS:
        return ResolvedEmanata()

    detailed = radius >= MIN_EMANATA_DETAIL
    width = max(radius * STROKE_FRACTION, 0.5)
    drawn: list[FaceMark] = []
    zones: list[tuple[Point, ...]] = []

    for mark in sorted(set(marks)):
        primitives: list[FaceMark] = []
        for symbol in _SYMBOLS[mark](puppet):
            if detailed or symbol.keeps_shape:
                primitives.extend(symbol.draw(width))
            elif symbol.dot is not None:
                primitives.append(
                    ResolvedDisc(id="", centre=symbol.centre, radius=symbol.dot, filled=True)
                )
        named = [
            _named(primitive, f"{SINGULAR[mark]}_{index}")
            for index, primitive in enumerate(primitives)
        ]
        drawn.extend(named)
        zones.append(_zone(named, width + radius * ZONE_PADDING))

    return ResolvedEmanata(marks=tuple(drawn), zones=tuple(zones))


# -- where each mark goes ---------------------------------------------------------------
#
# Positions are angles round the face, in degrees clockwise from straight up, and
# distances in face radii. Head marks sit just past the exclusion circle -- which is
# what makes them emanata rather than features -- and no further. The camera frames by
# body landmarks and leaves about 1.4 face radii above the face centre from `full_shot`
# to `medium_shot`, so a mark that reached further would be cropped by the panel edge
# at exactly the framings these are most often drawn at. Tighter shots crop them, as
# they crop everything else above the head.


def _around(puppet: ResolvedPuppet, degrees: float, distance: float, side: float) -> Point:
    """A point round the face. `side` is +1 for screen right, -1 for screen left."""
    face = puppet.face
    angle = math.radians(degrees)
    return Point(
        face.cx + side * math.sin(angle) * distance * face.r,
        face.cy - math.cos(angle) * distance * face.r,
    )


def _behind(puppet: ResolvedPuppet) -> float:
    """The screen side behind a figure: -1 when they face right, +1 when they face left."""
    return -1.0 if puppet.facing_right else 1.0


# Plewds: two off the back of the head and one off the front. Mostly behind, because
# the side a character faces is the side their gaze and their balloons want. Each is
# (+1 behind or -1 in front, angle, distance).
_PLEWD_SLOTS = ((1.0, 34.0, 1.2), (1.0, 74.0, 1.24), (-1.0, 44.0, 1.2))
_PLEWD_LENGTH = 0.32
_PLEWD_WIDTH = 0.19


def _plewds(puppet: ResolvedPuppet) -> list[_Symbol]:
    behind = _behind(puppet)
    symbols: list[_Symbol] = []
    for side, degrees, distance in _PLEWD_SLOTS:
        centre = _around(puppet, degrees, distance, side * behind)
        outward = _unit(puppet.face.centre, centre)
        length = _PLEWD_LENGTH * puppet.face.r
        thickness = _PLEWD_WIDTH * puppet.face.r
        symbols.append(
            _Symbol(
                centre=centre,
                dot=0.07 * puppet.face.r,
                draw=_drop_drawer(centre, outward, length, thickness),
            )
        )
    return symbols


def _drop_drawer(
    centre: Point, outward: tuple[float, float], length: float, thickness: float
) -> Callable[[float], list[FaceMark]]:
    """A teardrop flying away from the head: round end leading, point trailing."""

    def draw(width: float) -> list[FaceMark]:
        ux, uy = outward
        vx, vy = -uy, ux
        rho = thickness / 2
        reach = length - rho
        bulb = Point(centre.x + ux * (length / 2 - rho), centre.y + uy * (length / 2 - rho))
        tip = Point(centre.x - ux * length / 2, centre.y - uy * length / 2)
        # The rounded end runs between the two points where a line from the tip just
        # touches it, so the sides of the drop are straight and meet the curve cleanly.
        sweep = math.pi - math.acos(rho / reach)
        points = [tip]
        for step in range(DROP_SAMPLES):
            phi = -sweep + 2 * sweep * step / (DROP_SAMPLES - 1)
            points.append(
                Point(
                    bulb.x + rho * (math.cos(phi) * ux + math.sin(phi) * vx),
                    bulb.y + rho * (math.cos(phi) * uy + math.sin(phi) * vy),
                )
            )
        return [ResolvedStroke(id="", points=tuple(points), width=width, closed=True)]

    return draw


# Squeans: an arc over the head, starbursts alternating with little circles.
_SQUEAN_SLOTS = (-62.0, -31.0, 0.0, 31.0, 62.0)
_SQUEAN_DISTANCE = 1.14
_STAR_SIZE = 0.09
_CIRCLE_SIZE = 0.045


def _squeans(puppet: ResolvedPuppet) -> list[_Symbol]:
    radius = puppet.face.r
    symbols: list[_Symbol] = []
    for index, degrees in enumerate(_SQUEAN_SLOTS):
        centre = _around(puppet, degrees, _SQUEAN_DISTANCE, 1.0)
        if index % 2 == 0:
            draw = _starburst_drawer(centre, _STAR_SIZE * radius)
        else:
            draw = _circle_drawer(centre, _CIRCLE_SIZE * radius)
        symbols.append(_Symbol(centre=centre, dot=0.05 * radius, draw=draw))
    return symbols


def _starburst_drawer(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    """Three short strokes crossing at a point: six spokes."""

    def draw(width: float) -> list[FaceMark]:
        strokes: list[FaceMark] = []
        for degrees in (90.0, 30.0, 150.0):
            dx = math.cos(math.radians(degrees)) * size
            dy = math.sin(math.radians(degrees)) * size
            strokes.append(
                ResolvedStroke(
                    id="",
                    points=(centre.translated(-dx, -dy), centre.translated(dx, dy)),
                    width=width,
                )
            )
        return strokes

    return draw


def _circle_drawer(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    def draw(width: float) -> list[FaceMark]:
        return [ResolvedDisc(id="", centre=centre, radius=size, width=width)]

    return draw


# Grawlixes: a row of symbols over the head. Two are Walker's own -- a jarn is a spiral,
# a nittle a bursting star -- with the bolt and the hash every cartoonist adds.
_GRAWLIX_SLOTS = (-50.0, -17.0, 17.0, 50.0)
_GRAWLIX_DISTANCE = 1.15
_GRAWLIX_SIZE = 0.1


def _grawlixes(puppet: ResolvedPuppet) -> list[_Symbol]:
    size = _GRAWLIX_SIZE * puppet.face.r
    drawers = (_jarn, _nittle, _bolt, _hash)
    symbols: list[_Symbol] = []
    for degrees, drawer in zip(_GRAWLIX_SLOTS, drawers, strict=True):
        centre = _around(puppet, degrees, _GRAWLIX_DISTANCE, 1.0)
        symbols.append(_Symbol(centre=centre, dot=0.07 * puppet.face.r, draw=drawer(centre, size)))
    return symbols


def _jarn(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    """A spiral, two and a quarter turns out from the centre."""

    def draw(width: float) -> list[FaceMark]:
        points = tuple(
            Point(
                centre.x + math.cos(2 * math.pi * 2.25 * t) * size * t,
                centre.y + math.sin(2 * math.pi * 2.25 * t) * size * t,
            )
            for t in (step / (SPIRAL_SAMPLES - 1) for step in range(SPIRAL_SAMPLES))
        )
        return [ResolvedStroke(id="", points=points, width=width)]

    return draw


def _nittle(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    """A five-pointed star."""

    def draw(width: float) -> list[FaceMark]:
        points = tuple(
            Point(
                centre.x
                + math.cos(math.radians(-90 + 36 * step)) * size * (1.0 if step % 2 == 0 else 0.42),
                centre.y
                + math.sin(math.radians(-90 + 36 * step)) * size * (1.0 if step % 2 == 0 else 0.42),
            )
            for step in range(10)
        )
        return [ResolvedStroke(id="", points=points, width=width, closed=True)]

    return draw


# A lightning bolt, in units of the symbol's half-size.
_BOLT = ((0.30, -1.0), (-0.45, 0.12), (0.02, 0.12), (-0.30, 1.0), (0.45, -0.12), (-0.02, -0.12))


def _bolt(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    def draw(width: float) -> list[FaceMark]:
        points = tuple(centre.translated(x * size, y * size) for x, y in _BOLT)
        return [ResolvedStroke(id="", points=points, width=width, closed=True)]

    return draw


def _hash(centre: Point, size: float) -> Callable[[float], list[FaceMark]]:
    """`#`, as four strokes: two leaning uprights, two crossbars."""

    def draw(width: float) -> list[FaceMark]:
        lean, bar = 0.18 * size, 0.38 * size
        lines = (
            ((-bar + lean, -size), (-bar - lean, size)),
            ((bar + lean, -size), (bar - lean, size)),
            ((-size, -bar), (size, -bar)),
            ((-size, bar), (size, bar)),
        )
        return [
            ResolvedStroke(
                id="",
                points=(centre.translated(*start), centre.translated(*end)),
                width=width,
            )
            for start, end in lines
        ]

    return draw


# Briffits: puffs of dust where the character's heels just were, and two strokes
# trailing off behind them. Each puff is (distance behind, radius), in face radii.
_PUFFS = ((0.90, 0.40), (1.40, 0.52), (1.95, 0.44), (2.40, 0.32))
_TRAILS = ((2.55, 3.10, 0.28), (2.45, 2.95, 0.62))


def _briffits(puppet: ResolvedPuppet) -> list[_Symbol]:
    radius = puppet.face.r
    behind = _behind(puppet)
    ground = puppet.landmarks[Landmark.FEET]
    symbols: list[_Symbol] = []
    for start, end, height in _TRAILS:
        a = Point(puppet.face.cx + behind * start * radius, ground - height * radius)
        b = Point(puppet.face.cx + behind * end * radius, ground - height * radius)
        symbols.append(_Symbol(centre=a, dot=None, draw=_line_drawer(a, b)))
    for distance, size in _PUFFS:
        centre = Point(puppet.face.cx + behind * distance * radius, ground - size * radius)
        symbols.append(
            _Symbol(
                centre=centre,
                dot=size * radius,
                draw=_circle_drawer(centre, size * radius),
                keeps_shape=True,
            )
        )
    return symbols


def _line_drawer(start: Point, end: Point) -> Callable[[float], list[FaceMark]]:
    def draw(width: float) -> list[FaceMark]:
        return [ResolvedStroke(id="", points=(start, end), width=width)]

    return draw


_SYMBOLS: dict[Mark, Callable[[ResolvedPuppet], list[_Symbol]]] = {
    Mark.PLEWDS: _plewds,
    Mark.SQUEANS: _squeans,
    Mark.GRAWLIXES: _grawlixes,
    Mark.BRIFFITS: _briffits,
}


# -- helpers ----------------------------------------------------------------------------


def _named(primitive: FaceMark, identifier: str) -> FaceMark:
    if isinstance(primitive, ResolvedDisc):
        return ResolvedDisc(
            id=identifier,
            centre=primitive.centre,
            radius=primitive.radius,
            filled=primitive.filled,
            width=primitive.width,
        )
    return ResolvedStroke(
        id=identifier, points=primitive.points, width=primitive.width, closed=primitive.closed
    )


def _unit(start: Point, end: Point) -> tuple[float, float]:
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy) or 1.0
    return dx / length, dy / length


def _ring(centre: Point, radius: float) -> list[Point]:
    return [
        Point(
            centre.x + math.cos(2 * math.pi * step / ZONE_SAMPLES) * radius,
            centre.y + math.sin(2 * math.pi * step / ZONE_SAMPLES) * radius,
        )
        for step in range(ZONE_SAMPLES)
    ]


def _zone(marks: list[FaceMark], padding: float) -> tuple[Point, ...]:
    """A padded convex polygon around everything one mark draws."""
    points: list[Point] = []
    for mark in marks:
        if isinstance(mark, ResolvedDisc):
            points.extend(_ring(mark.centre, mark.radius + padding))
        else:
            for point in mark.points:
                points.extend(_ring(point, padding))
    return convex_hull(points)
