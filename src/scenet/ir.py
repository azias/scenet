"""The intermediate representation: a validated semantic scene graph.

This is the language's real definition. The YAML surface syntax is one way to
produce it; a comic-script frontend will be another. Nothing here carries a
coordinate -- computing those is the solver's job.

Validation is strict on purpose. Panel sources are untrusted input, and a typo in a
predicate or an actor id should be a clear error at parse time rather than a silently
wrong picture.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Depth-first search marks, used by the ordering cycle check.
_UNVISITED, _ON_STACK, _DONE = 0, 1, 2


class Strict(BaseModel):
    """Reject unknown keys everywhere.

    A misspelled key that is silently ignored produces a panel that is subtly wrong
    with no indication of why, which is the worst possible failure for a language
    meant to be precise.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ShotType(StrEnum):
    """How tightly the camera frames the cast.

    Ordered from widest to tightest. A shot type is defined by a **crop landmark** plus
    a headroom fraction, both measured in head-heights -- not as a percentage of panel
    height, which would make the same shot mean different things in a tall panel and a
    wide one. `docs/reference/shot_types.md` is normative.

    The requested shot is an *upper bound on tightness*, not a promise. If the cast
    cannot fit across the panel at that framing the camera retreats, and says so in
    [`CompileResult.notes`][scenet.pipeline.CompileResult.notes].

    Example:
        >>> from scenet import ShotType
        >>> ShotType("close_up")
        <ShotType.CLOSE_UP: 'close_up'>
    """

    LONG_SHOT = "long_shot"
    WIDE = "wide"
    FULL_SHOT = "full_shot"
    MEDIUM_FULL = "medium_full"
    COWBOY = "cowboy"
    MEDIUM_SHOT = "medium_shot"
    MEDIUM_CLOSE_UP = "medium_close_up"
    CLOSE_UP = "close_up"
    BIG_CLOSE_UP = "big_close_up"
    EXTREME_CLOSE_UP = "extreme_close_up"


class CameraAngle(StrEnum):
    """The camera's height relative to the subject.

    Affects headroom rather than perspective: this is a flat, orthographic compiler, so
    a tilted camera does not foreshorten anything. What it changes is how much air sits
    above the head -- which is the compositional cue readers actually take from an
    angle, and one that survives being drawn flat.

    A **low** camera looks up and the subject looms, so the head rides high in the frame
    with little space above it. A **high** camera looks down, so the head sits lower and
    more space opens up above. See
    [`headroom_for`][scenet.solve.camera.headroom_for] for the exact factors.
    """

    LOW = "low"
    EYE_LEVEL = "eye_level"
    HIGH = "high"


class AnchorX(StrEnum):
    """Where along the panel width an actor would like to stand.

    Horizontal only. Actors stand on a ground line, so their vertical position is
    derived from the camera rather than requested -- which is why this has no vertical
    counterpart and [`PlacementZone`][scenet.ir.PlacementZone], used for balloons, does.

    These are *weak* preferences. Non-overlap and declared left-to-right ordering are
    required constraints and will override an anchor without complaint; two actors both
    asking for `center` will simply be pushed apart around it.
    """

    LEFT_EDGE = "left_edge"
    LEFT_THIRD = "left_third"
    CENTRE = "center"
    RIGHT_THIRD = "right_third"
    RIGHT_EDGE = "right_edge"


class PlacementZone(StrEnum):
    """Where in the panel a balloon would prefer to sit.

    Two-dimensional, unlike `AnchorX`: an actor is placed along the ground line and
    so only needs a horizontal anchor, whereas a balloon floats and needs both axes.
    These are hints of the weakest priority -- occlusion and reading order override
    them freely.
    """

    TOP_LEFT = "top_left"
    TOP_CENTRE = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    MIDDLE_CENTRE = "middle_center"
    MIDDLE_RIGHT = "middle_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTRE = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"

    @property
    def fractions(self) -> tuple[float, float]:
        """The zone's centre as a fraction of panel width and height."""
        vertical, horizontal = self.value.split("_")
        across = {"left": 0.25, "center": 0.5, "right": 0.75}[horizontal]
        down = {"top": 0.2, "middle": 0.5, "bottom": 0.8}[vertical]
        return across, down


