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


class UnknownPuppetError(KeyError):
    """A panel referenced a character the library does not have.

    A distinct type rather than a bare KeyError so the CLI can report it as the
    user error it is, instead of letting a traceback escape.
    """


class Strict(BaseModel):
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
        return self.landmarks[Landmark.FEET]

    @property
    def heads_tall(self) -> float:
        return self.total_height / self.units_per_head

    def pose_angles(self, pose: str) -> dict[str, float]:
        if pose not in self.poses:
            raise KeyError(
                f"puppet '{self.name}' has no pose '{pose}'; available: {sorted(self.poses)}"
            )
        return self.poses[pose]


class PuppetLibrary:
    """Puppets loaded from a directory of `*.puppet.yaml` files."""

    def __init__(self, puppets: dict[str, PuppetSpec]) -> None:
        self._puppets = puppets

    @classmethod
    def from_directory(cls, directory: Path) -> Self:
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
        if name not in self._puppets:
            raise UnknownPuppetError(
                f"unknown character '{name}'; the library has {sorted(self._puppets)}"
            )
        return self._puppets[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._puppets))


def load_puppet(path: Path) -> PuppetSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return PuppetSpec.model_validate(data)


DEFAULT_LIBRARY_PATH = Path(__file__).parent / "library"


def default_library() -> PuppetLibrary:
    return PuppetLibrary.from_directory(DEFAULT_LIBRARY_PATH)
