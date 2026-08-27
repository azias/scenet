"""Resolving a setting into tonal masses: geometry, value, and draw order.

The solver still never sees artwork. A backdrop reaches it as the same kind of
geometric contract everything else does -- polygons, a value, an integer depth -- and
the emitter is left with nothing to decide.

## Why masses rather than drawn geometry

Crisp architecture needs a vanishing point, and this is deliberately a flat,
orthographic compiler, so drawn buildings would fight the compiler's own model. Soft
tonal masses have no perspective to get wrong. That is the structural argument; the
other is that this is simply how comics establish place.

**Notan** -- the Japanese light/dark mass principle, which entered Western art teaching
through Arthur Wesley Dow's *Composition* (1899) -- holds that place is read from the
arrangement of masses rather than from rendered detail. **Layered silhouette depth**
gives the arrangement: foreground near-black, each receding plane paler. And **aerial
perspective** supplies the parametric rule for free -- with distance, value contrast
drops toward the atmosphere colour. Three numbers per plane, monotonic in depth. That is
notation, not interpretation, which is what makes it belong in a compiler.

## Shape grammars, as a formalism rather than a library

Silhouette profiles are generated with the split/repeat/subdivide operations of CGA
shape grammar (Mueller et al., *Procedural Modeling of Buildings*, SIGGRAPH 2006). It is
reused as a **formalism**: there is no open-source Python implementation of CGA, and the
reference one is commercial, inside Esri CityEngine. See
`docs/explanation/prior_art.md`.

The discipline that comes with it is worth stating: **how many** of a thing there are is
derived from the geometry -- a wider span gets more bays -- and only **how big** each one
is comes from the seed. Random counts make a backdrop flicker between panels that ought
to look related.

## Determinism

Every profile is seeded from the declared content and the panel size, through
`blake2b` -- never a clock, never `hash()`, which is salted per process and would agree
with itself all day while disagreeing with tomorrow's build. Every profile is also
generated inside the frame by construction, so there is nothing to clip; `shapely` stays
where it earns its place, in the balloon occlusion cost.
"""

import math
from dataclasses import dataclass
from hashlib import blake2b
from random import Random

from scenet.geom import BBox, Circle, Point
from scenet.ir import Mass, MassKind, Plane, SettingSpec, Spans, TimeOfDay, Weather

__all__ = [
    "ATMOSPHERE",
    "FALL_CONTRAST_THRESHOLD",
    "FOREGROUND_SPAN_KEEP",
    "GROUND_START",
    "LADDER",
    "PLANE_DEPTH",
    "PLANE_SCALE",
    "TONE_INDEX",
    "ResolvedAtmosphere",
    "ResolvedBackdrop",
    "ResolvedMass",
    "ResolvedVeil",
    "depth_for",
    "lightness",
    "seed_for",
    "solve_backdrop",
    "tone_for",
]

# -- the value ladder ---------------------------------------------------------------
#
# Evenly spaced greys are perceptually uneven, so the ladder is spaced in OKLab
# lightness, which predicts perceived lightness well. It is a handful of *neutral*
# values fixed once, not a runtime colour computation -- so it was computed during
# development and the result hardcoded here. A colour library in `dependencies` would
# put a package through the licence gate to produce numbers that never change.
#
# Each time of day supplies two numbers: the value of the foreground and the value of
# the atmosphere. The four planes sit at t = 0, 0.25, 0.5, 0.75 between them and the
# atmosphere itself at t = 1, so the ladder is monotonic in depth by construction rather
# than by tuning. For a neutral grey OKLab reduces to L = cbrt(linear), which is what
# `lightness` inverts.
#
#            foreground  near  mid  far   atmosphere
#   dawn        0.18     0.33  0.48  0.63    0.78
#   day         0.14     0.34  0.55  0.75    0.95
#   dusk        0.12     0.25  0.37  0.50    0.62
#   night       0.08     0.17  0.25  0.34    0.42
LADDER: dict[TimeOfDay, tuple[str, str, str, str, str]] = {
    TimeOfDay.DAWN: ("#121212", "#353535", "#5d5d5d", "#898989", "#b7b7b7"),
    TimeOfDay.DAY: ("#090909", "#383838", "#707070", "#adadad", "#eeeeee"),
    TimeOfDay.DUSK: ("#060606", "#202020", "#404040", "#626262", "#868686"),
    TimeOfDay.NIGHT: ("#020202", "#0e0e0e", "#222222", "#373737", "#4d4d4d"),
}

