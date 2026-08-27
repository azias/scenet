"""The compiler: source through IR to Panel Core.

Each stage is separable and independently testable, which is the point of having
tiers at all. The frontend never computes a coordinate, the solver never touches
artwork, and the emitter never makes a layout decision.
"""

from dataclasses import dataclass
from pathlib import Path

from scenet.assets.contract import PuppetLibrary, default_library
from scenet.assets.face import ResolvedDisc, ResolvedStroke, build_face
from scenet.assets.kinematics import ResolvedPuppet, resolve
from scenet.core import (
    Blob,
    Box,
    Capsule,
    CoreActor,
    CoreAtmosphere,
    CoreBackdrop,
    CoreBalloon,
    CoreCaption,
    CoreMass,
    CoreStreak,
    CoreVeil,
    Disc,
    FaceDisc,
    FaceMark,
    FaceStroke,
    PanelCore,
    Tail,
    Transform,
    point_pair,
    round_pairs,
    vector_pair,
)
from scenet.frontends.script_front import load_script
from scenet.frontends.yaml_front import load_panel, load_scene, parse_panel, parse_scene
from scenet.geom import BBox, Vector, rounded
from scenet.ir import PanelIR
from scenet.solve.backdrop import ResolvedBackdrop, solve_backdrop
from scenet.solve.balloons import place_script
from scenet.solve.camera import CameraSolution
from scenet.solve.staging import Placement, solve_staging
from scenet.solve.text import FontMetrics


@dataclass(frozen=True, slots=True)
class CompileResult:
    """The compiled panel, with the intermediate results kept for inspection.

    Diagnostics -- notably whether the camera had to retreat to fit the cast -- are
    part of the result rather than log output, so tooling can surface them.
    """

    core: PanelCore
    camera: CameraSolution
    placements: tuple[Placement, ...]
    posed: dict[str, ResolvedPuppet]

    @property
    def notes(self) -> tuple[str, ...]:
        """Human-readable diagnostics about how this panel was compiled.

        Returns:
            Zero or more sentences describing decisions the compiler had to make that
            were not literally what the source asked for -- a camera that retreated to
            fit the cast, a balloon tail that had to bend around a face.

        These are returned rather than logged so that tooling can put them in front of
        the person who wrote the panel. A camera that silently retreats leaves you with
        a panel that is quietly not the shot you asked for, which you would eventually
        notice and have no way to explain.

        Example:
            >>> from scenet import compile_source
            >>> crowded = compile_source(
            ...     "{panel: {size: [600.0, 400.0]}, camera: {shot: close_up},"
            ...     " cast: {a: {reference: alice}, b: {reference: bob}},"
            ...     " staging: [a left_of b]}"
            ... )
            >>> any("camera retreated" in note for note in crowded.notes)
            True
        """
        notes: list[str] = []
        if self.camera.was_pulled_back:
            notes.append(
                f"camera retreated to {self.camera.pullback:.0%} of the requested "
                f"'{self.camera.shot.value}' framing so the cast would fit across the panel"
            )
        for balloon in self.core.balloons:
            if balloon.tail.is_curved:
                notes.append(f"balloon {balloon.id} needed a curved tail to clear a face")
        return tuple(notes)


def _gaze_aims(
    panel: PanelIR, posed: dict[str, ResolvedPuppet], origins: dict[str, str]
) -> dict[str, Vector]:
    """Unit vectors from each looking character's eyes to what they are looking at.

    `looking_at` has always turned a figure toward its target and made the space in
    front of them expensive for a balloon. What it never did was show up on the face,
    because the only gaze vector available was the head's forward direction -- which,
    with no pose rotating the head, is the facing direction and nothing more. This is
    the real thing, and it is what the pupils follow.

    Args:
        panel: The validated panel, for its `looking_at` relations.
        posed: Every actor, already placed. Both ends of a gaze must be resolved
            before the vector between them exists, which is why this runs here.
        origins: Actor id to the anchor its puppet declares as the gaze origin.

    Returns:
        Actor id to unit aim vector, for looking actors only.
    """
    aims: dict[str, Vector] = {}
    for actor, target in panel.gaze_targets().items():
        looker, looked_at = posed[actor], posed[target]
        eyes = looker.anchors.get(origins[actor], looker.face.centre)
        towards = looked_at.face.centre
        aim = Vector(towards.x - eyes.x, towards.y - eyes.y)
        if aim.length:
            aims[actor] = aim.normalised()
    return aims


def _core_mark(mark: ResolvedStroke | ResolvedDisc) -> FaceMark:
    """Reduce one resolved face mark to its serialisable Core twin."""
    if isinstance(mark, ResolvedDisc):
        return FaceDisc(
            id=mark.id,
            centre=point_pair(mark.centre),
            radius=rounded(mark.radius),
            filled=mark.filled,
            width=rounded(mark.width),
        )
    return FaceStroke(
        id=mark.id,
        points=round_pairs(mark.points),
        width=rounded(mark.width),
        closed=mark.closed,
    )


