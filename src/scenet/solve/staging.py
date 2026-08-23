"""Horizontal placement, vertical grounding and draw order.

This is where Cassowary earns its place. The arithmetic is trivial -- centring a
figure on a third is one division -- but the *conflicts* are not. Two actors both
asked to stand centre must be pushed apart; a crowded panel must let figures bleed off
the edge rather than overlap. Expressed as priorities, that resolves itself. Written
by hand it becomes an ever-growing cascade of special cases.

Priorities used:

  required  actors never overlap, and keep their declared left-to-right order
  strong    actors stay inside the panel
  weak      actors sit on their requested anchor

Bounds are deliberately *strong* rather than required. Letting a figure bleed past the
panel edge is ordinary comics practice, and far better than refusing to compile a
crowded panel.
"""

from dataclasses import dataclass
from itertools import pairwise

from kiwisolver import Solver, UnsatisfiableConstraint, Variable, strength

from scenet.assets.contract import PuppetLibrary, PuppetSpec
from scenet.assets.kinematics import ResolvedPuppet, resolve
from scenet.errors import LayoutError
from scenet.geom import Point
from scenet.ir import AnchorX, Facing, PanelIR, Predicate
from scenet.solve.camera import CameraSolution, solve_camera

# Where each anchor sits, as a fraction of panel width. The edge anchors are inset
# rather than flush so that "left_edge" still leaves a sliver of margin, which reads
# as deliberate composition rather than as an accident.
ANCHOR_FRACTIONS: dict[AnchorX, float] = {
    AnchorX.LEFT_EDGE: 0.12,
    AnchorX.LEFT_THIRD: 1.0 / 3.0,
    AnchorX.CENTRE: 0.5,
    AnchorX.RIGHT_THIRD: 2.0 / 3.0,
    AnchorX.RIGHT_EDGE: 0.88,
}

# Clear space between neighbouring actors, as a fraction of panel width.
MIN_GAP_FRACTION = 0.015

# When retreating the camera to fit the cast, aim slightly inside the usable width.
# Fitting exactly puts the outermost figures flush against both panel edges, which
# reads as cramped rather than composed -- and lands the bounds constraint precisely
# on a floating-point boundary, where it may or may not be satisfied.
FIT_SLACK = 0.96


@dataclass(frozen=True, slots=True)
class Placement:
    """Where one actor's root joint ends up, and how it is drawn."""

    actor_id: str
    reference: str
    pose: str
    x: float
    y: float
    scale: float
    facing_right: bool
    depth: int

    @property
    def origin(self) -> Point:
        """Where this actor's root joint lands, as a point."""
        return Point(self.x, self.y)


@dataclass(frozen=True, slots=True)
class _Extent:
    """How far an actor's silhouette reaches either side of its root joint."""

    left: float
    right: float

    @property
    def centre_offset(self) -> float:
        return (self.left + self.right) / 2


def _extent_of(posed: ResolvedPuppet, origin: Point) -> _Extent:
    bounds = posed.bounds
    return _Extent(left=bounds.x - origin.x, right=bounds.right - origin.x)


def horizontal_order(panel: PanelIR) -> tuple[str, ...]:
    """A total left-to-right order over the cast.

    Declared `left_of` relations are honoured; everything else is broken by anchor
    position and then by actor id. The tiebreak matters more than it looks: the solver
    needs a *total* order to write non-overlap constraints against, and it must be the
    same total order on every run or the output stops being deterministic.
    """
    actors = set(panel.cast)
    successors: dict[str, set[str]] = {actor: set() for actor in actors}
    in_degree: dict[str, int] = dict.fromkeys(actors, 0)

    for left, right in panel.ordering_constraints():
        if right not in successors[left]:
            successors[left].add(right)
            in_degree[right] += 1

    def sort_key(actor: str) -> tuple[float, str]:
        return (ANCHOR_FRACTIONS[panel.cast[actor].at], actor)

    ready = sorted((actor for actor in actors if in_degree[actor] == 0), key=sort_key)
    order: list[str] = []
    while ready:
        actor = ready.pop(0)
        order.append(actor)
        for successor in sorted(successors[actor]):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                ready.append(successor)
        ready.sort(key=sort_key)

    if len(order) != len(actors):
        # The IR validator rejects cycles, so reaching here means a new relation type
        # started contributing edges without updating that check.
        raise LayoutError("horizontal ordering is cyclic; this should have failed validation")
    return tuple(order)