#: Which rung of the ladder each plane takes. Front to back, so the foreground is the
#: darkest and the far plane the palest of the four.
TONE_INDEX: dict[Plane, int] = {
    Plane.FOREGROUND: 0,
    Plane.NEAR: 1,
    Plane.MID: 2,
    Plane.FAR: 3,
}

#: The rung beyond the farthest plane: the atmosphere itself.
ATMOSPHERE = 4

# -- draw order ---------------------------------------------------------------------
#
# `depth_order` in `solve/staging.py` floors actor depth at 0, so the backdrop planes
# take negative depths and land behind the whole cast without a second ordering
# mechanism. `emit/svg.py` already sorts by (depth, id).
PLANE_DEPTH: dict[Plane, int] = {Plane.FAR: -3, Plane.MID: -2, Plane.NEAR: -1}

#: How much larger the same mass is drawn nearer the reader. Size perspective alongside
#: aerial perspective: a near hill is not merely darker than a far one, it is bigger.
PLANE_SCALE: dict[Plane, float] = {
    Plane.FAR: 0.55,
    Plane.MID: 0.8,
    Plane.NEAR: 1.0,
    Plane.FOREGROUND: 1.45,
}

#: Where a ground-like mass begins below the horizon, as a fraction of the distance from
#: the horizon to the bottom edge.
#:
#: Ground, floor and water all run to the bottom edge, so a nearer one drawn from the
#: horizon would bury every plane behind it -- the near quayside would simply erase the
#: water. Starting each one lower leaves the planes behind it showing as bands, and that
#: stack of receding bands is the depth cue.
#:
#: The exception is the farthest ground-like mass in a panel, which meets the horizon
#: itself: there is nothing behind it to reveal, and a strip of bare paper along the
#: horizon reads as a mistake. See `_ground_start`.
GROUND_START: dict[Plane, float] = {
    Plane.FAR: 0.0,
    Plane.MID: 0.16,
    Plane.NEAR: 0.40,
    Plane.FOREGROUND: 0.68,
}

#: The kinds that lie flat and run to the bottom edge, rather than standing up from the
#: horizon.
GROUND_KINDS = frozenset({MassKind.GROUND, MassKind.FLOOR, MassKind.WATER})

#: How much of its declared span a foreground mass keeps, held against its outer edge.
#:
#: A foreground mass is a repoussoir -- the doorway or the wall you are standing behind,
#: which frames the panel. `left` reaches past the middle of the panel, and a foreground
#: mass that wide stops framing the composition and starts burying it: the first contact
#: sheet had `alley` hiding everything of the figure above the knees. A full-width
#: foreground is left alone, because asking for one is asking for a silhouette.
FOREGROUND_SPAN_KEEP = 0.6

# -- weather ------------------------------------------------------------------------
#
# One turbulence layer covers both of COCO-Stuff's atmospheric stuff classes. `fog` is
# it dense and low-frequency, tinted with the atmosphere itself, because fog *is* the
# atmosphere arriving in the foreground. For `rain` and `snow` the same layer is thinner,
# broader, and tinted with a nearer rung -- that is cloud, and cloud is closer than the
# sky it covers. Which also does the compositional work: a snowy sky is overcast rather
# than bright, and white flakes need something to be white against.
#
# Frequencies are per panel unit.
VEIL_SETTINGS: dict[Weather, tuple[float, float, int, int]] = {
    # weather: (opacity, base frequency, octaves, ladder rung to tint with)
    Weather.FOG: (0.55, 0.0042, 4, ATMOSPHERE),
    Weather.RAIN: (0.30, 0.0016, 3, 2),
    Weather.SNOW: (0.42, 0.0022, 3, 2),
}

