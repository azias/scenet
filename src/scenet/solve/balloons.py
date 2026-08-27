"""Placing everything in a panel that carries words: balloons, captions, and tails.

Placement is a scored search over candidate positions rather than a sweep of a cost
grid. Balloons belong in a small number of sensible places relative to their speaker
-- around the head, or tucked into a corner -- so generating those directly is both
cheaper than scanning cells and produces more natural results. This is the approach
used in the cartographic label-placement literature, which is the same problem.

The constraint that naive implementations miss is **reading order**. A box may never
sit above-and-left of the one before it in the script, because that makes the panel
read in the wrong order. That is a correctness bug in a comic, not a cosmetic one, so
it is enforced as a hard filter rather than scored.

Captions go through this machinery rather than a parallel one. The placement
principles the lettering references give for floating text -- keep off the important
figures, preserve the space of the art, keep the reading order flowing -- are the ones
already implemented here. What differs is where a caption *wants* to be: a balloon
mildly dislikes hugging the panel edge, and a caption is looking for exactly that.

So the two are placed in **one pass in script order**, sharing the list of boxes
already down. Placing every caption first would be simpler and wrong: a caption
written after the dialogue would then impose reading order on balloons that precede
it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry import Polygon, box

from scenet.assets.kinematics import ResolvedPuppet
from scenet.errors import BalloonPlacementError
from scenet.geom import BBox, Circle, Point, segment_intersects_circle
from scenet.ir import (
    BalloonKind,
    CaptionEvent,
    CaptionKind,
    PlacementZone,
    Plane,
    SayEvent,
    ScriptEvent,
)
from scenet.solve.backdrop import ResolvedBackdrop
from scenet.solve.text import (
    ITALIC_FONT_PATH,
    FontMetrics,
    TextBlock,
    balloon_size,
    layout_text,
    load_metrics,
)

# Candidate ring around the speaker's head.
RING_DIRECTIONS = 16
RING_RADII = (1.15, 1.5, 2.0)

# Cost weights. Tuned together; changing one in isolation will not do what you expect.
W_OCCLUSION = 1.0  # per unit of actor silhouette covered, normalised by balloon area
W_MOUTH_DISTANCE = 0.9  # keeps a balloon near whoever is speaking
W_PREFERRED_ZONE = 1.4  # honours an explicit `prefer:` hint
W_GAZE_BLOCKING = 0.7  # do not stand in front of what a character is looking at
W_EDGE = 0.25  # mild dislike of hugging the panel edge

# A backdrop mass is *not* an exclusion. Balloons sit over backgrounds routinely; that
# is what a background is for. So covering one is a soft cost, and a mild one -- an
# order of magnitude below covering a face, which is forbidden outright.
W_MASS_OCCLUSION = 0.5

# What covering a mass costs, by how near it is. Empty sky is nearly free; a foreground
# silhouette is the one thing in a backdrop a balloon should genuinely stay off, because
# it reads as an object in the room rather than as scenery.
PLANE_OCCLUSION_WEIGHT: dict[Plane, float] = {
    Plane.FOREGROUND: 1.0,
    Plane.NEAR: 0.55,
    Plane.MID: 0.3,
    Plane.FAR: 0.12,
}

# Tolerance when comparing balloon positions for reading order, in panel units.
READING_EPSILON = 2.0

# Balloon text size as a fraction of panel height.
FONT_SIZE_FRACTION = 0.035

# How far along a gaze direction the character is considered to be looking.
GAZE_REACH_FACTOR = 3.0

# Caption lettering runs slightly smaller than dialogue: a caption is the panel's own
# voice rather than someone speaking, and setting it at dialogue size makes it compete
# with the balloons instead of framing them.
CAPTION_FONT_SIZE_FRACTION = 0.030

# A caption box holds its text more tightly than a balloon does. A balloon's padding is
# generous because the outline is a curve pulling away from the text at the corners; a
# rectangle does not, so the same padding would look slack.
CAPTION_PADDING_FACTOR = 0.42

# How strongly a caption is drawn to the panel edge. The opposite sign to `W_EDGE`:
# tucking into a corner is where a caption belongs, not a compromise it settles for.
W_CAPTION_EDGE = 1.1

# Quotation marks for a `spoken` caption. Applied here rather than in the emitter --
# characters added after measurement would not fit the box drawn for them.
OPENING_QUOTE = "“"
CLOSING_QUOTE = "”"


@dataclass(frozen=True, slots=True)
class TailRoute:
    """The pointer from balloon to mouth.

    A straight tail is correct almost always. `control` is set only when the direct
    route was obstructed and the tail had to bend around something.
    """

    start: Point
    end: Point
    control: Point | None = None

    @property
    def is_curved(self) -> bool:
        """Whether this tail had to bend around a face.

        Reported in :attr:`CompileResult.notes <scenet.pipeline.CompileResult.notes>`, since
        a curved tail is a sign the panel is crowded enough to be worth a second look.
        """
        return self.control is not None


@dataclass(frozen=True, slots=True)
class PlacedBalloon:
    """One balloon after placement, before it is reduced to a Core document.

    Attributes:
        id: Stable identifier, `b0`, `b1`, ... in script order.
        speaker: Actor id of whoever is talking.
        order: Position in reading order, counting from zero.
        kind: Which sort of balloon to draw.
        box: Where it ended up.
        block: The text, already broken into lines and measured.
        tail: The route from balloon to mouth.
    """

    id: str
    speaker: str
    order: int
    kind: BalloonKind
    box: BBox
    block: TextBlock
    tail: TailRoute


@dataclass(frozen=True, slots=True)
class PlacedCaption:
    """One caption after placement, before it is reduced to a Core document.

    Attributes:
        id: Stable identifier, `c0`, `c1`, ... in the order the captions appear.
        order: Position in the panel's reading order, which captions share with
            balloons -- so a caption between two lines of dialogue takes the number
            between theirs.
        kind: What the box is doing, which decides how it is set.
        box: Where it ended up.
        block: The text, already quoted where the kind calls for it, broken into lines
            and measured against the face it will be drawn in.
        speaker: Who is talking, for a `spoken` caption. They are off panel, so this
            is not an actor id and resolves to nobody in the cast.

    There is no tail, which is the reason this is not a fifth `BalloonKind`.
    """

    id: str
    order: int
    kind: CaptionKind
    box: BBox
    block: TextBlock
    speaker: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptLayout:
    """Everything in a panel that carries words, placed.

    Two tuples rather than one merged sequence: they reduce to two different Core
    types, and the thing that orders them -- `order` -- is on both.
    """

    captions: tuple[PlacedCaption, ...] = ()
    balloons: tuple[PlacedBalloon, ...] = ()


def _hull_polygon(actor: ResolvedPuppet) -> Polygon:
    return Polygon([(point.x, point.y) for point in actor.hull])


def _candidate_positions(
    speaker: ResolvedPuppet, size: tuple[float, float], panel: BBox
) -> list[BBox]:
    """Positions worth evaluating for a balloon of this size.

    A ring around the speaker's head, plus the four panel corners. The corners matter
    because a crowded panel often has room nowhere else, and a corner balloon with a
    long tail is a perfectly ordinary comics solution.
    """
    width, height = size
    head = speaker.face
    reach = head.r + math.hypot(width, height) / 2
    candidates: list[BBox] = []

    for step in range(RING_DIRECTIONS):
        # Start at straight up and go clockwise; balloons above the speaker are the
        # commonest and should be tried first so that ties resolve upward.
        angle = -math.pi / 2 + 2 * math.pi * step / RING_DIRECTIONS
        for factor in RING_RADII:
            distance = reach * factor
            centre_x = head.cx + math.cos(angle) * distance
            centre_y = head.cy + math.sin(angle) * distance
            candidates.append(BBox(centre_x - width / 2, centre_y - height / 2, width, height))

    inset = min(panel.width, panel.height) * 0.02
    for corner_x, corner_y in (
        (panel.x + inset, panel.y + inset),
        (panel.right - inset - width, panel.y + inset),
        (panel.x + inset, panel.bottom - inset - height),
        (panel.right - inset - width, panel.bottom - inset - height),
    ):
        candidates.append(BBox(corner_x, corner_y, width, height))

    return candidates


def _caption_positions(size: tuple[float, float], panel: BBox) -> list[BBox]:
    """Positions worth evaluating for a caption of this size.

    One per :class:`PlacementZone <scenet.ir.PlacementZone>`, with the outer zones
    snapped flat against the panel edge rather than floated at the zone's centre.
    Derived from the enum rather than hand-listed, so a zone that becomes expressible
    in the language is a zone a caption can actually reach.
    """
    width, height = size
    inset = min(panel.width, panel.height) * 0.02
    across = {
        "left": panel.x + inset,
        "center": panel.x + (panel.width - width) / 2,
        "right": panel.right - inset - width,
    }
    down = {
        "top": panel.y + inset,
        "middle": panel.y + (panel.height - height) / 2,
        "bottom": panel.bottom - inset - height,
    }
    candidates: list[BBox] = []
    for zone in PlacementZone:
        vertical, horizontal = zone.value.split("_")
        candidates.append(BBox(across[horizontal], down[vertical], width, height))
    return candidates


def _blocks_gaze(candidate: BBox, actor: ResolvedPuppet, reach: float) -> bool:
    """Whether a balloon stands in the line of sight.

    Kress and van Leeuwen's "vectors": a character's gaze is a real compositional line
    that carries the reader's eye. Covering it reads as an obstruction.
    """
    if actor.gaze.length == 0:
        return False
    origin = actor.anchors.get("eyes")
    if origin is None:
        return False
    end = origin.translated(actor.gaze.dx * reach, actor.gaze.dy * reach)
    return _segment_hits_box(origin, end, candidate)


def _segment_hits_box(start: Point, end: Point, target: BBox) -> bool:
    """Sampled segment-box test.

    Sampling rather than exact clipping: this feeds a soft cost term, the segment is
    short, and an exact Liang-Barsky implementation would be more code than the
    approximation is worth.
    """
    samples = 12
    for step in range(samples + 1):
        t = step / samples
        x = start.x + (end.x - start.x) * t
        y = start.y + (end.y - start.y) * t
        if target.x <= x <= target.right and target.y <= y <= target.bottom:
            return True
    return False


def _reading_order_allows(placed: Sequence[BBox], candidate: BBox) -> bool:
    """Whether `candidate` may be read after everything in `placed`.

    Western reading is left to right, top to bottom, so a balloon may sit below an
    earlier one, or to its right, but never both above *and* left of it.

    Checked against **every** predecessor rather than only the immediately preceding
    balloon. The relation is not transitive: with balloons 0, 1, 2, it is entirely
    possible for 2 to be legal after 1 while sitting above and left of 0, and a reader
    following the page would then take them in the wrong order.
    """
    return all(
        candidate.y >= previous.y - READING_EPSILON
        or candidate.x >= previous.right - READING_EPSILON
        for previous in placed
    )


def _is_legal(
    candidate: BBox, actors: dict[str, ResolvedPuppet], panel: BBox, placed: list[BBox]
) -> bool:
    """The hard rules, which apply to anything carrying words.

    A box over a face is never acceptable whatever else it has going for it, a box
    outside the panel is not a box, and two overlapping boxes make both unreadable.
    """
    if not panel.contains(candidate):
        return False
    if any(candidate.intersects_circle(actor.face) for actor in actors.values()):
        return False
    return all(candidate.overlap_area(existing) == 0 for existing in placed)


def _occlusion_cost(candidate: BBox, hulls: dict[str, Polygon], forgive: str | None) -> float:
    """How much silhouette this box covers, normalised by its own area.

    `forgive` names an actor whose silhouette is half-weighted -- a balloon resting on
    its own speaker's shoulder reads naturally in a way that covering a bystander does
    not. A caption has no speaker, so it forgives nobody.
    """
    area = max(candidate.area, 1.0)
    shape = box(candidate.x, candidate.y, candidate.right, candidate.bottom)
    cost = 0.0
    for actor_id, hull in hulls.items():
        overlap = shape.intersection(hull).area
        if overlap:
            weight = 0.5 if actor_id == forgive else 1.0
            cost += W_OCCLUSION * weight * overlap / area
    return cost


def _mass_polygons(backdrop: ResolvedBackdrop | None) -> list[tuple[Polygon, float]]:
    """The backdrop as weighted shapes, built once per panel rather than per candidate.

    Returns:
        Each mass as a `shapely` polygon paired with what covering it costs.
    """
    if backdrop is None:
        return []
    return [
        (Polygon([(point.x, point.y) for point in polygon]), PLANE_OCCLUSION_WEIGHT[plane])
        for polygon, plane in backdrop.occluders()
    ]


def _mass_cost(candidate: BBox, masses: Sequence[tuple[Polygon, float]]) -> float:
    """How much backdrop this box covers, weighted by how near that backdrop is.

    The counterpart of `_occlusion_cost` for scenery. It never makes a position
    illegal -- a balloon over a sky is not a fault, it is the ordinary case -- so this
    only ever nudges a choice between candidates that are all legal.
    """
    if not masses:
        return 0.0
    area = max(candidate.area, 1.0)
    shape = box(candidate.x, candidate.y, candidate.right, candidate.bottom)
    cost = 0.0
    for polygon, weight in masses:
        overlap = shape.intersection(polygon).area
        if overlap:
            cost += W_MASS_OCCLUSION * weight * overlap / area
    return cost


def _edge_slack(candidate: BBox, panel: BBox) -> float:
    """Distance from the box to the nearest panel edge."""
    return min(
        candidate.x - panel.x,
        candidate.y - panel.y,
        panel.right - candidate.right,
        panel.bottom - candidate.bottom,
    )


def _score(
    candidate: BBox,
    *,
    speaker: ResolvedPuppet,
    actors: dict[str, ResolvedPuppet],
    hulls: dict[str, Polygon],
    panel: BBox,
    prefer: PlacementZone | None,
    placed: list[BBox],
    masses: Sequence[tuple[Polygon, float]],
) -> float:
    """Cost of putting a balloon here. Lower is better; infinity means illegal."""
    if not _is_legal(candidate, actors, panel, placed):
        return math.inf

    cost = _occlusion_cost(candidate, hulls, speaker.name) + _mass_cost(candidate, masses)

    diagonal = math.hypot(panel.width, panel.height)
    mouth = speaker.anchors.get("mouth", speaker.face.centre)
    cost += W_MOUTH_DISTANCE * (candidate.centre.distance_to(mouth) / diagonal)

    if prefer is not None:
        across, down = prefer.fractions
        target = Point(panel.x + panel.width * across, panel.y + panel.height * down)
        cost += W_PREFERRED_ZONE * (candidate.centre.distance_to(target) / diagonal)

    reach = speaker.face.r * GAZE_REACH_FACTOR
    for actor in actors.values():
        if _blocks_gaze(candidate, actor, reach):
            cost += W_GAZE_BLOCKING

    cost += W_EDGE * max(0.0, 1.0 - _edge_slack(candidate, panel) / (diagonal * 0.05))

    return cost


def _score_caption(
    candidate: BBox,
    *,
    actors: dict[str, ResolvedPuppet],
    hulls: dict[str, Polygon],
    panel: BBox,
    prefer: PlacementZone,
    placed: list[BBox],
    masses: Sequence[tuple[Polygon, float]],
) -> float:
    """Cost of putting a caption here. Lower is better; infinity means illegal.

    The same hard rules as a balloon, and two differences in the soft ones. There is
    no mouth to stay near, because a caption has no speaker in the panel. And the edge
    term is reversed: a balloon floating against the frame looks stranded, while a
    caption tucked into the corner is doing what a caption is for.
    """
    if not _is_legal(candidate, actors, panel, placed):
        return math.inf

    cost = _occlusion_cost(candidate, hulls, None) + _mass_cost(candidate, masses)

    diagonal = math.hypot(panel.width, panel.height)
    across, down = prefer.fractions
    target = Point(panel.x + panel.width * across, panel.y + panel.height * down)
    cost += W_PREFERRED_ZONE * (candidate.centre.distance_to(target) / diagonal)

    # Reach is taken from the largest face in the panel rather than a speaker's, since
    # a caption has none. It is the conservative choice: the longest sight line any
    # character in this panel has.
    reach = max((actor.face.r for actor in actors.values()), default=0.0) * GAZE_REACH_FACTOR
    for actor in actors.values():
        if _blocks_gaze(candidate, actor, reach):
            cost += W_GAZE_BLOCKING

    cost += W_CAPTION_EDGE * min(1.0, _edge_slack(candidate, panel) / (diagonal * 0.05))

    return cost


def _stop_at_face(start: Point, mouth: Point, face: Circle | None) -> Point:
    """Trim a tail so it stops on the face outline instead of inside the head.

    The mouth anchor sits well within the face circle, so a tail drawn all the way to
    it stabs through the middle of the head -- correct by the numbers and obviously
    wrong on the page. Letterers stop the tip at the outline, aimed at the mouth. This
    finds where the tail crosses that outline and ends there.
    """
    if face is None or not face.contains_point(mouth):
        return mouth

    dx, dy = mouth.x - start.x, mouth.y - start.y
    a = dx * dx + dy * dy
    if a == 0:
        return mouth
    fx, fy = start.x - face.cx, start.y - face.cy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - face.r * face.r
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return mouth

    root = math.sqrt(discriminant)
    # The first crossing along the segment is where the tail meets the outline.
    for t in sorted(((-b - root) / (2 * a), (-b + root) / (2 * a))):
        if 0.0 <= t <= 1.0:
            return Point(start.x + dx * t, start.y + dy * t)
    return mouth


def route_tail(
    balloon: BBox, mouth: Point, obstacles: list[Circle], speaker_face: Circle | None = None
) -> TailRoute:
    """Route a tail from the balloon toward the speaker's mouth.

    Straight is right almost always, so it is tried first. Only when the direct line
    crosses another character's face does the tail bend, and then via a single control
    point chosen from a handful of lateral offsets.

    Grid pathfinding is deliberately not used here. A tail is a short tapered stroke,
    and A-star produces a jointed path that looks nothing like one drawn by hand.
    """
    start = _rim_point(balloon, mouth)
    tip = _stop_at_face(start, mouth, speaker_face)
    if not any(segment_intersects_circle(start, tip, circle) for circle in obstacles):
        return TailRoute(start=start, end=tip)
    mouth = tip

    midpoint = Point((start.x + mouth.x) / 2, (start.y + mouth.y) / 2)
    dx, dy = mouth.x - start.x, mouth.y - start.y
    length = math.hypot(dx, dy) or 1.0
    normal_x, normal_y = -dy / length, dx / length

    for magnitude in (0.35, 0.7, 1.1, 1.6):
        for sign in (1.0, -1.0):
            offset = length * magnitude * sign
            control = midpoint.translated(normal_x * offset, normal_y * offset)
            if not _curve_hits(start, control, mouth, obstacles):
                return TailRoute(start=start, end=mouth, control=control)

    # Nothing clears the obstacle. A straight tail that clips a face is still better
    # than no tail at all, since a balloon with no pointer has no attributed speaker.
    return TailRoute(start=start, end=mouth)


def _curve_hits(start: Point, control: Point, end: Point, obstacles: list[Circle]) -> bool:
    samples = 16
    previous = start
    for step in range(1, samples + 1):
        t = step / samples
        inverse = 1 - t
        x = inverse * inverse * start.x + 2 * inverse * t * control.x + t * t * end.x
        y = inverse * inverse * start.y + 2 * inverse * t * control.y + t * t * end.y
        current = Point(x, y)
        if any(segment_intersects_circle(previous, current, circle) for circle in obstacles):
            return True
        previous = current
    return False


def _rim_point(balloon: BBox, toward: Point) -> Point:
    """Where a tail leaves the balloon outline, heading toward a point."""
    centre = balloon.centre
    dx, dy = toward.x - centre.x, toward.y - centre.y
    if dx == 0 and dy == 0:
        return centre
    # Scale the direction until it meets the box edge.
    scale_x = (balloon.width / 2) / abs(dx) if dx else math.inf
    scale_y = (balloon.height / 2) / abs(dy) if dy else math.inf
    scale = min(scale_x, scale_y)
    return centre.translated(dx * scale, dy * scale)


def caption_text(events: Sequence[ScriptEvent], index: int) -> str:
    """The text of a caption, with quotation marks where the kind calls for them.

    Blambot's rule for a run of spoken captions: an opening quote on each, a closing
    quote **only on the last**. Consecutive boxes are one continuous line of off-panel
    speech, and closing each of them would read as four separate interruptions.

    Applied here, before measurement, and carried through Panel Core as part of the
    resolved lines. Adding the marks in the emitter would make the text wider than the
    box that was drawn for it.

    Args:
        events: The whole script, because whether this caption closes depends on what
            follows it.
        index: Which entry to render.

    Returns:
        The text to letter.

    Example:
        >>> from scenet.ir import CaptionEvent, CaptionKind
        >>> from scenet.solve.balloons import caption_text
        >>> run = (
        ...     CaptionEvent(text="Get down!", kind=CaptionKind.SPOKEN),
        ...     CaptionEvent(text="All of you!", kind=CaptionKind.SPOKEN),
        ... )
        >>> caption_text(run, 0).endswith("”")
        False
        >>> caption_text(run, 1).endswith("”")
        True
    """
    event = events[index]
    if not isinstance(event, CaptionEvent) or not event.kind.is_quoted:
        return events[index].text

    following = events[index + 1] if index + 1 < len(events) else None
    continues = isinstance(following, CaptionEvent) and following.kind.is_quoted
    return OPENING_QUOTE + event.text + ("" if continues else CLOSING_QUOTE)


def place_script(
    events: Sequence[ScriptEvent],
    actors: dict[str, ResolvedPuppet],
    panel: BBox,
    *,
    metrics: FontMetrics | None = None,
    italic_metrics: FontMetrics | None = None,
    font_size: float | None = None,
    backdrop: ResolvedBackdrop | None = None,
) -> ScriptLayout:
    """Place every balloon and caption, in script order.

    Greedy rather than jointly optimised: each box is placed against those already
    down, which is exactly how reading order works -- a box constrains its successor,
    never its predecessor. That makes the greedy pass the natural formulation rather
    than a compromise.

    One pass over the whole script, not captions and then balloons. The two share the
    list of boxes already placed, so a caption written between two lines of dialogue
    is read between them.

    Args:
        events: The panel's script, in reading order.
        actors: Resolved puppets, keyed by actor id.
        panel: The rectangle to compose within, margins already applied.
        metrics: Font to measure roman lettering against.
        italic_metrics: Font to measure italic captions against. Defaults to the
            italic face of the same family.
        font_size: Override for dialogue size, in panel units.
        backdrop: The resolved setting, if the panel has one. Its masses are a soft
            cost, never an exclusion: a balloon over a sky is the ordinary case.

    Returns:
        Everything that carries words, placed.

    Raises:
        BalloonPlacementError: Some box had no legal position anywhere in the panel.
    """
    if not events:
        return ScriptLayout()

    size = font_size if font_size is not None else panel.height * FONT_SIZE_FRACTION
    caption_size = font_size if font_size is not None else panel.height * CAPTION_FONT_SIZE_FRACTION
    hulls = {actor_id: _hull_polygon(actor) for actor_id, actor in actors.items()}
    faces = [actor.face for actor in actors.values()]
    masses = _mass_polygons(backdrop)

    placed: list[BBox] = []
    captions: list[PlacedCaption] = []
    balloons: list[PlacedBalloon] = []

    for order, event in enumerate(events):
        if isinstance(event, CaptionEvent):
            captions.append(
                _place_caption(
                    event,
                    text=caption_text(events, order),
                    identifier=f"c{len(captions)}",
                    order=order,
                    actors=actors,
                    hulls=hulls,
                    panel=panel,
                    placed=placed,
                    font_size=caption_size,
                    metrics=metrics,
                    italic_metrics=italic_metrics,
                    masses=masses,
                )
            )
            placed.append(captions[-1].box)
            continue

        balloons.append(
            _place_balloon(
                event,
                identifier=f"b{len(balloons)}",
                order=order,
                actors=actors,
                hulls=hulls,
                faces=faces,
                panel=panel,
                placed=placed,
                font_size=size,
                metrics=metrics,
                masses=masses,
            )
        )
        placed.append(balloons[-1].box)

    return ScriptLayout(captions=tuple(captions), balloons=tuple(balloons))


def _place_balloon(
    event: SayEvent,
    *,
    identifier: str,
    order: int,
    actors: dict[str, ResolvedPuppet],
    hulls: dict[str, Polygon],
    faces: list[Circle],
    panel: BBox,
    placed: list[BBox],
    font_size: float,
    metrics: FontMetrics | None,
    masses: Sequence[tuple[Polygon, float]],
) -> PlacedBalloon:
    """Choose a position for one balloon and route its tail."""
    speaker = actors[event.by]
    block = layout_text(event.text, font_size=font_size, metrics=metrics)
    balloon_box = balloon_size(block)

    best: BBox | None = None
    best_cost = math.inf
    for candidate in _candidate_positions(speaker, balloon_box, panel):
        if not _reading_order_allows(placed, candidate):
            continue
        cost = _score(
            candidate,
            speaker=speaker,
            actors=actors,
            hulls=hulls,
            panel=panel,
            prefer=event.prefer,
            placed=placed,
            masses=masses,
        )
        if cost < best_cost:
            best, best_cost = candidate, cost

    if best is None:
        raise BalloonPlacementError(
            f"no legal position for balloon {order} spoken by '{event.by}': every "
            "candidate either covered a face, left the panel, overlapped another "
            "balloon, or broke reading order"
        )

    mouth = speaker.anchors.get("mouth", speaker.face.centre)
    # A speaker's own face does not obstruct their own tail -- the tail is
    # supposed to arrive there.
    obstacles = [face for face in faces if face is not speaker.face]
    return PlacedBalloon(
        id=identifier,
        speaker=event.by,
        order=order,
        kind=event.kind,
        box=best,
        block=block,
        tail=route_tail(best, mouth, obstacles, speaker_face=speaker.face),
    )


def _place_caption(
    event: CaptionEvent,
    *,
    text: str,
    identifier: str,
    order: int,
    actors: dict[str, ResolvedPuppet],
    hulls: dict[str, Polygon],
    panel: BBox,
    placed: list[BBox],
    font_size: float,
    metrics: FontMetrics | None,
    italic_metrics: FontMetrics | None,
    masses: Sequence[tuple[Polygon, float]],
) -> PlacedCaption:
    """Choose a position for one caption.

    The face it is measured against is the face it will be drawn in, which is the
    whole reason the italic kinds use a real italic file rather than a skew.
    """
    if event.kind.is_italic:
        face = italic_metrics or load_metrics(str(ITALIC_FONT_PATH))
    else:
        face = metrics or load_metrics()

    block = layout_text(text, font_size=font_size, metrics=face)
    caption_box = balloon_size(block, CAPTION_PADDING_FACTOR)

    best: BBox | None = None
    best_cost = math.inf
    for candidate in _caption_positions(caption_box, panel):
        if not _reading_order_allows(placed, candidate):
            continue
        cost = _score_caption(
            candidate,
            actors=actors,
            hulls=hulls,
            panel=panel,
            prefer=event.prefer,
            placed=placed,
            masses=masses,
        )
        if cost < best_cost:
            best, best_cost = candidate, cost

    if best is None:
        raise BalloonPlacementError(
            f"no legal position for caption {order}: every candidate either covered a "
            "face, left the panel, overlapped another box, or broke reading order"
        )

    return PlacedCaption(
        id=identifier, order=order, kind=event.kind, box=best, block=block, speaker=event.by
    )
