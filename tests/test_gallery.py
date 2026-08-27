"""Every example the playground offers must actually compile.

The playground's gallery is not a list of strings inside a TypeScript file. It is these
files, compiled here, and served to the browser at build time. So an example that stops
working fails the build rather than greeting the first visitor with a stack trace.

That also makes the gallery a coverage instrument in its own right: between them these
files exercise every shot type, every camera angle, every balloon kind, every placement
zone, every predicate and both frontends. A construct that no example uses is a
construct nobody has looked at.
"""

from pathlib import Path

import pytest
import yaml

from scenet import (
    BalloonKind,
    CameraAngle,
    CaptionKind,
    CaptionTone,
    Horizon,
    MassKind,
    Place,
    PlacementZone,
    Plane,
    Predicate,
    ShotType,
    Spans,
    TimeOfDay,
    Weather,
    compile_document,
    default_library,
    render,
    render_debug,
    render_strip,
)

GALLERY = Path(__file__).parent.parent / "examples" / "gallery"
MANIFEST = yaml.safe_load((GALLERY / "manifest.yaml").read_text(encoding="utf-8"))
ENTRIES = MANIFEST["examples"]
IDS = [entry["file"] for entry in ENTRIES]


class TestManifestMatchesDisk:
    def test_every_listed_file_exists(self):
        missing = [entry["file"] for entry in ENTRIES if not (GALLERY / entry["file"]).is_file()]
        assert missing == []

    def test_every_file_is_listed(self):
        on_disk = {path.name for path in GALLERY.iterdir() if path.name != "manifest.yaml"}
        assert on_disk == {entry["file"] for entry in ENTRIES}

    def test_every_entry_has_a_title(self):
        assert all(entry["title"].strip() for entry in ENTRIES)

    def test_kinds_are_known(self):
        assert {entry["kind"] for entry in ENTRIES} <= {"panel", "scene", "script"}


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
class TestEveryExampleWorks:
    def test_it_compiles(self, entry: dict[str, str]):
        results = compile_document(GALLERY / entry["file"])
        assert results, "a document that compiles to no panels is not an example of anything"

    def test_every_renderer_accepts_it(self, entry: dict[str, str]):
        results = compile_document(GALLERY / entry["file"])
        for result in results.values():
            assert render(result.core).lstrip().startswith("<?xml")
            assert render_debug(result.core).lstrip().startswith("<?xml")
        strip = render_strip([(name, result.core) for name, result in results.items()])
        assert strip.lstrip().startswith("<?xml")

    def test_it_is_deterministic(self, entry: dict[str, str]):
        first = compile_document(GALLERY / entry["file"])
        second = compile_document(GALLERY / entry["file"])
        assert [r.core.to_json() for r in first.values()] == [
            r.core.to_json() for r in second.values()
        ]

    def test_the_kind_in_the_manifest_is_right(self, entry: dict[str, str]):
        name = entry["file"]
        expected = (
            "script"
            if name.endswith(".script")
            else "scene"
            if name.endswith(".scene.yaml")
            else "panel"
        )
        assert entry["kind"] == expected


class TestTheGalleryCoversTheLanguage:
    """A construct no example demonstrates is a construct nobody is looking at."""

    @staticmethod
    def _all_text() -> str:
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in GALLERY.iterdir()
            if path.name != "manifest.yaml"
        )

    def test_every_shot_type_appears(self):
        text = self._all_text()
        missing = [shot.value for shot in ShotType if shot.value not in text]
        assert missing == []

    def test_every_camera_angle_appears(self):
        text = self._all_text()
        missing = [angle.value for angle in CameraAngle if angle.value not in text]
        assert missing == []

    def test_every_balloon_kind_appears(self):
        text = self._all_text()
        missing = [kind.value for kind in BalloonKind if kind.value not in text]
        assert missing == []

    def test_every_caption_kind_appears(self):
        text = self._all_text()
        missing = [kind.value for kind in CaptionKind if kind.value not in text]
        assert missing == []

    def test_every_caption_tone_appears(self):
        """A tone nobody has looked at is a tone nobody has checked reads."""
        text = self._all_text()
        missing = [tone.value for tone in CaptionTone if f"tone: {tone.value}" not in text]
        assert missing == []

    def test_every_expression_appears(self):
        """The expression vocabulary is only worth having if every face in it has been
        looked at at least once."""
        text = self._all_text()
        names = sorted(default_library().get("alice").expressions)
        missing = [name for name in names if name not in text]
        assert missing == []

    @pytest.mark.parametrize(
        "enum",
        [MassKind, Plane, Spans, Horizon, TimeOfDay, Weather, Place],
        ids=lambda enum: enum.__name__,
    )
    def test_every_setting_word_appears(self, enum):
        """The setting vocabulary is twelve mass kinds, four planes, four spans, three
        horizons, four hours, four weathers and ten places. A word no example uses is a
        word nobody has looked at -- and for this feature, "looked at" is literal: the
        contact sheet is the only thing that can tell whether a value reads as depth."""
        text = self._all_text()
        missing = [member.value for member in enum if member.value not in text]
        assert missing == []

    def test_every_predicate_appears(self):
        text = self._all_text()
        missing = [predicate.value for predicate in Predicate if predicate.value not in text]
        assert missing == []

    def test_the_corner_placement_zones_appear(self):
        text = self._all_text()
        corners = [
            PlacementZone.TOP_LEFT,
            PlacementZone.TOP_RIGHT,
            PlacementZone.BOTTOM_LEFT,
            PlacementZone.BOTTOM_RIGHT,
        ]
        assert all(zone.value in text for zone in corners)

    def test_both_frontends_appear(self):
        names = [entry["file"] for entry in ENTRIES]
        assert any(name.endswith(".script") for name in names)
        assert any(name.endswith(".panel.yaml") for name in names)
        assert any(name.endswith(".scene.yaml") for name in names)

    def test_the_setting_examples_actually_draw_something(self):
        """The examples claim to show masses. Check they resolve to some, rather than
        trusting a comment that may have outlived the behaviour it describes."""
        for name in ("19-setting.scene.yaml", "20-places.scene.yaml"):
            for panel, result in compile_document(GALLERY / name).items():
                assert result.core.backdrop is not None, f"{name}:{panel}"
                assert result.core.backdrop.masses, f"{name}:{panel}"

    def test_the_atmosphere_example_actually_has_weather(self):
        """One panel of it is `clear`, which must resolve to no atmosphere at all --
        that is the case most easily broken by making weather unconditional."""
        results = compile_document(GALLERY / "21-atmosphere.scene.yaml")
        air = {
            name: result.core.backdrop.atmosphere
            for name, result in results.items()
            if result.core.backdrop is not None
        }
        assert air["noon"] is None

        midnight, winter, morning = air["midnight"], air["winter"], air["morning"]
        assert midnight is not None
        assert winter is not None
        assert morning is not None
        assert midnight.streaks
        assert winter.flecks
        assert morning.veil is not None

    def test_the_camera_pullback_example_actually_pulls_back(self):
        """The example claims the camera retreats. Check it does, rather than trusting
        a comment that may have outlived the behaviour it describes."""
        results = compile_document(GALLERY / "10-crowd-pullback.panel.yaml")
        notes = [note for result in results.values() for note in result.notes]
        assert any("camera retreated" in note for note in notes)