#: Above this lightness -- of the sky *as the cloud leaves it*, not of the bare sky --
#: **rain** is drawn in ink rather than in the paper colour. Inkers flip the same way and
#: for the same reason: a white streak over a noon sky is invisible and a black one over
#: midnight is too. The choice is made here rather than in the emitter, because it is a
#: decision about the panel.
#:
#: Snow does not flip. Snow is white -- a convention rather than a value on the depth
#: ladder, and a black snowflake is not a thing any comic has ever drawn. The overcast
#: veil above is what gives it something to read against.
FALL_CONTRAST_THRESHOLD = 0.5

#: What snow is drawn in, at every hour.
SNOW_TONE = "#ffffff"

#: How far rain leans from vertical, as a rightward run per unit of fall. Every streak
#: in a panel shares it: rain drawn at scattered angles reads as static, not as weather.
RAIN_SLANT = 0.26

#: One streak per this many square panel units, and one fleck per this many. Density
#: follows the panel's area so a small panel is not solid with weather.
RAIN_DENSITY = 9000.0
SNOW_DENSITY = 13000.0


def lightness(tone: str) -> float:
    """The OKLab lightness a neutral grey sits at.

    The inverse of how the ladder was built, so that monotonicity is checkable rather
    than asserted. For a neutral, OKLab's matrices cancel and `L` is the cube root of
    the linear value, which is the whole conversion.

    Args:
        tone: A `#rrggbb` neutral grey.

    Returns:
        Lightness in `0.0 .. 1.0`.

    Example:
        >>> from scenet.solve.backdrop import lightness
        >>> round(lightness("#ffffff"), 3)
        1.0
    """
    channel = int(tone[1:3], 16) / 255.0
    linear = channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
    return linear ** (1 / 3)


def tone_for(kind: MassKind, plane: Plane, time: TimeOfDay) -> str:
    """The value a mass is filled with.

    Value comes from the **plane** and from nothing else, which is what keeps the notan
    reading literal: masses at one distance read as one mass, and the arrangement is
    what carries the place. Two kinds sit off their own plane's rung, and both stay on
    the ladder rather than beside it:

    - `sky` is the atmosphere. It is at infinite distance whatever plane it was filed
      under, so it always takes the last rung.
    - `window` is a hole showing a more distant plane, so it takes the rung one step
      farther back than the wall it is cut into.

    Args:
        kind: What the mass is made of.
        plane: How far back it sits.
        time: When the panel happens, which selects the ladder.

    Returns:
        A `#rrggbb` neutral grey.

    Example:
        >>> from scenet.ir import MassKind, Plane, TimeOfDay
        >>> from scenet.solve.backdrop import tone_for
        >>> tone_for(MassKind.SKY, Plane.FAR, TimeOfDay.NIGHT)
        '#4d4d4d'
    """
    if kind is MassKind.SKY:
        index = ATMOSPHERE
    elif kind is MassKind.WINDOW:
        index = min(TONE_INDEX[plane] + 1, ATMOSPHERE)
    else:
        index = TONE_INDEX[plane]
    return LADDER[time][index]


def depth_for(plane: Plane, *, frontmost_actor: int) -> int:
    """Painter's order for a plane, against the cast that is already placed.

    Args:
        plane: How far back the mass sits.
        frontmost_actor: The largest depth any actor in this panel was given.

    Returns:
        A depth for the existing `(depth, id)` sort. Backdrop planes are negative, so
        they land behind every actor; the foreground takes one above the frontmost, so
        it draws over the cast and still under the lettering.
    """
    if plane is Plane.FOREGROUND:
        return max(frontmost_actor, 0) + 1
    return PLANE_DEPTH[plane]


def seed_for(setting: SettingSpec, width: float, height: float) -> int:
    """A stable seed for one panel's backdrop.

    Derived from the declared content and the panel size, so the same source produces
    the same silhouettes forever -- and two panels that differ get different ones.

    `blake2b` rather than `hash()`, deliberately and load-bearingly: `hash()` is salted
    per process, so a seed derived from it agrees with itself all day and disagrees with
    tomorrow's build. That is exactly the failure a golden-file test cannot see.

    Args:
        setting: The declared setting.
        width: Panel width in panel units.
        height: Panel height in panel units.

    Returns:
        A 32-bit seed.
    """
    declared = ";".join(
        [
            f"{width:.4f}x{height:.4f}",
            setting.horizon.value,
            setting.time.value,
            setting.weather.value,
            *(f"{m.kind.value}/{m.plane.value}/{m.spans.value}" for m in setting.masses),
        ]
    )
    return int.from_bytes(blake2b(declared.encode("utf-8"), digest_size=4).digest(), "big")


