"""Balloon placement and tail routing.

Placement is a scored search over candidate positions rather than a sweep of a cost
grid. Balloons belong in a small number of sensible places relative to their speaker
-- around the head, or tucked into a corner -- so generating those directly is both
cheaper than scanning cells and produces more natural results. This is the approach
used in the cartographic label-placement literature, which is the same problem.

The constraint that naive implementations miss is **reading order**. A balloon may
never sit above-and-left of the one before it in the script, because that makes the
panel read in the wrong order. That is a correctness bug in a comic, not a cosmetic
one, so it is enforced as a hard filter rather than scored.
"""

import math
from dataclasses import dataclass

from shapely.geometry import Polygon, box

from scenet.assets.kinematics import ResolvedPuppet
from scenet.geom import BBox, Circle, Point, segment_intersects_circle
from scenet.ir import BalloonKind, PlacementZone, SayEvent
from scenet.solve.text import FontMetrics, TextBlock, balloon_size, layout_text

# Candidate ring around the speaker's head.
RING_DIRECTIONS = 16
RING_RADII = (1.15, 1.5, 2.0)

# Cost weights. Tuned together; changing one in isolation will not do what you expect.
W_OCCLUSION = 1.0  # per unit of actor silhouette covered, normalised by balloon area
W_MOUTH_DISTANCE = 0.9  # keeps a balloon near whoever is speaking
W_PREFERRED_ZONE = 1.4  # honours an explicit `prefer:` hint
W_GAZE_BLOCKING = 0.7  # do not stand in front of what a character is looking at
W_EDGE = 0.25  # mild dislike of hugging the panel edge

# Tolerance when comparing balloon positions for reading order, in panel units.
READING_EPSILON = 2.0

# Balloon text size as a fraction of panel height.
FONT_SIZE_FRACTION = 0.035

# How far along a gaze direction the character is considered to be looking.
GAZE_REACH_FACTOR = 3.0


class BalloonPlacementError(ValueError):
    """No legal position exists for a balloon."""


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
        return self.control is not None


@dataclass(frozen=True, slots=True)
class PlacedBalloon:
    id: str
    speaker: str
    order: int
    kind: BalloonKind
    box: BBox
    block: TextBlock
    tail: TailRoute


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


def _reading_order_allows(previous: BBox | None, candidate: BBox) -> bool:
    """Whether `candidate` may follow `previous` in reading order.

    Western reading is left to right, top to bottom, so a balloon may sit below its
    predecessor, or to its right, but never both above *and* left of it.
    """
    if previous is None:
        return True
    below = candidate.y >= previous.y - READING_EPSILON
    right_of = candidate.x >= previous.right - READING_EPSILON
    return below or right_of


def _score(
    candidate: BBox,
    *,
    speaker: ResolvedPuppet,
    actors: dict[str, ResolvedPuppet],
    hulls: dict[str, Polygon],
    panel: BBox,
    prefer: PlacementZone | None,
    placed: list[BBox],
) -> float:
    """Cost of putting a balloon here. Lower is better; infinity means illegal."""
    if not panel.contains(candidate):
        return math.inf

    # A balloon over a face is never acceptable, whatever else it has going for it.
    for actor in actors.values():
        if candidate.intersects_circle(actor.face):
            return math.inf

    # Balloons must not overlap each other, or the lettering becomes unreadable.
    for existing in placed:
        if candidate.overlap_area(existing) > 0:
            return math.inf

    area = max(candidate.area, 1.0)
    shape = box(candidate.x, candidate.y, candidate.right, candidate.bottom)

    cost = 0.0
    for actor_id, hull in hulls.items():
        overlap = shape.intersection(hull).area
        if overlap:
            # Covering the speaker is more forgivable than covering someone else: a
            # balloon resting on its own speaker's shoulder reads naturally.
            weight = 0.5 if actor_id == speaker.name else 1.0
            cost += W_OCCLUSION * weight * overlap / area

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

    edge_slack = min(
        candidate.x - panel.x,
        candidate.y - panel.y,
        panel.right - candidate.right,
        panel.bottom - candidate.bottom,
    )
    cost += W_EDGE * max(0.0, 1.0 - edge_slack / (diagonal * 0.05))

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


def place_balloons(
    events: tuple[SayEvent, ...],
    actors: dict[str, ResolvedPuppet],
    panel: BBox,
    *,
    metrics: FontMetrics | None = None,
    font_size: float | None = None,
) -> tuple[PlacedBalloon, ...]:
    """Place every balloon in script order.

    Greedy rather than jointly optimised: each balloon is placed against those already
    down, which is exactly how reading order works -- a balloon constrains its
    successor, never its predecessor. That makes the greedy pass the natural
    formulation rather than a compromise.
    """
    if not events:
        return ()

    size = font_size if font_size is not None else panel.height * FONT_SIZE_FRACTION
    hulls = {actor_id: _hull_polygon(actor) for actor_id, actor in actors.items()}
    faces = [actor.face for actor in actors.values()]

    placed: list[BBox] = []
    results: list[PlacedBalloon] = []
    previous: BBox | None = None

    for order, event in enumerate(events):
        speaker = actors[event.by]
        block = layout_text(event.text, font_size=size, metrics=metrics)
        balloon_box = balloon_size(block)

        best: BBox | None = None
        best_cost = math.inf
        for candidate in _candidate_positions(speaker, balloon_box, panel):
            if not _reading_order_allows(previous, candidate):
                continue
            cost = _score(
                candidate,
                speaker=speaker,
                actors=actors,
                hulls=hulls,
                panel=panel,
                prefer=event.prefer,
                placed=placed,
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
        results.append(
            PlacedBalloon(
                id=f"b{order}",
                speaker=event.by,
                order=order,
                kind=event.kind,
                box=best,
                block=block,
                tail=route_tail(best, mouth, obstacles, speaker_face=speaker.face),
            )
        )
        placed.append(best)
        previous = best

    return tuple(results)