class Facing(StrEnum):
    """Which way an actor is turned.

    Mirroring the whole puppet, gaze vector included. Defaults to `right`, so a cast
    written left to right ends up looking into the panel rather than out of it.
    """

    LEFT = "left"
    RIGHT = "right"


class Predicate(StrEnum):
    """How one actor stands in relation to another.

    Drawn from the spatial subset of the Visual Genome vocabulary rather than invented,
    so a scene stays convertible to and from the scene-graph representations used
    elsewhere in computer vision.

    `left_of` and `right_of` are the load-bearing ones: they are resolved at parse time
    into a linear ordering, because Cassowary cannot express the disjunction "A left of
    B *or* B left of A".
    """

    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    IN_FRONT_OF = "in_front_of"
    BEHIND = "behind"
    LOOKING_AT = "looking_at"
    GROUND_SHARED_WITH = "ground_shared_with"


class BalloonKind(StrEnum):
    """What kind of balloon carries a line, which is how it gets drawn.

    The kind changes the outline and the tail, never the placement: a whisper is
    subject to exactly the same face-avoidance and reading-order rules as a shout.

    | Kind | Outline | Tail |
    |---|---|---|
    | `speech` | plain ellipse | tapered pointer |
    | `thought` | scalloped cloud | trail of bubbles |
    | `whisper` | dashed ellipse | tapered pointer |
    | `shout` | jagged burst | tapered pointer |
    """

    SPEECH = "speech"
    THOUGHT = "thought"
    WHISPER = "whisper"
    SHOUT = "shout"


class PanelSpec(Strict):
    """The panel's own dimensions.

    Attributes:
        size: `(width, height)` in panel units. Everything else in the language is
            expressed relative to these, so they set what a unit means.
        margin: Inset on all four sides. Balloons are kept inside it; actors may bleed
            past it, which is ordinary comics practice.

    Example:
        >>> from scenet import PanelSpec
        >>> PanelSpec(size=(1200.0, 600.0)).width
        1200.0
    """

    size: tuple[float, float] = (1000.0, 1000.0)
    margin: float = Field(default=0.0, ge=0.0)

    @property
    def width(self) -> float:
        """Panel width in panel units."""
        return self.size[0]

    @property
    def height(self) -> float:
        """Panel height in panel units."""
        return self.size[1]

    @model_validator(mode="after")
    def check_positive(self) -> Self:
        """Reject a panel with no usable area.

        Returns:
            The validated spec.

        Raises:
            ValueError: A dimension is zero or negative, or the margins meet in the
                middle leaving nothing to compose in.
        """
        if self.width <= 0 or self.height <= 0:
            raise ValueError("panel size must be positive")
        if self.margin * 2 >= min(self.width, self.height):
            raise ValueError("margin leaves no usable panel area")
        return self


class CameraSpec(Strict):
    """How the panel is framed.

    Attributes:
        shot: Requested framing; an upper bound on tightness, see
            [`ShotType`][scenet.ir.ShotType].
        angle: Camera height, see [`CameraAngle`][scenet.ir.CameraAngle].

    There is exactly **one camera per panel**, and every actor is drawn at the scale it
    implies. Scaling each actor to its own crop landmark instead would make everybody
    the same apparent height and erase the body differences a comic uses to tell
    characters apart.
    """

    shot: ShotType = ShotType.MEDIUM_SHOT
    angle: CameraAngle = CameraAngle.EYE_LEVEL