@dataclass(frozen=True, slots=True)
class ResolvedMass:
    """One tonal mass, resolved to a numeric polygon.

    Attributes:
        id: Stable identifier, `m0`, `m1`, ... back to front.
        kind: What it is made of, kept so a Core document stays readable.
        plane: How far back it sits.
        depth: Its place in the painter's order, shared with the actors.
        tone: The `#rrggbb` fill.
        polygon: The silhouette, in panel coordinates.
    """

    id: str
    kind: MassKind
    plane: Plane
    depth: int
    tone: str
    polygon: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class ResolvedVeil:
    """The turbulence layer, as parameters rather than as pixels.

    SVG has Perlin noise built in through `feTurbulence`, and the specification includes
    reference code, so a fixed seed is reproducible **by definition** -- the emitted text
    is identical. Browsers agree only approximately on what to paint from it, which is
    fine and is why the determinism contract is on the SVG text and has never been on
    pixels. See `docs/reference/language.md`.
    """

    tone: str
    opacity: float
    frequency: float
    octaves: int
    seed: int


@dataclass(frozen=True, slots=True)
class ResolvedAtmosphere:
    """What the air is doing, resolved.

    Attributes:
        time: When the panel happens.
        weather: What is falling, if anything.
        tone: The atmosphere's own value at this hour.
        veil: The turbulence layer -- fog, or cloud for rain and snow.
        streaks: Rain, as `(start, end)` pairs all at one angle.
        flecks: Snow, as discs.
        streak_width: Stroke width for a streak, in panel units.
        fall_tone: What rain and snow are drawn in, chosen against the atmosphere so
            they stay visible at every hour.
    """

    time: TimeOfDay
    weather: Weather
    tone: str
    veil: ResolvedVeil | None = None
    streaks: tuple[tuple[Point, Point], ...] = ()
    flecks: tuple[Circle, ...] = ()
    streak_width: float = 0.0
    fall_tone: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedBackdrop:
    """Everything behind, around and in front of the cast.

    Attributes:
        horizon: Where the ground meets what is behind it, in panel units.
        masses: The tonal masses, back to front.
        atmosphere: The air, or None when the weather is clear.
        seed: What every profile in here was generated from.
    """

    horizon: float
    seed: int
    masses: tuple[ResolvedMass, ...] = ()
    atmosphere: ResolvedAtmosphere | None = None

    def occluders(self) -> tuple[tuple[tuple[Point, ...], Plane], ...]:
        """The masses a balloon should prefer not to sit on, with their planes.

        Masses are **not** exclusions. Balloons sit over backgrounds routinely; that is
        the point of having a background. This feeds a soft cost instead.
        """
        return tuple((mass.polygon, mass.plane) for mass in self.masses)