def depth_order(panel: PanelIR) -> dict[str, int]:
    """Painter's order from `in_front_of` / `behind` relations.

    Depth is the longest chain of actors behind a given one, so anything not mentioned
    stays at zero and the common case adds no noise to the output.
    """
    behind: dict[str, set[str]] = {actor: set() for actor in panel.cast}
    for relation in panel.staging:
        if relation.predicate is Predicate.IN_FRONT_OF:
            behind[relation.subject].add(relation.object)
        elif relation.predicate is Predicate.BEHIND:
            behind[relation.object].add(relation.subject)

    depths: dict[str, int] = {}

    def depth_of(actor: str, seen: frozenset[str]) -> int:
        if actor in depths:
            return depths[actor]
        if actor in seen:
            raise LayoutError(f"depth ordering is cyclic around '{actor}'")
        value = 0
        for other in sorted(behind[actor]):
            value = max(value, depth_of(other, seen | {actor}) + 1)
        depths[actor] = value
        return value

    for actor in sorted(panel.cast):
        depth_of(actor, frozenset())
    return depths


def _vertical_placement(
    panel: PanelIR, puppets: dict[str, PuppetSpec], camera: CameraSolution
) -> dict[str, float]:
    """Root-joint y for every actor.

    Actors sharing a ground line get their *feet* aligned, not their heads -- which is
    what lets two characters of different heights stand together convincingly. Each
    group is framed from its own first member; actors in no group are framed alone.
    """
    ys: dict[str, float] = {}
    grouped: set[str] = set()

    for group in panel.ground_groups():
        # Sorted so the group's framing reference is stable across runs.
        members = sorted(group)
        anchor_actor = members[0]
        anchor_y = camera.root_y_framed(puppets[anchor_actor])
        ground = camera.ground_y_of(puppets[anchor_actor], anchor_y)
        for member in members:
            ys[member] = camera.root_y_on_ground(puppets[member], ground)
            grouped.add(member)

    for actor in panel.cast:
        if actor not in grouped:
            ys[actor] = camera.root_y_framed(puppets[actor])
    return ys


def _fit_cast_across_frame(
    panel: PanelIR, puppets: dict[str, PuppetSpec], camera: CameraSolution
) -> CameraSolution:
    """Retreat the camera until the whole cast fits across the frame.

    Without this, asking for a medium shot of two people produces two figures each
    wider than half the panel; non-overlap then shoves one of them off the edge. A
    real camera would move back instead, so that is what happens here -- see
    `CameraSolution.pulled_back_to` for why loosening the shot is the correct
    reading rather than a violation of it.

    Silhouette widths scale linearly, so they are measured once at unit scale and the
    fitting scale follows directly. No search required.
    """
    native_total = 0.0
    for actor, member in panel.cast.items():
        posed = resolve(
            puppets[actor],
            pose=member.pose,
            facing_right=True,
            scale=1.0,
            origin=Point(0.0, 0.0),
        )
        native_total += posed.bounds.width

    usable = panel.panel.width - 2 * panel.panel.margin
    gaps = panel.panel.width * MIN_GAP_FRACTION * (len(panel.cast) - 1)
    room_for_figures = usable - gaps
    if room_for_figures <= 0 or native_total <= 0:
        # Gaps alone exceed the panel: nothing sensible to fit to, so leave the
        # requested framing alone and let the solver push figures off the edge.
        return camera
    return camera.pulled_back_to(room_for_figures * FIT_SLACK / native_total)


