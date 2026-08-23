"""Camera framing: shot type into scale and vertical placement.

The central rule, and the one most easily got wrong: **a shot type names where the
frame cuts the body**, not what fraction of the panel a figure fills. Encoding the
fraction instead bakes in one body and one pose, so a child and an adult would come
out the same height. See docs/reference/shot_types.md, which is normative.

The second rule: **one camera, one scale.** A camera has a single focal length, so
every actor at the same distance is scaled identically and a taller character is
taller in frame. Scaling each actor to fit its own crop would silently erase height
differences, which is precisely what a comic uses to characterise people.
"""

from dataclasses import dataclass

from scenet.assets.contract import Landmark, PuppetSpec
from scenet.ir import CameraAngle, ShotType


@dataclass(frozen=True, slots=True)
class ShotSpec:
    """A crop landmark and the empty space left above the head."""

    crop: Landmark
    headroom: float


SHOT_TABLE: dict[ShotType, ShotSpec] = {
    # long_shot and full_shot both crop at the feet, so headroom is the only thing that
    # separates them -- and it separated them the wrong way round. A long shot puts the
    # figure *small in its environment*, so it needs MORE air above the head, not less.
    # At 0.05 against full_shot's 0.08 it drew the figure larger than a full shot,
    # inverting the ladder at its widest end with nothing to notice.
    #
    # The honest limitation: with no environment to show, these two can differ only by
    # headroom, so the gap stays modest however the numbers are set.
    ShotType.LONG_SHOT: ShotSpec(Landmark.FEET, 0.14),
    ShotType.WIDE: ShotSpec(Landmark.FEET, 0.14),
    ShotType.FULL_SHOT: ShotSpec(Landmark.FEET, 0.05),
    ShotType.MEDIUM_FULL: ShotSpec(Landmark.MID_THIGH, 0.08),
    ShotType.COWBOY: ShotSpec(Landmark.MID_THIGH, 0.08),
    ShotType.MEDIUM_SHOT: ShotSpec(Landmark.WAIST, 0.10),
    ShotType.MEDIUM_CLOSE_UP: ShotSpec(Landmark.CHEST, 0.10),
    ShotType.CLOSE_UP: ShotSpec(Landmark.SHOULDERS, 0.08),
    ShotType.BIG_CLOSE_UP: ShotSpec(Landmark.CHIN, 0.05),
    ShotType.EXTREME_CLOSE_UP: ShotSpec(Landmark.EYES, 0.00),
}

# Camera angle adjusts headroom rather than displacing the figure, so it composes
# with the crop maths instead of fighting it. A high angle looks down on a subject and
# leaves more air above, diminishing them; a low angle crowds the top of the frame and
# makes them loom. This is a compositional approximation, not true perspective --
# there is no foreshortening yet, and the spec says so.
ANGLE_HEADROOM_FACTOR: dict[CameraAngle, float] = {
    CameraAngle.LOW: 0.5,
    CameraAngle.EYE_LEVEL: 1.0,
    CameraAngle.HIGH: 1.6,
}

# A minimum, so that `extreme_close_up` (headroom 0.0) still shifts under a high angle
# rather than being stuck flush against the top edge.
MINIMUM_ANGLE_HEADROOM = 0.02