def solve_backdrop(
    setting: SettingSpec, panel: BBox, *, frontmost_actor: int = 0
) -> ResolvedBackdrop | None:
    """Resolve a declared setting into masses, tones and atmosphere.

    Args:
        setting: The declared setting.
        panel: The panel rectangle. Not the margined frame: a backdrop bleeds to the
            edge, exactly as artwork does, and only lettering is kept inside a margin.
        frontmost_actor: The largest depth any actor was given, so a foreground mass can
            be placed in front of the whole cast.

    Returns:
        The resolved backdrop, or None when there is nothing to draw -- which is what
        every panel written before this block existed gets.

    Example:
        >>> from scenet.geom import BBox
        >>> from scenet.ir import SettingSpec
        >>> from scenet.solve.backdrop import solve_backdrop
        >>> solve_backdrop(SettingSpec(), BBox(0.0, 0.0, 800.0, 600.0)) is None
        True
    """
    if setting.is_bare:
        return None

    seed = seed_for(setting, panel.width, panel.height)
    horizon = panel.height * setting.horizon.fraction

    grounded = _meets_horizon(setting.masses)
    masses: list[ResolvedMass] = []
    for index, mass in enumerate(setting.masses):
        rng = _rng(seed, index, mass)
        depth = depth_for(mass.plane, frontmost_actor=frontmost_actor)
        tone = tone_for(mass.kind, mass.plane, setting.time)
        for polygon in _profiles(
            mass, panel=panel, horizon=horizon, rng=rng, meets_horizon=index == grounded
        ):
            masses.append(
                ResolvedMass(
                    id=f"m{len(masses)}",
                    kind=mass.kind,
                    plane=mass.plane,
                    depth=depth,
                    tone=tone,
                    polygon=polygon,
                )
            )

    return ResolvedBackdrop(
        horizon=horizon,
        seed=seed,
        masses=tuple(masses),
        atmosphere=_atmosphere(setting, panel, seed),
    )


def _rng(seed: int, index: int, mass: Mass) -> Random:
    """A generator for one mass, derived from the panel seed and the mass's own words.

    Mixed through a digest rather than by arithmetic on the seed, so two masses that
    differ only in their span do not get generators a few steps apart in one stream.
    """
    material = f"{seed}:{index}:{mass.kind.value}:{mass.plane.value}:{mass.spans.value}"
    # `random` is exactly the right tool here, and the weakness the linter objects to is
    # the point: what this needs is a stream identical on every machine and every release
    # for a given seed, which Mersenne Twister promises and a cryptographic generator
    # explicitly does not. Nothing here is a secret.
    return Random(  # noqa: S311 -- reproducibility is the requirement, not unpredictability
        int.from_bytes(blake2b(material.encode("utf-8"), digest_size=8).digest(), "big")
    )


def _meets_horizon(masses: tuple[Mass, ...]) -> int | None:
    """Which mass, if any, is the one that runs all the way up to the horizon.

    The farthest ground-like mass in the panel, because there is nothing behind it to
    reveal by starting lower. First writer wins on a tie, so the answer does not depend
    on anything but declaration order.
    """
    candidates = [
        (GROUND_START[mass.plane], index)
        for index, mass in enumerate(masses)
        if mass.kind in GROUND_KINDS
    ]
    return min(candidates)[1] if candidates else None


@dataclass(frozen=True, slots=True)
class _Plot:
    """The patch of panel one mass is composed into.

    Every generator below takes this and a random generator, which keeps their
    signatures the same shape and puts the arithmetic that turns a declaration into
    panel units in one place rather than in nine.

    Attributes:
        left: Left edge of the span, in panel units.
        right: Right edge of the span.
        horizon: Where the ground meets what is behind it.
        rise: How far a mass standing on the horizon may rise, its plane's scaling
            already applied. Every generator clamps to the frame, so a foreground mass
            simply fills the panel rather than running off the top.
        ground: Where a mass that lies flat begins -- the horizon for the farthest one,
            lower for anything in front of it.
        bottom: The panel's bottom edge.
        panel_width: The whole panel's width, which is what repeat counts are measured
            against so that a half-width span gets half as many bays.
    """

    left: float
    right: float
    horizon: float
    rise: float
    ground: float
    bottom: float
    panel_width: float

    @property
    def width(self) -> float:
        """How wide the span is, in panel units."""
        return self.right - self.left

    def repeats(self, share: float, least: int) -> int:
        """How many times a motif repeats across this span.

        Derived from the geometry rather than from the seed. A wider span gets more
        bays, and two panels of the same width get the same number of them -- which is
        what stops a backdrop flickering between panels meant to look related.

        Args:
            share: How much of the panel's width one repeat should take.
            least: Fewest repeats worth drawing.

        Returns:
            A repeat count.
        """
        return max(least, round(self.width / (self.panel_width * share)))