class CastMember(Strict):
    """One character present in the panel.

    Attributes:
        reference: Name of a puppet in the library. This is what gets drawn; the key
            this member is filed under in `cast` is the actor id used everywhere else.
        pose: Named pose from that puppet's declared set.
        at: Preferred horizontal anchor.
        facing: Which way the figure is turned.

    The split between actor id and `reference` is what lets one puppet appear twice in
    a panel as two different people:

        cast:
          guard_left:  {reference: bob, pose: arms_crossed}
          guard_right: {reference: bob, pose: standing_neutral, facing: left}
    """

    reference: str
    pose: str = "standing_neutral"
    at: AnchorX = AnchorX.CENTRE
    facing: Facing = Facing.RIGHT


class Relation(Strict):
    """One staging fact, written as a sentence.

    Attributes:
        subject: Actor id the sentence is about.
        predicate: What relation holds.
        object: The other actor id.

    Authored as `alice left_of bob` rather than a three-key mapping because staging is
    read far more often than it is written, and a sentence is legible at a glance.

    Raises:
        pydantic.ValidationError: The subject and object are the same actor. No
            predicate here is meaningful reflexively.
    """

    subject: str
    predicate: Predicate
    object: str

    @model_validator(mode="after")
    def check_not_reflexive(self) -> Self:
        """Reject a relation between an actor and itself.

        Returns:
            The validated relation.

        Raises:
            ValueError: Subject and object are the same actor id. No predicate in the
                language means anything reflexively, so this is always a typo.
        """
        if self.subject == self.object:
            raise ValueError(
                f"relation '{self.predicate}' cannot relate '{self.subject}' to itself"
            )
        return self


class SayEvent(Strict):
    """One line of dialogue.

    Attributes:
        by: Actor id of the speaker; must be in the cast.
        text: What is said. Line breaking is the compiler's job, so write it as one
            string and do not insert newlines yourself.
        prefer: Optional hint about where the balloon should sit. The weakest of all
            the placement terms -- face avoidance and reading order override it.
        kind: Which sort of balloon carries it.

    Script order **is** reading order, and reading order is a hard constraint. Reorder
    these and you reorder the panel.
    """

    by: str
    text: str = Field(min_length=1)
    prefer: PlacementZone | None = None
    kind: BalloonKind = BalloonKind.SPEECH


