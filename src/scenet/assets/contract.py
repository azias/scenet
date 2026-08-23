"""What a character puppet must declare.

The solver never sees artwork -- only this contract. That is what keeps rendering
swappable: the same panel lays out identically whether it is drawn as wireframe
boxes, as vector puppets, or eventually as real artwork.

A character is a skeleton plus parametric limbs rather than a picture, so a pose is
a set of joint angles and not a drawing. That avoids the combinatorial explosion of
one image per pose per expression per facing direction.
"""

from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from scenet.errors import AssetError, UnknownPuppetError


class Landmark(StrEnum):
    """Vertical body landmarks, measured downward from the top of the head.

    These are the crop lines a shot type names -- see docs/spec/shot_types.md.
    """

    HEAD_TOP = "head_top"
    EYES = "eyes"
    CHIN = "chin"
    SHOULDERS = "shoulders"
    CHEST = "chest"
    WAIST = "waist"
    MID_THIGH = "mid_thigh"
    KNEES = "knees"
    FEET = "feet"


class Strict(BaseModel):
    """Base for every puppet model: frozen, and rejecting unknown keys.

    A misspelled key in a puppet file that was silently ignored would produce a
    character that is subtly wrong -- an arm the wrong length, an anchor in the wrong
    place -- with nothing to point at.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class JointSpec(Strict):
    """One joint in the skeleton.

    `offset` is the rest-pose displacement from the parent joint, in native units.
    A joint's pose angle rotates the bone arriving at it *and* everything below it,
    which is the formulation that makes posing read naturally: bending `elbow_l`
    swings the upper arm and takes the forearm and hand with it.
    """

    parent: str | None = None
    offset: tuple[float, float] = (0.0, 0.0)


class BonePart(Strict):
    """A limb segment drawn as a capsule between two joints."""

    from_joint: str = Field(alias="from")
    to_joint: str = Field(alias="to")
    width: float = Field(gt=0)

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class BlobPart(Strict):
    """A rounded mass -- the head, or a torso -- centred on a joint."""

    at: str
    radius: float = Field(gt=0)
    offset: tuple[float, float] = (0.0, 0.0)


class AnchorSpec(Strict):
    """A named point that rides along with a joint.

    Anchors are how the solver addresses anatomy without knowing anatomy: the balloon
    tail terminates at `mouth`, and it neither knows nor cares how the head is drawn.
    """

    joint: str
    offset: tuple[float, float] = (0.0, 0.0)


class FaceSpec(Strict):
    """The region a balloon may never cover.

    A circle rather than a polygon: faces are roughly round, the test is cheap, and
    the cost of being slightly generous here is a balloon placed a little further
    away, which is never wrong.
    """

    joint: str = "head"
    radius: float = Field(gt=0)
    offset: tuple[float, float] = (0.0, 0.0)


class GazeSpec(Strict):
    """Where a character's line of sight starts.

    Attributes:
        origin: Name of a declared anchor, conventionally `eyes`. Validated to exist.

    The *direction* is not stored: it is derived at solve time from whom the character
    is looking at, so a `looking_at` relation is enough and nobody has to compute an
    angle by hand.
    """

    origin: str = "eyes"


class PuppetSpec(Strict):
    """The complete geometric contract for one character."""

    name: str
    units_per_head: float = Field(gt=0)
    landmarks: dict[Landmark, float]
    joints: dict[str, JointSpec]
    root: str = "root"
    # Which landmark the root joint physically sits at. The skeleton is built outward
    # from the root, while landmarks are measured downward from the top of the head;
    # this is what bridges the two frames. Declared rather than assumed, because a
    # puppet is free to root itself somewhere other than the waist.
    root_landmark: Landmark = Landmark.WAIST
    parts: tuple[BonePart | BlobPart, ...] = ()
    anchors: dict[str, AnchorSpec] = Field(default_factory=dict)
    face: FaceSpec
    gaze: GazeSpec = GazeSpec()
    poses: dict[str, dict[str, float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_landmarks_complete_and_ordered(self) -> Self:
        """Require every landmark, in head-to-foot order.

        Returns:
            The validated puppet.

        Raises:
            ValueError: A landmark is missing, `head_top` is not zero, or the values do
                not increase downward.

        All nine landmarks are required rather than optional-with-defaults because any
        shot type may crop at any of them, so a puppet missing one is a puppet that
        cannot be framed at some perfectly ordinary shot.
        """
        missing = [landmark for landmark in Landmark if landmark not in self.landmarks]
        if missing:
            raise ValueError(
                f"puppet '{self.name}' is missing landmarks {[m.value for m in missing]}; "
                "every landmark is required because any shot type may crop there"
            )
        if self.landmarks[Landmark.HEAD_TOP] != 0:
            raise ValueError(f"puppet '{self.name}': head_top must be 0, it is the origin")

        ordered = [self.landmarks[landmark] for landmark in Landmark]
        for earlier, later in pairwise(ordered):
            if later <= earlier:
                raise ValueError(
                    f"puppet '{self.name}': landmarks must increase downward from head_top "
                    f"to feet, but {later} follows {earlier}"
                )
        return self

    @model_validator(mode="after")
    def check_skeleton_is_a_tree(self) -> Self:
        """Require the skeleton to be a tree rooted at `root`.

        Returns:
            The validated puppet.

        Raises:
            ValueError: The root is undefined or has a parent, a joint names a parent
                that does not exist, or a joint sits in a cycle.

        Forward kinematics accumulates each joint's transform from its parent's. A
        cycle would make that non-terminating and an orphan would leave a limb with no
        defined position, so both are rejected here rather than discovered at pose time.
        """
        if self.root not in self.joints:
            raise ValueError(f"puppet '{self.name}': root joint '{self.root}' is not defined")
        if self.joints[self.root].parent is not None:
            raise ValueError(f"puppet '{self.name}': root joint '{self.root}' must have no parent")

        for name, joint in self.joints.items():
            if joint.parent is not None and joint.parent not in self.joints:
                raise ValueError(
                    f"puppet '{self.name}': joint '{name}' names unknown parent '{joint.parent}'"
                )

        # Every joint must reach the root, which rules out both cycles and orphans.
        for name in self.joints:
            seen: set[str] = set()
            cursor: str | None = name
            while cursor is not None:
                if cursor in seen:
                    raise ValueError(f"puppet '{self.name}': joint '{name}' sits in a cycle")
                seen.add(cursor)
                cursor = self.joints[cursor].parent
        return self

    @model_validator(mode="after")
    def check_joint_references(self) -> Self:
        """Require every joint name mentioned anywhere to exist.

        Covers parts, anchors, the face, the gaze origin, and every angle in every
        declared pose.

        Returns:
            The validated puppet.

        Raises:
            ValueError: Something references a joint or anchor that is not declared.
        """

        def require(joint: str, context: str) -> None:
            if joint not in self.joints:
                raise ValueError(
                    f"puppet '{self.name}': {context} references unknown joint '{joint}'"
                )

        for part in self.parts:
            if isinstance(part, BonePart):
                require(part.from_joint, "part")
                require(part.to_joint, "part")
            else:
                require(part.at, "part")
        for anchor_name, anchor in self.anchors.items():
            require(anchor.joint, f"anchor '{anchor_name}'")
        require(self.face.joint, "face")

        if self.gaze.origin not in self.anchors:
            raise ValueError(
                f"puppet '{self.name}': gaze origin '{self.gaze.origin}' is not a declared anchor"
            )
        for pose_name, angles in self.poses.items():
            for joint in angles:
                require(joint, f"pose '{pose_name}'")
        return self

    @property
    def total_height(self) -> float:
        """Head top to feet, in the puppet's own native units."""
        return self.landmarks[Landmark.FEET]

    @property
    def heads_tall(self) -> float:
        """Height in head-heights -- the classic figure-drawing proportion.

        The unit the camera works in. Two puppets of different `heads_tall` framed at
        the same shot produce figures of visibly different build, which is the whole
        reason the shipped library has a 7.5-head character and a taller one.
        """
        return self.total_height / self.units_per_head

    def pose_angles(self, pose: str) -> dict[str, float]:
        """Look up the joint angles for a named pose.

        Args:
            pose: Name of a pose this puppet declares.

        Returns:
            Joint name to angle in degrees. Joints absent from the mapping keep their
            rest angle.

        Raises:
            KeyError: This puppet has no pose by that name. The message lists the ones
                it does have.
        """
        if pose not in self.poses:
            raise KeyError(
                f"puppet '{self.name}' has no pose '{pose}'; available: {sorted(self.poses)}"
            )
        return self.poses[pose]