def _profiles(
    mass: Mass, *, panel: BBox, horizon: float, rng: Random, meets_horizon: bool
) -> list[tuple[Point, ...]]:
    """The silhouette of one authored mass, as one or more polygons.

    One mass may resolve to several: furniture is a few separate blocks and a wall may
    hold several windows. Joining them into one comb with a zero-height baseline would
    be a lie about the shape, and a self-touching polygon besides.
    """
    start, end = _extent(mass)
    scale = PLANE_SCALE[mass.plane]
    plot = _Plot(
        left=panel.x + panel.width * start,
        right=panel.x + panel.width * end,
        horizon=horizon,
        rise=horizon * scale,
        ground=_ground_start(mass.plane, horizon, panel.bottom, meets_horizon=meets_horizon),
        bottom=panel.bottom,
        panel_width=panel.width,
    )

    match mass.kind:
        case MassKind.SKY | MassKind.WALL:
            polygons = [_rect(plot.left, panel.y, plot.right, horizon)]
        case MassKind.CEILING:
            band = min(horizon, panel.y + horizon * 0.26 * scale)
            polygons = [_rect(plot.left, panel.y, plot.right, band)]
        case MassKind.GROUND | MassKind.FLOOR:
            polygons = [_rect(plot.left, plot.ground, plot.right, plot.bottom)]
        case MassKind.WATER:
            polygons = [_water(plot, rng)]
        case MassKind.BUILDING:
            polygons = [_skyline(plot, rng)]
        case MassKind.SOLID:
            polygons = [_peaks(plot, rng)]
        case MassKind.PLANT:
            polygons = [_treeline(plot, rng)]
        case MassKind.STRUCTURAL:
            polygons = [_railing(plot, rng)]
        case MassKind.FURNITURE:
            polygons = _blocks(plot, rng)
        case MassKind.WINDOW:
            polygons = _panes(plot, rng)
    return polygons


def _extent(mass: Mass) -> tuple[float, float]:
    """The horizontal extent a mass actually occupies, as fractions of panel width.

    The declared span, narrowed against its own outer edge when the mass is in the
    foreground -- see `FOREGROUND_SPAN_KEEP`. Still resolved entirely from the
    declaration, with no reference to anything else in the panel, which is what keeps
    `spans` an absolute extent rather than a relation the solver would have to order.
    """
    start, end = mass.spans.fractions
    if mass.plane is not Plane.FOREGROUND or mass.spans is Spans.FULL:
        return start, end

    kept = (end - start) * FOREGROUND_SPAN_KEEP
    if mass.spans is Spans.LEFT:
        return start, start + kept
    if mass.spans is Spans.RIGHT:
        return end - kept, end
    middle = (start + end) / 2
    return middle - kept / 2, middle + kept / 2


def _ground_start(plane: Plane, horizon: float, bottom: float, *, meets_horizon: bool) -> float:
    """Where a ground-like mass begins, in panel units."""
    if meets_horizon:
        return horizon
    return horizon + (bottom - horizon) * GROUND_START[plane]


def _rect(x0: float, y0: float, x1: float, y1: float) -> tuple[Point, ...]:
    return (Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1))


def _skyline(plot: _Plot, rng: Random) -> tuple[Point, ...]:
    """A row of flat-topped bays: CGA repeat, then a split to pick each height."""
    bays = plot.repeats(0.11, 3)
    step = plot.width / bays
    # Quantised split levels rather than a continuous height. Buildings share storey
    # heights, and a continuous distribution reads as noise instead of as a street.
    levels = (0.34, 0.46, 0.58, 0.7, 0.86)
    points = [Point(plot.left, plot.horizon)]
    for bay in range(bays):
        left = plot.left + bay * step
        top = max(0.0, plot.horizon - plot.rise * rng.choice(levels))
        points.append(Point(left, top))
        points.append(Point(left + step, top))
    points.append(Point(plot.right, plot.horizon))
    return tuple(points)


def _peaks(plot: _Plot, rng: Random) -> tuple[Point, ...]:
    """Hills or mountains: apexes separated by saddles."""
    count = plot.repeats(0.34, 2)
    step = plot.width / count
    points = [Point(plot.left, plot.horizon)]
    for peak in range(count):
        left = plot.left + peak * step
        apex = left + step * rng.uniform(0.38, 0.62)
        points.append(Point(apex, max(0.0, plot.horizon - plot.rise * rng.uniform(0.45, 1.0))))
        if peak < count - 1:
            points.append(Point(left + step, max(0.0, plot.horizon - plot.rise * 0.14)))
    points.append(Point(plot.right, plot.horizon))
    return tuple(points)