def _facing_for(panel: PanelIR, actor: str, order: tuple[str, ...]) -> bool:
    """Resolve which way an actor turns.

    An explicit `facing` always wins. Otherwise `looking_at` turns the actor toward
    its target, using the declared left-to-right order rather than solved coordinates
    -- because facing has to be known *before* solving, since it changes the
    silhouette's width and therefore the constraints themselves.
    """
    member = panel.cast[actor]
    targets = panel.gaze_targets()
    if actor in targets:
        target = targets[actor]
        if target in order and actor in order:
            return order.index(target) > order.index(actor)
    return member.facing is Facing.RIGHT


def solve_staging(
    panel: PanelIR, library: PuppetLibrary, camera: CameraSolution | None = None
) -> tuple[tuple[Placement, ...], CameraSolution]:
    """Resolve every actor's position, scale, facing and draw order."""
    if not panel.cast:
        raise LayoutError("panel has no cast; there is nothing to place")

    puppets = {actor: library.get(member.reference) for actor, member in panel.cast.items()}

    if camera is None:
        # The reference is the first actor the author wrote, which is the one the
        # panel is about.
        reference = next(iter(panel.cast))
        camera = solve_camera(
            puppets[reference],
            shot=panel.camera.shot,
            angle=panel.camera.angle,
            panel_height=panel.panel.height,
        )

    order = horizontal_order(panel)
    depths = depth_order(panel)
    camera = _fit_cast_across_frame(panel, puppets, camera)
    ys = _vertical_placement(panel, puppets, camera)
    facings = {actor: _facing_for(panel, actor, order) for actor in panel.cast}

    # Silhouette extents must be measured with the final facing and scale already
    # applied, because mirroring an asymmetric pose changes how far it reaches.
    extents: dict[str, _Extent] = {}
    for actor in panel.cast:
        origin = Point(0.0, ys[actor])
        posed = resolve(
            puppets[actor],
            pose=panel.cast[actor].pose,
            facing_right=facings[actor],
            scale=camera.scale,
            origin=origin,
        )
        extents[actor] = _extent_of(posed, origin)

    width = panel.panel.width
    margin = panel.panel.margin
    gap = width * MIN_GAP_FRACTION

    solver = Solver()
    variables = {actor: Variable(f"x_{actor}") for actor in panel.cast}

    for actor, variable in variables.items():
        extent = extents[actor]
        solver.addConstraint((variable + extent.left >= margin) | strength.strong)
        solver.addConstraint((variable + extent.right <= width - margin) | strength.strong)

        target = width * ANCHOR_FRACTIONS[panel.cast[actor].at]
        solver.addConstraint((variable + extent.centre_offset == target) | strength.weak)

    for left, right in pairwise(order):
        solver.addConstraint(
            (variables[left] + extents[left].right + gap <= variables[right] + extents[right].left)
            | strength.required
        )

    try:
        solver.updateVariables()
    except UnsatisfiableConstraint as exc:  # pragma: no cover -- only required
        # constraints can be unsatisfiable, and the only required ones are
        # non-overlap over an acyclic order, which is always solvable on an
        # unbounded line. Kept so a future required constraint fails legibly.
        raise LayoutError(
            "could not place the cast: the required non-overlap constraints conflict"
        ) from exc

    placements = tuple(
        Placement(
            actor_id=actor,
            reference=panel.cast[actor].reference,
            pose=panel.cast[actor].pose,
            x=variables[actor].value(),
            y=ys[actor],
            scale=camera.scale,
            facing_right=facings[actor],
            depth=depths[actor],
        )
        # Emitted in draw order, then by the left-to-right order, so the output
        # sequence is itself deterministic and reads naturally in a diff.
        for actor in sorted(panel.cast, key=lambda a: (depths[a], order.index(a)))
    )
    return placements, camera