class PuppetLibrary:
    """Puppets loaded from a directory of `*.puppet.yaml` files."""

    def __init__(self, puppets: dict[str, PuppetSpec]) -> None:
        """Wrap an already-loaded mapping of puppets.

        Args:
            puppets: Puppet name to specification. Usually built by
                [`from_directory`][scenet.assets.contract.PuppetLibrary.from_directory]
                rather than passed in directly -- but constructing one by hand is how
                you supply your own characters without touching the filesystem.
        """
        self._puppets = puppets

    @classmethod
    def from_directory(cls, directory: Path) -> Self:
        """Load every `*.puppet.yaml` in a directory.

        Args:
            directory: Directory to scan. Not searched recursively.

        Returns:
            A library containing every puppet found.

        Raises:
            ValueError: Two files declare the same puppet name.
            AssetError: A file is not a YAML mapping.

        Files are visited in sorted order so that a duplicate-name collision reports the
        same offender on every platform, whatever order the filesystem hands them back.
        """
        puppets: dict[str, PuppetSpec] = {}
        # Sorted so that a duplicate-name collision reports the same offender on
        # every platform, whatever order the filesystem hands files back in.
        for path in sorted(directory.glob("*.puppet.yaml")):
            spec = load_puppet(path)
            if spec.name in puppets:
                raise ValueError(f"duplicate puppet name '{spec.name}' in {path}")
            puppets[spec.name] = spec
        return cls(puppets)

    def get(self, name: str) -> PuppetSpec:
        """Look up one puppet by name.

        Args:
            name: The name a cast member's `reference` field points at.

        Returns:
            That puppet's specification.

        Raises:
            UnknownPuppetError: No puppet by that name. The message lists what is
                available, because the usual cause is a typo.
        """
        if name not in self._puppets:
            raise UnknownPuppetError(
                f"unknown character '{name}'; the library has {sorted(self._puppets)}"
            )
        return self._puppets[name]

    def names(self) -> tuple[str, ...]:
        """Every puppet name in this library, sorted.

        Example:
            >>> from scenet import default_library
            >>> default_library().names()
            ('alice', 'bob')
        """
        return tuple(sorted(self._puppets))