def _treeline(plot: _Plot, rng: Random) -> tuple[Point, ...]:
    """Foliage as a row of canopies.

    Each canopy is half an ellipse exactly as wide as its bay, so the profile's x never
    turns back on itself. Overlapping canopies would look softer and would make the
    polygon self-intersecting, which is not a shape.
    """
    canopies = plot.repeats(0.085, 3)
    step = plot.width / canopies
    samples = 8
    points = [Point(plot.left, plot.horizon)]
    for canopy in range(canopies):
        centre = plot.left + (canopy + 0.5) * step
        height = plot.rise * rng.uniform(0.34, 0.58)
        for sample in range(samples + 1):
            angle = math.pi - math.pi * sample / samples
            points.append(
                Point(
                    centre + math.cos(angle) * step / 2,
                    max(0.0, plot.horizon - math.sin(angle) * height),
                )
            )
    points.append(Point(plot.right, plot.horizon))
    return tuple(points)


def _railing(plot: _Plot, rng: Random) -> tuple[Point, ...]:
    """A rail on posts -- pilings, a fence, a gantry.

    Walked as a comb: left to right along the top of the rail, then back along its
    underside, dropping down and up again for each post.
    """
    posts = plot.repeats(0.055, 2)
    step = plot.width / posts
    rail_top = max(0.0, plot.horizon - plot.rise * rng.uniform(0.26, 0.34))
    rail_bottom = min(plot.horizon, rail_top + plot.rise * 0.08)
    post_width = step * 0.22

    points = [
        Point(plot.left, rail_top),
        Point(plot.right, rail_top),
        Point(plot.right, rail_bottom),
    ]
    for post in reversed(range(posts)):
        centre = plot.left + (post + 0.5) * step
        left, right = centre - post_width / 2, centre + post_width / 2
        points.append(Point(right, rail_bottom))
        points.append(Point(right, plot.horizon))
        points.append(Point(left, plot.horizon))
        points.append(Point(left, rail_bottom))
    points.append(Point(plot.left, rail_bottom))
    return tuple(points)


def _water(plot: _Plot, rng: Random) -> tuple[Point, ...]:
    """Water, with a ripple along the top edge rather than a ruled line.

    The ripple rises **above** the start line rather than dipping below it. Dipping
    leaves a sliver of bare paper between the troughs and whatever the water was meant
    to meet, which reads as a white seam along the horizon -- the one artifact the first
    contact sheet made obvious.
    """
    samples = 24
    amplitude = (plot.bottom - plot.ground) * 0.03
    phase = rng.uniform(0.0, math.tau)
    points = []
    for sample in range(samples + 1):
        t = sample / samples
        wave = (1.0 + math.sin(phase + t * math.tau * 1.5)) / 2
        points.append(Point(plot.left + plot.width * t, max(0.0, plot.ground - amplitude * wave)))
    points.append(Point(plot.right, plot.bottom))
    points.append(Point(plot.left, plot.bottom))
    return tuple(points)


def _blocks(plot: _Plot, rng: Random) -> list[tuple[Point, ...]]:
    """Furniture: a few separate masses standing on the floor."""
    count = 3 if plot.width > (plot.bottom - plot.horizon) * 2 else 2
    step = plot.width / count
    base = min(plot.bottom, plot.horizon + (plot.bottom - plot.horizon) * 0.34)
    blocks: list[tuple[Point, ...]] = []
    for block in range(count):
        left = plot.left + block * step + step * 0.12
        right = plot.left + (block + 1) * step - step * 0.12
        top = max(0.0, plot.horizon - plot.rise * rng.uniform(0.06, 0.2))
        blocks.append(_rect(left, top, right, base))
    return blocks


