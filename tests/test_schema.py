"""The JSON Schema the editor uses for completion and validation.

The schema is generated from the pydantic models rather than hand-written, so what an
editor suggests is derived from the compiler's own definition of the language. These
tests guard the property that makes that worth doing: that the two cannot disagree.
"""

import json
from enum import StrEnum
from pathlib import Path

import pytest

from scenet.cli import main, scene_schema
from scenet.ir import (
    AnchorX,
    BalloonKind,
    CaptionTone,
    Horizon,
    MassKind,
    PanelIR,
    PlacementZone,
    Plane,
    Predicate,
    ShotType,
    Spans,
    TimeOfDay,
    Weather,
)

REPO = Path(__file__).resolve().parents[1]
SHIPPED = {
    "panel": REPO / "editor" / "schemas" / "panel.schema.json",
    "scene": REPO / "editor" / "schemas" / "scene.schema.json",
}


def generated(kind: str) -> str:
    schema = scene_schema() if kind == "scene" else PanelIR.model_json_schema()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


class TestPanelSchema:
    def test_top_level_keys_match_the_language(self):
        properties = PanelIR.model_json_schema()["properties"]
        assert set(properties) == {"panel", "camera", "setting", "cast", "staging", "script"}

    @pytest.mark.parametrize(
        "enum",
        [
            ShotType,
            AnchorX,
            Predicate,
            BalloonKind,
            CaptionTone,
            PlacementZone,
            MassKind,
            Plane,
            Spans,
            Horizon,
            TimeOfDay,
            Weather,
        ],
    )
    def test_every_enum_member_reaches_the_schema(self, enum: type[StrEnum]):
        """Completion is only useful if it offers everything the compiler accepts."""
        document = json.dumps(PanelIR.model_json_schema())
        for member in enum:
            assert f'"{member.value}"' in document, f"{enum.__name__}.{member.name} is missing"


class TestSceneSchema:
    def test_it_allows_panels_alongside_defaults(self):
        schema = scene_schema()
        assert "panels" in schema["properties"]
        # Document-level keys act as defaults every panel inherits.
        assert "camera" in schema["properties"]

    def test_panel_members_may_declare_over(self):
        member = scene_schema()["properties"]["panels"]["additionalProperties"]
        assert "over" in member["properties"]

    def test_definitions_are_carried_across(self):
        """The member schema references $defs, so dropping them would leave every
        reference dangling and the editor silently unable to validate anything."""
        schema = scene_schema()
        assert schema["$defs"]
        assert "ShotType" in schema["$defs"]

    def test_both_schemas_describe_the_same_language(self):
        panel = PanelIR.model_json_schema()["properties"]
        scene = scene_schema()["properties"]
        assert set(panel) <= set(scene)


class TestShippedSchemasAreCurrent:
    """The editor ships generated files, and a stale one is worse than none.

    A language change with no regeneration leaves the editor confidently offering
    completions that no longer compile. CI runs these, so that cannot ship.
    """

    @pytest.mark.parametrize("kind", ["panel", "scene"])
    def test_shipped_schema_is_up_to_date(self, kind: str):
        path = SHIPPED[kind]
        assert path.exists(), f"{path} is missing; run `npm run schemas` in editor/"
        assert path.read_text(encoding="utf-8") == generated(kind), (
            f"{path} is stale; run `npm run schemas` in editor/"
        )


class TestSchemaCommand:
    def test_it_writes_to_a_file(self, tmp_path: Path, capsys):
        target = tmp_path / "nested" / "panel.schema.json"
        assert main(["schema", "-o", str(target)]) == 0
        assert json.loads(target.read_text(encoding="utf-8"))["properties"]

    def test_it_prints_to_stdout_by_default(self, capsys):
        assert main(["schema"]) == 0
        assert json.loads(capsys.readouterr().out)["properties"]

    def test_the_scene_flag_selects_the_scene_schema(self, capsys):
        assert main(["schema", "--scene"]) == 0
        assert "panels" in json.loads(capsys.readouterr().out)["properties"]

    def test_output_is_deterministic(self, capsys):
        """Keys are sorted so regenerating produces no spurious diff."""
        main(["schema"])
        first = capsys.readouterr().out
        main(["schema"])
        assert capsys.readouterr().out == first