def load_puppet(path: Path) -> PuppetSpec:
    """Read one `*.puppet.yaml` file into a validated specification.

    Args:
        path: The puppet file to read.

    Returns:
        The validated puppet, ready to be posed.

    Raises:
        AssetError: The file is not a YAML mapping.
        pydantic.ValidationError: The mapping is not a well-formed puppet -- an
            out-of-order landmark, a skeleton that is not a tree, a joint referring
            to a parent that does not exist.

    Example:
        >>> from scenet import default_library, load_puppet
        >>> from scenet.assets.contract import DEFAULT_LIBRARY_PATH
        >>> alice = load_puppet(DEFAULT_LIBRARY_PATH / "alice.puppet.yaml")
        >>> alice.name
        'alice'
        >>> round(alice.heads_tall, 1)
        7.5

    See Also:
        [`PuppetLibrary.from_directory`][scenet.assets.contract.PuppetLibrary.from_directory],
        to read a whole directory at once.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssetError(f"{path}: expected a mapping at the top level")
    return PuppetSpec.model_validate(data)


DEFAULT_LIBRARY_PATH = Path(__file__).parent / "library"


def default_library() -> PuppetLibrary:
    """Load the puppets shipped with Scenet.

    Two characters of deliberately different build, so that a bug in camera scaling
    cannot hide behind two figures that happen to be the same height.

    Returns:
        A library containing `alice` and `bob`.

    Example:
        >>> from scenet import default_library
        >>> library = default_library()
        >>> round(library.get("alice").heads_tall, 1)
        7.5
    """
    return PuppetLibrary.from_directory(DEFAULT_LIBRARY_PATH)
