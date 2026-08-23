"""The compiler: source through IR to Panel Core.

Each stage is separable and independently testable, which is the point of having
tiers at all. The frontend never computes a coordinate, the solver never touches
artwork, and the emitter never makes a layout decision.
"""

from dataclasses import dataclass
from pathlib import Path

from scenet.assets.contract import PuppetLibrary, default_library
from scenet.assets.kinematics import ResolvedPuppet, resolve
from scenet.core import (
    Blob,
    Box,
    Capsule,
    CoreActor,
    CoreBalloon,
    Disc,
    PanelCore,
    Tail,
    Transform,
    point_pair,
    round_pairs,
    vector_pair,
)
from scenet.frontends.yaml_front import load_panel, parse_panel
from scenet.geom import BBox, rounded
from scenet.ir import PanelIR
from scenet.solve.balloons import place_balloons
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
        notes: list[str] = []
        if self.camera.was_pulled_back:
            notes.append(
                f"camera retreated to {self.camera.pullback:.0%} of the requested "
                f"'{self.camera.reference}' framing so the cast would fit across the panel"
            )
        for balloon in self.core.balloons:
            if balloon.tail.is_curved:
                notes.append(f"balloon {balloon.id} needed a curved tail to clear a face")
        return tuple(notes)


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
            facing_right=placement.facing_right,
            scale=placement.scale,
            origin=placement.origin,
        )
        for placement in placements
    }

    frame = BBox(
        panel.panel.margin,
        panel.panel.margin,
        panel.panel.width - 2 * panel.panel.margin,
        panel.panel.height - 2 * panel.panel.margin,
    )
    balloons = place_balloons(panel.script, posed, frame, metrics=metrics)

    core = PanelCore(
        width=rounded(panel.panel.width),
        height=rounded(panel.panel.height),
        actors=tuple(
            CoreActor(
                id=placement.actor_id,
                reference=placement.reference,
                pose=placement.pose,
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
            for balloon in balloons
        ),
    )
    return CompileResult(core=core, camera=camera, placements=placements, posed=posed)


def compile_source(
    text: str,
    *,
    source: Path | None = None,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> CompileResult:
    return compile_ir(parse_panel(text, source=source), library=library, metrics=metrics)


def compile_file(
    path: Path,
    *,
    library: PuppetLibrary | None = None,
    metrics: FontMetrics | None = None,
) -> CompileResult:
    return compile_ir(load_panel(path), library=library, metrics=metrics)
