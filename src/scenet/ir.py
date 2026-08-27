"""The intermediate representation: a validated semantic scene graph.

This is the language's real definition. The YAML surface syntax is one way to
produce it; a comic-script frontend will be another. Nothing here carries a
coordinate -- computing those is the solver's job.

Validation is strict on purpose. Panel sources are untrusted input, and a typo in a
predicate or an actor id should be a clear error at parse time rather than a silently
wrong picture.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenet.errors import RuleViolationError

__all__ = [
    "AnchorX",
    "BalloonKind",
    "CameraAngle",
    "CameraSpec",
    "CaptionEvent",
    "CaptionKind",
    "CastMember",
    "Facing",
    "Horizon",
    "Mass",
    "MassKind",
    "PanelIR",
    "PanelSpec",
    "PlacementZone",
    "Plane",
    "Predicate",
    "Relation",
    "SayEvent",
    "SettingSpec",
    "ShotType",
    "Spans",
    "Strict",
    "TimeOfDay",
    "Weather",
]

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

    Ordered from widest to tightest, and the order is enforced by a test: reading down
    the ladder, the figure never gets smaller.

    A shot type is defined by two things in two different units. The **crop landmark**
    is anatomical -- the waist, the chest, the shoulders -- which is what stops a shot
    type baking in one body and one pose; naming a fraction of panel height instead
    would do exactly that. The **headroom** is a plain fraction of panel height, because
    it is about composition within the frame rather than anatomy.
    `docs/reference/shot_types.md` is normative.

    The requested shot is an *upper bound on tightness*, not a promise. If the cast
    cannot fit across the panel at that framing the camera retreats, and says so in
    :attr:`CompileResult.notes <scenet.pipeline.CompileResult.notes>`.

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
    :func:`headroom_for <scenet.solve.camera.headroom_for>` for the exact factors.
    """

    LOW = "low"
    EYE_LEVEL = "eye_level"
    HIGH = "high"