def _core_backdrop(backdrop: ResolvedBackdrop | None) -> CoreBackdrop | None:
    """Reduce a resolved backdrop to its serialisable Core twin.

    Rounding happens here, as it does for every other tier boundary, so that a Core
    document is byte-identical across platforms whose float formatting differs in the
    last digit.
    """
    if backdrop is None:
        return None

    air = backdrop.atmosphere
    return CoreBackdrop(
        horizon=rounded(backdrop.horizon),
        seed=backdrop.seed,
        masses=tuple(
            CoreMass(
                id=mass.id,
                kind=mass.kind,
                plane=mass.plane,
                depth=mass.depth,
                tone=mass.tone,
                polygon=round_pairs(mass.polygon),
            )
            for mass in backdrop.masses
        ),
        atmosphere=None
        if air is None
        else CoreAtmosphere(
            time=air.time,
            weather=air.weather,
            tone=air.tone,
            veil=None
            if air.veil is None
            else CoreVeil(
                tone=air.veil.tone,
                opacity=air.veil.opacity,
                frequency=air.veil.frequency,
                octaves=air.veil.octaves,
                seed=air.veil.seed,
            ),
            streaks=tuple(
                CoreStreak(start=point_pair(start), end=point_pair(end))
                for start, end in air.streaks
            ),
            flecks=tuple(Disc.of(fleck) for fleck in air.flecks),
            streak_width=rounded(air.streak_width),
            fall_tone=air.fall_tone,
        ),
    )