@dataclass(frozen=True, slots=True)
class CameraSolution:
    """The camera's verdict for a panel: one scale, shared by every actor."""

    scale: float
    headroom: float
    footroom: float
    panel_height: float
    reference: str
    # How far the camera had to retreat to fit the whole cast across the frame.
    # 1.0 means the requested shot was used as-is; smaller means it was loosened.
    pullback: float = 1.0

    @property
    def was_pulled_back(self) -> bool:
        """Whether the camera had to retreat from the requested framing.

        Surfaced to the user through
        :attr:`CompileResult.notes <scenet.pipeline.CompileResult.notes>`. Retreating
        silently would leave a panel that quietly is not the shot that was asked for.
        """
        return self.pullback < 1.0

    def pulled_back_to(self, scale: float) -> "CameraSolution":
        """Retreat the camera until the cast fits across the frame.

        A shot type is a statement about *vertical* framing -- where the frame cuts
        the body. When several actors cannot fit side by side at that scale, a real
        camera moves back: everyone gets smaller and more of the body comes into
        view. So the requested shot behaves as an upper bound on tightness rather
        than an exact contract, and the amount of retreat is recorded here so the
        result stays inspectable rather than mysterious.
        """
        if scale >= self.scale:
            return self
        return CameraSolution(
            scale=scale,
            headroom=self.headroom,
            footroom=self.footroom,
            panel_height=self.panel_height,
            reference=self.reference,
            pullback=scale / self.scale,
        )

    @property
    def head_top_y(self) -> float:
        """Where the reference actor's head-top lands."""
        return self.panel_height * self.headroom

    def root_y_framed(self, puppet: PuppetSpec) -> float:
        """Place this puppet by its own head, as if framed alone.

        Used for actors that share no ground line with anyone: each is composed
        independently within the frame.
        """
        head_to_root = puppet.landmarks[puppet.root_landmark] - puppet.landmarks[Landmark.HEAD_TOP]
        return self.head_top_y + head_to_root * self.scale

    def root_y_on_ground(self, puppet: PuppetSpec, ground_y: float) -> float:
        """Place this puppet so its feet meet a given ground line.

        This is what makes two characters of different heights stand together
        convincingly: feet align, heads do not.
        """
        return ground_y - self.feet_below_root(puppet)

    def feet_below_root(self, puppet: PuppetSpec) -> float:
        """How far below the root joint this puppet's feet sit, at this camera scale.

        Args:
            puppet: The character being placed.

        Returns:
            Distance in panel units.
        """
        return (
            puppet.landmarks[Landmark.FEET] - puppet.landmarks[puppet.root_landmark]
        ) * self.scale

    def ground_y_of(self, puppet: PuppetSpec, root_y: float) -> float:
        """The ground line a puppet stands on, given where its root joint is.

        The inverse of
        :meth:`root_y_on_ground <scenet.solve.camera.CameraSolution.root_y_on_ground>`, and
        how `ground_shared_with` gets its target: take one actor's ground line, then
        place the other so their feet meet it.

        Args:
            puppet: The character.
            root_y: Where its root joint sits vertically.

        Returns:
            The y coordinate of its feet.
        """
        return root_y + self.feet_below_root(puppet)


def headroom_for(shot: ShotType, angle: CameraAngle) -> float:
    """Empty space to leave above the head, as a fraction of panel height.

    A shot type has two halves and they use different units. The **crop landmark** is
    anatomical -- the waist, the chest, the shoulders -- which is what stops a shot type
    baking in one body and one pose. The **headroom** is a plain fraction of panel
    height, because it is about composition within the frame rather than about anatomy.
    See `docs/reference/shot_types.md`, which is normative.

    Angle changes headroom rather than perspective. This compiler is orthographic, so a
    tilted camera cannot foreshorten anything -- but the amount of air above the head is
    the compositional cue readers actually take from an angle, and it is one that
    survives being drawn flat.

    A **low** camera looks up and the subject looms, so headroom tightens; a **high**
    camera looks down and it opens out.

    Args:
        shot: The requested framing.
        angle: The camera height.

    Returns:
        Headroom as a fraction of panel height, never below `MINIMUM_ANGLE_HEADROOM`
        for a tilted
        camera -- so that `extreme_close_up`, whose base headroom is zero, still shifts
        under an angle instead of staying flush against the top edge.

    Example:
        >>> from scenet import CameraAngle, ShotType
        >>> from scenet.solve.camera import headroom_for
        >>> [
        ...     headroom_for(ShotType.MEDIUM_SHOT, angle)
        ...     for angle in (CameraAngle.LOW, CameraAngle.EYE_LEVEL, CameraAngle.HIGH)
        ... ]
        [0.05, 0.1, 0.16000000000000003]
    """
    base = SHOT_TABLE[shot].headroom
    scaled = base * ANGLE_HEADROOM_FACTOR[angle]
    if angle is CameraAngle.EYE_LEVEL:
        return scaled
    return max(scaled, MINIMUM_ANGLE_HEADROOM)


def visible_height(puppet: PuppetSpec, shot: ShotType) -> float:
    """Native height of the portion of the body the frame will show."""
    spec = SHOT_TABLE[shot]
    return puppet.landmarks[spec.crop] - puppet.landmarks[Landmark.HEAD_TOP]


def solve_camera(
    reference: PuppetSpec,
    *,
    shot: ShotType,
    angle: CameraAngle,
    panel_height: float,
    footroom: float = 0.0,
) -> CameraSolution:
    """Resolve the camera against a reference actor.

    Everything else in the panel inherits this scale. The reference is the actor the
    shot is composed on -- by convention the first in the cast, which is the one the
    author wrote first and therefore the one the panel is about.
    """
    headroom = headroom_for(shot, angle)
    if headroom + footroom >= 1.0:
        raise ValueError(
            f"headroom {headroom:.2f} plus footroom {footroom:.2f} leaves no room for the figure"
        )

    available = panel_height * (1.0 - headroom - footroom)
    native = visible_height(reference, shot)
    if native <= 0:
        raise ValueError(
            f"puppet '{reference.name}' has no visible height for shot '{shot}'; "
            "its landmarks may be misordered"
        )
    return CameraSolution(
        scale=available / native,
        headroom=headroom,
        footroom=footroom,
        panel_height=panel_height,
        reference=reference.name,
    )
