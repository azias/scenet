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
    LOW = "low"
    EYE_LEVEL = "eye_level"
    HIGH = "high"


class AnchorX(StrEnum):
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
    LEFT = "left"
    RIGHT = "right"


class Predicate(StrEnum):
    """Relation predicates, drawn from the spatial subset of the Visual Genome
    vocabulary rather than invented, so a scene stays convertible to and from the
    scene-graph representations used elsewhere in computer vision."""

    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    IN_FRONT_OF = "in_front_of"
    BEHIND = "behind"
    LOOKING_AT = "looking_at"
    GROUND_SHARED_WITH = "ground_shared_with"


class BalloonKind(StrEnum):
    SPEECH = "speech"
    THOUGHT = "thought"
    WHISPER = "whisper"
    SHOUT = "shout"


class PanelSpec(Strict):
    size: tuple[float, float] = (1000.0, 1000.0)
    margin: float = Field(default=0.0, ge=0.0)

    @property
    def width(self) -> float:
        return self.size[0]

    @property
    def height(self) -> float:
        return self.size[1]

    @model_validator(mode="after")
    def check_positive(self) -> Self:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("panel size must be positive")
        if self.margin * 2 >= min(self.width, self.height):
            raise ValueError("margin leaves no usable panel area")
        return self


class CameraSpec(Strict):
    shot: ShotType = ShotType.MEDIUM_SHOT
    angle: CameraAngle = CameraAngle.EYE_LEVEL


class CastMember(Strict):
    reference: str
    pose: str = "standing_neutral"
    at: AnchorX = AnchorX.CENTRE
    facing: Facing = Facing.RIGHT


class Relation(Strict):
    subject: str
    predicate: Predicate
    object: str

    @model_validator(mode="after")
    def check_not_reflexive(self) -> Self:
        if self.subject == self.object:
            raise ValueError(
                f"relation '{self.predicate}' cannot relate '{self.subject}' to itself"
            )
        return self


class SayEvent(Strict):
    by: str
    text: str = Field(min_length=1)
    prefer: PlacementZone | None = None
    kind: BalloonKind = BalloonKind.SPEECH


class PanelIR(Strict):
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