def _panes(plot: _Plot, rng: Random) -> list[tuple[Point, ...]]:
    """Windows: openings cut into the wall behind them."""
    count = 3 if plot.width > plot.horizon * 1.6 else 2
    step = plot.width / count
    top = plot.horizon * rng.uniform(0.18, 0.26)
    base = plot.horizon * rng.uniform(0.66, 0.76)
    panes: list[tuple[Point, ...]] = []
    for pane in range(count):
        left = plot.left + pane * step + step * 0.18
        right = plot.left + (pane + 1) * step - step * 0.18
        panes.append(_rect(left, top, right, base))
    return panes


def _atmosphere(setting: SettingSpec, panel: BBox, seed: int) -> ResolvedAtmosphere | None:
    """The air: a turbulence veil, and whatever is falling through it."""
    if setting.weather is Weather.CLEAR:
        return None

    tone = LADDER[setting.time][ATMOSPHERE]
    opacity, frequency, octaves, rung = VEIL_SETTINGS[setting.weather]
    veil = ResolvedVeil(
        tone=LADDER[setting.time][rung],
        opacity=opacity,
        frequency=frequency,
        octaves=octaves,
        # `feTurbulence` takes a small integer seed, and the specification's reference
        # implementation is defined over one.
        seed=seed % 65536,
    )
    rng = Random(  # noqa: S311 -- see `_rng`: the same stream on every machine is the point
        int.from_bytes(blake2b(f"{seed}:fall".encode(), digest_size=8).digest(), "big")
    )
    if setting.weather is Weather.RAIN:
        # Ink over a bright sky, paper over a dark one: a single white streak is
        # invisible against noon and a black one is invisible against midnight, so the
        # mark follows the ground it falls over.
        return ResolvedAtmosphere(
            time=setting.time,
            weather=setting.weather,
            tone=tone,
            veil=veil,
            streaks=_rain(panel, rng),
            streak_width=max(1.0, panel.height * 0.0022),
            fall_tone=LADDER[setting.time][
                0 if _under_cloud(tone, veil) > FALL_CONTRAST_THRESHOLD else ATMOSPHERE
            ],
        )
    if setting.weather is Weather.SNOW:
        return ResolvedAtmosphere(
            time=setting.time,
            weather=setting.weather,
            tone=tone,
            veil=veil,
            flecks=_snow(panel, rng),
            fall_tone=SNOW_TONE,
        )
    return ResolvedAtmosphere(time=setting.time, weather=setting.weather, tone=tone, veil=veil)


def _under_cloud(tone: str, veil: ResolvedVeil) -> float:
    """How light the sky ends up once the cloud is over it.

    Mixed in lightness rather than in sRGB, which is close enough for a threshold and
    stays in the space the ladder was built in. What rain has to be visible against is
    this, not the bare sky: at noon the sky is nearly white and the cloud does not change
    that, so the rain still has to be ink.
    """
    return lightness(tone) * (1 - veil.opacity) + lightness(veil.tone) * veil.opacity


def _rain(panel: BBox, rng: Random) -> tuple[tuple[Point, Point], ...]:
    """Falling rain, every streak at the same angle.

    Starts are sampled from the region where the whole streak already fits, so nothing
    has to be clipped afterwards -- clipping would shorten some streaks and, worse, bend
    them off the shared angle.
    """
    length = panel.height * 0.07
    run, fall = length * RAIN_SLANT, length
    count = max(12, int(panel.width * panel.height / RAIN_DENSITY))
    streaks: list[tuple[Point, Point]] = []
    for _ in range(count):
        x = rng.uniform(panel.x, panel.right - run)
        y = rng.uniform(panel.y, panel.bottom - fall)
        streaks.append((Point(x, y), Point(x + run, y + fall)))
    return tuple(streaks)


def _snow(panel: BBox, rng: Random) -> tuple[Circle, ...]:
    """Falling snow, as discs of two or three sizes."""
    count = max(10, int(panel.width * panel.height / SNOW_DENSITY))
    flecks: list[Circle] = []
    for _ in range(count):
        radius = panel.height * rng.uniform(0.004, 0.009)
        flecks.append(
            Circle(
                rng.uniform(panel.x + radius, panel.right - radius),
                rng.uniform(panel.y + radius, panel.bottom - radius),
                radius,
            )
        )
    return tuple(flecks)