class PanelIR(Strict):
    """A complete, validated panel: the language's real definition.

    Every frontend produces one of these and nothing else, which is what lets the YAML
    syntax and the comic-script syntax coexist without the solver knowing either exists.
    **Nothing here carries a coordinate** -- computing those is the solver's job, and
    keeping them out is what makes a panel reusable at any size.

    Attributes:
        panel: Dimensions and margin.
        camera: Framing and angle.
        cast: Actor id to character. Declaration order is not significant; `staging`
            decides left-to-right order.
        staging: Spatial and attentional relations between actors.
        script: Dialogue, in reading order.

    Validation is strict and total: unknown keys are rejected, every actor id mentioned
    in `staging` or `script` must exist in `cast`, and the ordering relations must not
    contain a cycle. A misspelled key that was silently ignored would produce a panel
    that is subtly wrong with no indication of why, which for a language meant to be
    precise is the worst possible failure.

    Example:
        >>> from scenet import parse_panel
        >>> panel = parse_panel("panel: {size: [800.0, 600.0]}")
        >>> panel.panel.width, panel.camera.shot.value
        (800.0, 'medium_shot')

    See Also:
        [`compile_ir`][scenet.pipeline.compile_ir], to turn one of these into geometry.
    """

    panel: PanelSpec = PanelSpec()
    camera: CameraSpec = CameraSpec()
    cast: dict[str, CastMember] = Field(default_factory=dict)
    staging: tuple[Relation, ...] = ()
    script: tuple[SayEvent, ...] = ()

    @model_validator(mode="after")
    def check_references_resolve(self) -> Self:
        """Every actor id mentioned anywhere must exist in the cast.

        Caught here rather than in the solver so the error names the offending
        identifier while the source is still in view.
        """
        known = set(self.cast)
        for relation in self.staging:
            for role, actor in (("subject", relation.subject), ("object", relation.object)):
                if actor not in known:
                    raise ValueError(
                        f"staging relation '{relation.predicate}' names unknown actor "
                        f"'{actor}' as {role}; cast is {sorted(known)}"
                    )
        for index, event in enumerate(self.script):
            if event.by not in known:
                raise ValueError(
                    f"script entry {index} is spoken by unknown actor '{event.by}'; "
                    f"cast is {sorted(known)}"
                )
        return self

    @model_validator(mode="after")
    def check_ordering_is_consistent(self) -> Self:
        """Horizontal ordering must not contain a cycle.

        The layout engine is a *linear* constraint solver, so ordering has to be
        decided before it runs -- see docs/spec/language.md. A cycle such as
        'a left_of b, b left_of a' has no solution, and detecting it here produces a
        comprehensible message instead of an opaque solver failure.
        """
        edges: dict[str, set[str]] = {actor: set() for actor in self.cast}
        for relation in self.staging:
            if relation.predicate is Predicate.LEFT_OF:
                edges[relation.subject].add(relation.object)
            elif relation.predicate is Predicate.RIGHT_OF:
                edges[relation.object].add(relation.subject)

        # Iterative depth-first search, so a deep cast cannot blow the Python stack.
        colour = dict.fromkeys(edges, _UNVISITED)
        for start in sorted(edges):
            if colour[start] != _UNVISITED:
                continue
            stack: list[tuple[str, bool]] = [(start, False)]
            while stack:
                node, leaving = stack.pop()
                if leaving:
                    colour[node] = _DONE
                    continue
                colour[node] = _ON_STACK
                stack.append((node, True))
                for neighbour in sorted(edges[node]):
                    if colour[neighbour] == _ON_STACK:
                        raise ValueError(
                            f"horizontal ordering is cyclic around '{neighbour}'; "
                            "left_of/right_of relations must form a consistent order"
                        )
                    if colour[neighbour] == _UNVISITED:
                        stack.append((neighbour, False))
        return self

    def ordering_constraints(self) -> tuple[tuple[str, str], ...]:
        """Normalised (left, right) pairs from both left_of and right_of relations."""
        pairs: list[tuple[str, str]] = []
        for relation in self.staging:
            if relation.predicate is Predicate.LEFT_OF:
                pairs.append((relation.subject, relation.object))
            elif relation.predicate is Predicate.RIGHT_OF:
                pairs.append((relation.object, relation.subject))
        return tuple(pairs)

    def gaze_targets(self) -> dict[str, str]:
        """Who is looking at whom.

        Returns:
            A mapping from each looking actor to the actor they are looking at. An
            actor may look at only one target, so a later `looking_at` relation for the
            same subject replaces an earlier one.

        Example:
            >>> from scenet import parse_panel
            >>> panel = parse_panel(
            ...     "{cast: {a: {reference: alice}, b: {reference: bob}},"
            ...     " staging: [a looking_at b]}"
            ... )
            >>> panel.gaze_targets()
            {'a': 'b'}
        """
        return {
            relation.subject: relation.object
            for relation in self.staging
            if relation.predicate is Predicate.LOOKING_AT
        }

    def ground_groups(self) -> tuple[frozenset[str], ...]:
        """Actors joined by ground_shared_with, as connected components.

        Union-find rather than pairwise handling, so that 'a with b' plus 'b with c'
        puts all three on one ground line without the author saying 'a with c'.
        """
        parent = {actor: actor for actor in self.cast}

        def find(actor: str) -> str:
            while parent[actor] != actor:
                parent[actor] = parent[parent[actor]]
                actor = parent[actor]
            return actor

        for relation in self.staging:
            if relation.predicate is Predicate.GROUND_SHARED_WITH:
                root_a, root_b = find(relation.subject), find(relation.object)
                if root_a != root_b:
                    parent[root_b] = root_a

        groups: dict[str, set[str]] = {}
        for actor in self.cast:
            groups.setdefault(find(actor), set()).add(actor)
        return tuple(frozenset(members) for members in groups.values() if len(members) > 1)