def compile_ir(
    panel: PanelIR,
    *,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> CompileResult:
    """Compile validated IR into Panel Core."""
    library = library or default_library()
    placements, camera = solve_staging(panel, library)

    posed = {
        placement.actor_id: resolve(
            library.get(placement.reference),
            pose=placement.pose,
            expression=placement.expression,
            facing_right=placement.facing_right,
            scale=placement.scale,
            origin=placement.origin,
        )
        for placement in placements
    }
    # Aiming has to happen here rather than in `resolve`, because where a character is
    # looking is a fact about two actors and is not known until both are placed. It is
    # still nothing to do with the solver: no constraint reads it, and it changes no
    # position -- it only turns the pupils.
    specs = {placement.actor_id: library.get(placement.reference) for placement in placements}
    aims = _gaze_aims(panel, posed, {actor: spec.gaze.origin for actor, spec in specs.items()})
    faces = {
        actor: build_face(
            posed[actor], spec.expression_states(posed[actor].expression), aims.get(actor)
        )
        if spec.expressions
        else ()
        for actor, spec in specs.items()
    }

    # The backdrop is resolved against the whole panel, not the margined frame: artwork
    # bleeds to the edge and only lettering is kept inside a margin. It runs after
    # staging, which is what knows how deep the cast goes, and before placement, which
    # reads the masses as a soft cost.
    backdrop = solve_backdrop(
        panel.setting,
        BBox(0.0, 0.0, panel.panel.width, panel.panel.height),
        frontmost_actor=max((placement.depth for placement in placements), default=0),
    )

    frame = BBox(
        panel.panel.margin,
        panel.panel.margin,
        panel.panel.width - 2 * panel.panel.margin,
        panel.panel.height - 2 * panel.panel.margin,
    )
    layout = place_script(panel.script, posed, frame, metrics=metrics, backdrop=backdrop)

    core = PanelCore(
        width=rounded(panel.panel.width),
        height=rounded(panel.panel.height),
        actors=tuple(
            CoreActor(
                id=placement.actor_id,
                reference=placement.reference,
                pose=placement.pose,
                expression=placement.expression,
                transform=Transform(
                    x=rounded(placement.x),
                    y=rounded(placement.y),
                    scale=rounded(placement.scale),
                    mirrored=not placement.facing_right,
                ),
                anchors={
                    name: point_pair(point)
                    for name, point in sorted(posed[placement.actor_id].anchors.items())
                },
                face_exclusion=Disc.of(posed[placement.actor_id].face),
                gaze=vector_pair(posed[placement.actor_id].gaze),
                gaze_aim=(
                    vector_pair(aims[placement.actor_id]) if placement.actor_id in aims else None
                ),
                face_marks=tuple(_core_mark(mark) for mark in faces[placement.actor_id]),
                hull=round_pairs(posed[placement.actor_id].hull),
                capsules=tuple(
                    Capsule(
                        start=point_pair(capsule.start),
                        end=point_pair(capsule.end),
                        width=rounded(capsule.width),
                    )
                    for capsule in posed[placement.actor_id].capsules
                ),
                blobs=tuple(
                    Blob(centre=point_pair(blob.centre), radius=rounded(blob.radius))
                    for blob in posed[placement.actor_id].blobs
                ),
                depth=placement.depth,
            )
            for placement in placements
        ),
        balloons=tuple(
            CoreBalloon(
                id=balloon.id,
                speaker=balloon.speaker,
                order=balloon.order,
                kind=balloon.kind,
                box=Box.of(balloon.box),
                lines=balloon.block.lines,
                font_size=rounded(balloon.block.font_size),
                line_height=rounded(balloon.block.line_height),
                tail=Tail(
                    start=point_pair(balloon.tail.start),
                    end=point_pair(balloon.tail.end),
                    control=(point_pair(balloon.tail.control) if balloon.tail.control else None),
                ),
            )
            for balloon in layout.balloons
        ),
        captions=tuple(
            CoreCaption(
                id=caption.id,
                order=caption.order,
                kind=caption.kind,
                box=Box.of(caption.box),
                lines=caption.block.lines,
                font_size=rounded(caption.block.font_size),
                line_height=rounded(caption.block.line_height),
                italic=caption.kind.is_italic,
                speaker=caption.speaker,
            )
            for caption in layout.captions
        ),
        backdrop=_core_backdrop(backdrop),
    )
    return CompileResult(core=core, camera=camera, placements=placements, posed=posed)


def compile_source(
    text: str,
    *,
    source: Path | None = None,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> CompileResult:
    """Compile one panel from a source string.

    The usual entry point, and the one to reach for first.

    Args:
        text: A single-panel document in the YAML surface syntax.
        source: Path the text came from, used only to prefix error messages. Pass it
            when you have one; the diagnostics are much more useful with it.
        library: Characters to draw from. Defaults to the two shipped puppets.
        metrics: Font to measure lettering against. Defaults to the font that ships as
            a dependency of this package.

    Returns:
        The compiled panel, with the intermediate results kept for inspection.

    Raises:
        PanelSyntaxError: The document is malformed or invalid.
        UnknownPuppetError: A cast member references a character the library lacks.
        LayoutError: The required constraints cannot all be satisfied.
        BalloonPlacementError: A balloon has no legal position.

    Example:
        >>> from scenet import compile_source, render
        >>> result = compile_source(
        ...     "{cast: {alice: {reference: alice}}, script: [{say: {by: alice, text: Hello.}}]}"
        ... )
        >>> len(result.core.balloons)
        1
        >>> result.core.balloons[0].lines
        ('Hello.',)
        >>> svg = render(result.core)

    See Also:
        :func:`compile_file <scenet.pipeline.compile_file>`, to read from disk.
        :func:`compile_scene <scenet.pipeline.compile_scene>`, for multi-panel documents.
        :func:`compile_document <scenet.pipeline.compile_document>`, to dispatch on
        extension and accept any supported syntax.
    """
    return compile_ir(parse_panel(text, source=source), library=library, metrics=metrics)


def compile_file(
    path: Path,
    *,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> CompileResult:
    """Compile one panel from a file.

    Args:
        path: A `*.panel.yaml` document.
        library: Characters to draw from. Defaults to the two shipped puppets.
        metrics: Font to measure lettering against.

    Returns:
        The compiled panel.

    Raises:
        OSError: The file cannot be read.
        PanelSyntaxError: The document is malformed or invalid. The path is included
            in the message.
    """
    return compile_ir(load_panel(path), library=library, metrics=metrics)


def compile_scene(
    text: str,
    *,
    source: Path | None = None,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> dict[str, CompileResult]:
    """Compile every panel in a multi-panel document.

    Each panel is compiled independently. A panel's composition must not depend on
    what sits beside it, or the same source would compile differently in isolation --
    which would make panels non-reusable and golden tests meaningless.
    """
    library = library or default_library()
    return {
        name: compile_ir(panel, library=library, metrics=metrics)
        for name, panel in parse_scene(text, source=source).items()
    }


def compile_scene_file(
    path: Path,
    *,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> dict[str, CompileResult]:
    """Compile every panel in a multi-panel file.

    Args:
        path: A `*.scene.yaml` document. A single-panel document also works and comes
            back as one entry named `panel`.
        library: Characters to draw from. Defaults to the two shipped puppets.
        metrics: Font to measure lettering against.

    Returns:
        Panel name to compiled panel, in declaration order -- which is reading order.

    Raises:
        OSError: The file cannot be read.
        PanelSyntaxError: A panel is malformed or invalid.
        CompositionError: An `over:` chain refers to a panel that does not exist, or
            forms a cycle.
    """
    library = library or default_library()
    return {
        name: compile_ir(panel, library=library, metrics=metrics)
        for name, panel in load_scene(path).items()
    }


# Which frontend handles which extension. Adding a syntax means adding a line here and
# nothing else, because every frontend produces the same IR.
FRONTENDS = {
    ".script": load_script,
    ".yaml": load_scene,
    ".yml": load_scene,
}


def compile_document(
    path: Path,
    *,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> dict[str, CompileResult]:
    """Compile any supported document, choosing the frontend by extension."""
    loader = FRONTENDS.get(path.suffix.lower())
    if loader is None:
        supported = ", ".join(sorted(FRONTENDS))
        raise ValueError(
            f"{path}: unsupported extension '{path.suffix}'; expected one of {supported}"
        )
    library = library or default_library()
    return {
        name: compile_ir(panel, library=library, metrics=metrics)
        for name, panel in loader(path).items()
    }