class AnchorX(StrEnum):
    """Where along the panel width an actor would like to stand.

    Horizontal only. Actors stand on a ground line, so their vertical position is
    derived from the camera rather than requested -- which is why this has no vertical
    counterpart and :class:`PlacementZone <scenet.ir.PlacementZone>`, used for balloons, does.

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


class CaptionKind(StrEnum):
    """What a caption box is doing, which is how it gets set.

    These four are the letterers' own vocabulary, taken from Blambot's *Comic Book
    Grammar & Tradition* rather than invented -- for the same reason the predicates
    were taken from Visual Genome. Note that "narration", the obvious guess, is not
    among them.

    | Kind | What it is | How it is set |
    |---|---|---|
    | `locale` | Location and time -- "Midnight. The docks." | Italic |
    | `monologue` | A character's inner voice | Italic |
    | `spoken` | Off-panel dialogue | Roman, in quotation marks |
    | `editorial` | The voice of the writer or editor | Italic |

    `monologue` has largely replaced the thought balloon in modern comics, so a panel
    has two ways to render an inner voice: this and
    :attr:`BalloonKind.THOUGHT <scenet.ir.BalloonKind>`. Both are correct. They are
    different eras of the same convention, not a duplication.
    """

    LOCALE = "locale"
    MONOLOGUE = "monologue"
    SPOKEN = "spoken"
    EDITORIAL = "editorial"

    @property
    def is_italic(self) -> bool:
        """Whether this kind is set in italic. Everything except `spoken`."""
        return self is not CaptionKind.SPOKEN

    @property
    def is_quoted(self) -> bool:
        """Whether this kind takes quotation marks.

        `spoken` only, because it is the one kind where somebody is talking.
        """
        return self is CaptionKind.SPOKEN


class MassKind(StrEnum):
    """What a tonal mass in the backdrop is made of.

    Subsetted from the **supercategories** of
    [COCO-Stuff](https://arxiv.org/pdf/1612.03716), the canonical taxonomy of *stuff* --
    "amorphous background regions" as opposed to *things* with a well-defined shape.
    Its own argument is that stuff classes explain scene type and the geometric
    properties of a scene, which is exactly the job here. Taken from an existing
    vocabulary for the same reason the predicates were taken from Visual Genome.

    **Deliberately not the leaf names.** COCO-Stuff's actual classes are
    `building-other`, `sky-other`, `wall-brick`, `water-other` and so on, where the
    `-other` suffix marks the catch-all inside a supercategory. `building-other` is not
    a word anyone should have to type.

    Seven are outdoor -- `building`, `ground`, `plant`, `sky`, `solid`, `structural`,
    `water` -- and five indoor: `ceiling`, `floor`, `furniture`, `wall`, `window`.
    COCO-Stuff's own indoor/outdoor split is where that distinction comes from, so it
    did not have to be invented either. Its `textile`, `food` and `rawmaterial`
    supercategories are left out: drapery and objects, not scene-defining masses.

    A kind decides the **shape** a mass takes, never its value. Value comes from the
    plane, which is what keeps the notan reading honest -- see
    :class:`Plane <scenet.ir.Plane>`.
    """

    BUILDING = "building"
    CEILING = "ceiling"
    FLOOR = "floor"
    FURNITURE = "furniture"
    GROUND = "ground"
    PLANT = "plant"
    SKY = "sky"
    SOLID = "solid"
    STRUCTURAL = "structural"
    WALL = "wall"
    WATER = "water"
    WINDOW = "window"


class Plane(StrEnum):
    """How far back a mass sits, which decides both its draw order and its value.

    Four planes, ordered from the back of the panel forward. They map onto the existing
    integer :attr:`CoreActor.depth <scenet.core.CoreActor.depth>` painter's order rather
    than introducing a second ordering mechanism: the three backdrop planes take
    negative depths, and `foreground` takes one above the frontmost actor, so a
    foreground mass draws over the cast the way a silhouetted doorway does.

    Value follows from the plane and from nothing else, which is what makes the
    [aerial perspective](https://en.wikipedia.org/wiki/Aerial_perspective) rule
    parametric: with distance, contrast drops toward the atmosphere. Reading front to
    back, a mass never gets darker. See
    :func:`tone_for <scenet.solve.backdrop.tone_for>`.
    """

    FOREGROUND = "foreground"
    NEAR = "near"
    MID = "mid"
    FAR = "far"


class Spans(StrEnum):
    """How much of the panel's width a mass covers.

    Resolved to an extent in the frontend, and that is **not cosmetic**. `CLAUDE.md`
    requires any construct that would reintroduce a left/right disjunction to resolve it
    before the solver, because Cassowary cannot express "A left of B *or* B left of A".
    A span is an absolute extent rather than a relation, which is what stops masses
    becoming an unordered `beside`.
    """

    FULL = "full"
    LEFT = "left"
    CENTRE = "center"
    RIGHT = "right"

    @property
    def fractions(self) -> tuple[float, float]:
        """The extent as `(start, end)` fractions of panel width.

        `left` and `right` overlap slightly in the middle. Butting them exactly would
        leave a seam down the centre of the panel wherever both are used at the same
        plane, which reads as a mistake rather than as two masses.

        Example:
            >>> from scenet.ir import Spans
            >>> Spans.FULL.fractions
            (0.0, 1.0)
        """
        return {
            Spans.FULL: (0.0, 1.0),
            Spans.LEFT: (0.0, 0.56),
            Spans.CENTRE: (0.26, 0.74),
            Spans.RIGHT: (0.44, 1.0),
        }[self]


class Horizon(StrEnum):
    """Where the ground meets whatever is behind it.

    One line for the whole panel, which every mass is composed against: masses of the
    ground sort start at it and run down, masses that stand in the world rise from it.
    Named rather than given as a number for the same reason `at:` is -- the author is
    saying how the panel is composed, not typing a coordinate.
    """

    HIGH = "high"
    MID = "mid"
    LOW = "low"

    @property
    def fraction(self) -> float:
        """Where the line sits, as a fraction of panel height.

        A **high** horizon sits nearer the top of the frame, so more ground is in view
        and the camera reads as looking down over it.

        Example:
            >>> from scenet.ir import Horizon
            >>> Horizon.HIGH.fraction < Horizon.LOW.fraction
            True
        """
        return {Horizon.HIGH: 0.38, Horizon.MID: 0.55, Horizon.LOW: 0.72}[self]


class TimeOfDay(StrEnum):
    """When the panel happens, which shifts the whole value ladder.

    Each time supplies two numbers -- the value of the foreground and the value of the
    atmosphere -- and the planes are spaced evenly between them. So `night` is not a
    blue filter over a daytime panel: it is a darker, more compressed ladder, which is
    what night actually does to a drawn scene. The ladder stays monotonic in depth at
    every time of day, by construction rather than by tuning.
    """

    DAWN = "dawn"
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"


class Weather(StrEnum):
    """What the air is doing between the reader and the panel.

    `clouds` and `fog` are first-class *stuff* in COCO-Stuff, so this vocabulary did not
    have to be invented either. `fog` renders as a turbulence veil over the backdrop;
    `rain` and `snow` add that veil as cloud and put falling marks over everything,
    because weather is between the reader and the figures rather than behind them.
    """

    CLEAR = "clear"
    RAIN = "rain"
    FOG = "fog"
    SNOW = "snow"


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
            raise RuleViolationError("panel size must be positive", rule="panel-geometry")
        if self.margin * 2 >= min(self.width, self.height):
            raise RuleViolationError("margin leaves no usable panel area", rule="panel-geometry")
        return self


class CameraSpec(Strict):
    """How the panel is framed.

    Attributes:
        shot: Requested framing; an upper bound on tightness, see
            :class:`ShotType <scenet.ir.ShotType>`.
        angle: Camera height, see :class:`CameraAngle <scenet.ir.CameraAngle>`.

    There is exactly **one camera per panel**, and every actor is drawn at the scale it
    implies. Scaling each actor to its own crop landmark instead would make everybody
    the same apparent height and erase the body differences a comic uses to tell
    characters apart.
    """

    shot: ShotType = ShotType.MEDIUM_SHOT
    angle: CameraAngle = CameraAngle.EYE_LEVEL


class Mass(Strict):
    """One tonal mass in the backdrop: what it is, how far back, how wide.

    Attributes:
        kind: What the mass is made of, which decides its silhouette.
        plane: How far back it sits, which decides its value and its draw order.
        spans: How much of the panel's width it covers.

    **Backdrops are never author-drawn**, and there are two reasons. The structural one:
    crisp architecture needs a vanishing point, and this is deliberately a flat,
    orthographic compiler, so drawn buildings would fight the compiler's own model.
    Soft tonal masses have no perspective to get wrong.

    The second is that this is how comics actually establish place. Notan -- the
    Japanese light/dark mass principle, which reached Western art teaching through
    Arthur Wesley Dow's *Composition* (1899) -- says place is read from the arrangement
    of masses rather than from rendered detail.

    Example:
        >>> from scenet.ir import Mass, MassKind
        >>> Mass(kind=MassKind.SKY).plane.value
        'mid'
    """

    kind: MassKind
    plane: Plane = Plane.MID
    spans: Spans = Spans.FULL


class SettingSpec(Strict):
    """Where and when the panel happens, as tonal masses rather than drawn geometry.

    Attributes:
        horizon: Where the ground meets what is behind it.
        masses: The backdrop, back to front. Written directly, or produced by naming a
            place in the surface syntax.
        time: When it happens, which shifts the value ladder.
        weather: What the air is doing.

    **There is no `place` field here, deliberately.** `place: docks` is surface syntax
    that the frontend expands into exactly the mass list an author could have written
    themselves -- the same treatment `alice left_of bob` gets, which reaches the IR as a
    :class:`Relation <scenet.ir.Relation>` and never as text. That is what keeps a
    preset a library for convenience rather than a second, opaque format: by the time
    anything downstream sees a backdrop, there is one representation of it.

    A panel with no masses and clear weather has no backdrop at all, which is what every
    panel written before this block existed still gets.

    Example:
        >>> from scenet import parse_panel
        >>> panel = parse_panel("setting: {place: docks, time: night}")
        >>> panel.setting.time.value, len(panel.setting.masses) > 0
        ('night', True)
    """

    horizon: Horizon = Horizon.MID
    masses: tuple[Mass, ...] = ()
    time: TimeOfDay = TimeOfDay.DAY
    weather: Weather = Weather.CLEAR

    @property
    def is_bare(self) -> bool:
        """Whether there is nothing to draw: no masses, and nothing in the air."""
        return not self.masses and self.weather is Weather.CLEAR


class CastMember(Strict):
    """One character present in the panel.

    Attributes:
        reference: Name of a puppet in the library. This is what gets drawn; the key
            this member is filed under in `cast` is the actor id used everywhere else.
        pose: Named pose from that puppet's declared set.
        expression: Named expression from that puppet's declared set. Selected by name
            exactly as a pose is, because a face is the same kind of thing as a body:
            a small closed set of arrangements the character can be in.
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
    expression: str = "neutral"
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
            raise RuleViolationError(
                f"relation '{self.predicate}' cannot relate '{self.subject}' to itself",
                rule="reflexive-relation",
            )
        return self


class SayEvent(Strict):
    """One line of dialogue.

    Attributes:
        verb: Always `say`. The tag the surface syntax writes as `- say: {...}`,
            carried into the model so that a script entry knows which sort of event it
            is without the frontend having to remember.
        by: Actor id of the speaker; must be in the cast.
        text: What is said. Line breaking is the compiler's job, so write it as one
            string and do not insert newlines yourself.
        prefer: Optional hint about where the balloon should sit. The weakest of all
            the placement terms -- face avoidance and reading order override it.
        kind: Which sort of balloon carries it.

    Script order **is** reading order, and reading order is a hard constraint. Reorder
    these and you reorder the panel.
    """

    verb: Literal["say"] = "say"
    by: str
    text: str = Field(min_length=1)
    prefer: PlacementZone | None = None
    kind: BalloonKind = BalloonKind.SPEECH


class CaptionEvent(Strict):
    """One caption box: the panel speaking in its own voice.

    A caption is what lets a panel say where and when it happens without a character
    having to explain it out loud. `MIDNIGHT. THE DOCKS.` in the corner does the work
    of an establishing shot with no artwork at all, which is how comics established
    place long before they had reliable backgrounds.

    Attributes:
        verb: Always `caption`, written as `- caption: {...}`.
        text: What the box says. As with dialogue, line breaking is computed.
        kind: What the box is doing, which decides how it is set.
        prefer: Where it would like to sit. Defaults to `top_left`, which is where a
            `locale` caption conventionally goes.
        by: Who is speaking, for a `spoken` caption only.

    **A caption is not a fifth balloon kind.** It has no speaker to point at and no
    tail, and :attr:`CoreBalloon.tail <scenet.core.CoreBalloon.tail>` is required -- a
    fifth kind would mean inventing a speaker and leaving a field dead.

    `by` is the one place where the rule that every actor id resolves does not hold,
    and deliberately: an off-panel speaker is not in the panel, so requiring them to be
    in the cast would defeat the point of saying they are off panel.

    Example:
        >>> from scenet.ir import CaptionEvent
        >>> CaptionEvent(text="Midnight. The docks.").kind.value
        'locale'
    """

    verb: Literal["caption"] = "caption"
    text: str = Field(min_length=1)
    kind: CaptionKind = CaptionKind.LOCALE
    prefer: PlacementZone = PlacementZone.TOP_LEFT
    by: str | None = None

    @model_validator(mode="after")
    def check_speaker_is_meaningful(self) -> Self:
        """Only an off-panel line has a speaker to name.

        Returns:
            The validated event.

        Raises:
            ValueError: `by` was given for a kind that has no speaker. A locale box
                states a place; nobody says it, so naming who did is a mistake worth
                reporting rather than a field to ignore.
        """
        if self.by is not None and not self.kind.is_quoted:
            raise RuleViolationError(
                f"only a 'spoken' caption may name a speaker, but this one is '{self.kind.value}'",
                rule="caption-speaker",
            )
        return self


#: One entry in a panel's script. Tagged by a defaulted literal rather than a pydantic
#: discriminator: a discriminator requires the tag to be present in the input, which
#: would break every caller that constructs `SayEvent(...)` directly. The default still
#: produces an unambiguous `anyOf` in the generated JSON Schema.
ScriptEvent = SayEvent | CaptionEvent


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
        script: Dialogue and captions, in reading order.

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
        :func:`compile_ir <scenet.pipeline.compile_ir>`, to turn one of these into geometry.
    """

    panel: PanelSpec = PanelSpec()
    camera: CameraSpec = CameraSpec()
    setting: SettingSpec = SettingSpec()
    cast: dict[str, CastMember] = Field(default_factory=dict)
    staging: tuple[Relation, ...] = ()
    script: tuple[ScriptEvent, ...] = ()

    @model_validator(mode="after")
    def check_references_resolve(self) -> Self:
        """Every actor id mentioned anywhere must exist in the cast.

        Caught here rather than in the solver so the error names the offending
        identifier while the source is still in view.
        """
        known = set(self.cast)
        for index, relation in enumerate(self.staging):
            for role, actor in (("subject", relation.subject), ("object", relation.object)):
                if actor not in known:
                    raise RuleViolationError(
                        f"staging relation '{relation.predicate}' names unknown actor "
                        f"'{actor}' as {role}; cast is {sorted(known)}",
                        rule="unknown-actor",
                        loc=("staging", index),
                    )
        # Captions are skipped rather than exempted by accident. A `spoken` caption's
        # `by` names somebody *off panel*, so it is not in the cast by definition and
        # checking it here would make the field impossible to use for what it is for.
        for index, event in enumerate(self.script):
            if not isinstance(event, SayEvent):
                continue
            if event.by not in known:
                raise RuleViolationError(
                    f"script entry {index} is spoken by unknown actor '{event.by}'; "
                    f"cast is {sorted(known)}",
                    rule="unknown-actor",
                    loc=("script", index, "by"),
                )
        return self

    @model_validator(mode="after")
    def check_ordering_is_consistent(self) -> Self:
        """Horizontal ordering must not contain a cycle.

        The layout engine is a *linear* constraint solver, so ordering has to be
        decided before it runs -- see docs/reference/language.md. A cycle such as
        'a left_of b, b left_of a' has no solution, and detecting it here produces a
        comprehensible message instead of an opaque solver failure.
        """
        edges: dict[str, set[str]] = {actor: set() for actor in self.cast}
        # Which staging entry introduced each edge, so a cycle can be reported against a
        # line the author actually wrote rather than against the document as a whole.
        # First writer wins: if two entries state the same ordering, the earlier one is
        # the one to point at.
        wrote: dict[tuple[str, str], int] = {}
        for index, relation in enumerate(self.staging):
            if relation.predicate is Predicate.LEFT_OF:
                edge = (relation.subject, relation.object)
            elif relation.predicate is Predicate.RIGHT_OF:
                edge = (relation.object, relation.subject)
            else:
                continue
            edges[edge[0]].add(edge[1])
            wrote.setdefault(edge, index)

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
                        culprit = wrote.get((node, neighbour))
                        raise RuleViolationError(
                            f"horizontal ordering is cyclic around '{neighbour}'; "
                            "left_of/right_of relations must form a consistent order",
                            rule="ordering-cycle",
                            loc=("staging",) if culprit is None else ("staging", culprit),
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
