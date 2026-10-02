"""The `cast` experiment from issue #11: everything in it that needs no network.

`scripts/cast_experiment.py` asks Gemini for the same panels under several response
schemas and records how far each answer gets through the compiler. The live calls are
not tested here -- the default run never touches the network -- but everything that
decides what a call *means* is: how each schema variant is built, how a flattened cast
is read back, and which stage an answer is charged to. A mistake in any of those would
quietly move a failure from one arm to another, which is the one thing an experiment
comparing arms cannot afford.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scenet import default_library
from scenet.ir import PanelIR
from scenet.schema import panel_schema

ROOT = Path(__file__).resolve().parents[1]


def _load_experiment() -> ModuleType:
    """Import `scripts/cast_experiment.py`, which is a script rather than a package module."""
    path = ROOT / "scripts" / "cast_experiment.py"
    spec = importlib.util.spec_from_file_location("cast_experiment", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cast_experiment"] = module
    spec.loader.exec_module(module)
    return module


ex = _load_experiment()

#: One panel in the IR's own shape, which every arm should carry to an SVG.
GOOD_IR: dict[str, Any] = {
    "camera": {"shot": "medium_full"},
    "cast": {
        "alice": {"reference": "alice", "pose": "pointing"},
        "bob": {"reference": "bob", "facing": "left"},
    },
    "staging": [{"subject": "alice", "predicate": "left_of", "object": "bob"}],
    "script": [
        {"verb": "caption", "text": "Later."},
        {"verb": "say", "by": "alice", "text": "There you are."},
    ],
}


def _as_list(document: dict[str, Any]) -> dict[str, Any]:
    cast = [{"id": actor, **member} for actor, member in document["cast"].items()]
    return {**document, "cast": cast}


def _as_surface(document: dict[str, Any]) -> dict[str, Any]:
    script = [
        {event["verb"]: {key: value for key, value in event.items() if key != "verb"}}
        for event in document["script"]
    ]
    return {**document, "script": script}


def _walk(node: object) -> list[tuple[str, object]]:
    """Every (key, value) pair anywhere in a JSON document."""
    pairs: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            pairs.append((key, value))
            pairs.extend(_walk(value))
    elif isinstance(node, list):
        for item in node:
            pairs.extend(_walk(item))
    return pairs


def _arm(field: str, base: str, cast: str, *, closed: bool = True) -> object:
    return ex.Arm(ex.ApiField(field), ex.Base(base), ex.CastShape(cast), closed=closed)


class TestSchemas:
    def test_the_mapping_arm_sends_the_ir_schema_unchanged(self):
        arm = _arm("responseJsonSchema", "ir", "mapping")
        assert ex.schema_for(arm) == PanelIR.model_json_schema()

    def test_the_surface_mapping_arm_sends_the_published_schema_unchanged(self):
        arm = _arm("responseJsonSchema", "surface", "mapping")
        assert ex.schema_for(arm) == panel_schema()

    def test_flattening_turns_cast_into_a_list_of_members_with_an_id(self):
        schema = ex.flatten_cast(PanelIR.model_json_schema())
        cast = schema["properties"]["cast"]
        assert cast["type"] == "array"
        entry = schema["$defs"][cast["items"]["$ref"].rsplit("/", 1)[1]]
        member = PanelIR.model_json_schema()["$defs"]["CastMember"]
        assert entry["required"][0] == "id"
        assert set(entry["required"]) == {"id", *member.get("required", [])}
        assert next(iter(entry["properties"])) == "id"
        assert {key: value for key, value in entry["properties"].items() if key != "id"} == (
            member["properties"]
        )
        assert entry["additionalProperties"] is False

    def test_flattening_changes_nothing_but_cast(self):
        original = PanelIR.model_json_schema()
        schema = ex.flatten_cast(original)
        assert original == PanelIR.model_json_schema(), "the input must not be modified"
        for key in original["properties"]:
            if key != "cast":
                assert schema["properties"][key] == original["properties"][key]
        for name, definition in original["$defs"].items():
            assert schema["$defs"][name] == definition

    def test_opening_removes_every_closed_object_but_keeps_the_cast_values(self):
        schema = ex.open_schema(PanelIR.model_json_schema())
        assert ("additionalProperties", False) not in _walk(schema)
        assert schema["properties"]["cast"]["additionalProperties"] == {
            "$ref": "#/$defs/CastMember"
        }

    def test_the_closed_ir_schema_really_is_closed_throughout(self):
        """The premise of the open/closed arms: `extra="forbid"` closes every object."""
        schema = PanelIR.model_json_schema()
        objects = [
            name for name, definition in schema["$defs"].items() if "properties" in definition
        ]
        assert objects
        for name in objects:
            assert schema["$defs"][name]["additionalProperties"] is False, name
        assert schema["additionalProperties"] is False

    @pytest.mark.parametrize("cast", ["mapping", "list"])
    def test_the_openapi_form_uses_only_keywords_responseschema_accepts(self, cast):
        schema = ex.schema_for(_arm("responseSchema", "ir", cast))
        keys = {key for key, _ in _walk(schema)}
        # Every one of these was refused by the API with "Unknown name ... Cannot find
        # field" when sent as `responseSchema`; see the module docstring.
        for keyword in ("$ref", "$defs", "$schema", "additionalProperties", "const", "default"):
            assert keyword not in keys - _property_names(schema), keyword

    def test_the_openapi_mapping_cast_is_an_object_with_nothing_to_say_about_its_values(self):
        schema = ex.schema_for(_arm("responseSchema", "ir", "mapping"))
        assert schema["properties"]["cast"] == {"title": "Cast", "type": "object"}

    def test_the_openapi_list_cast_still_describes_a_member(self):
        schema = ex.schema_for(_arm("responseSchema", "ir", "list"))
        items = schema["properties"]["cast"]["items"]
        assert items["required"][0] == "id"
        assert items["properties"]["at"]["enum"] == [
            "left_edge",
            "left_third",
            "center",
            "right_third",
            "right_edge",
        ]

    def test_every_object_states_its_property_order(self):
        """Without it the API reorders keys, and the model skipped cast and script."""
        schema = ex.schema_for(_arm("responseSchema", "ir", "list"))
        assert schema["propertyOrdering"] == list(PanelIR.model_json_schema()["properties"])
        objects = [node for node in _nodes(schema) if node.get("properties")]
        assert objects
        for node in objects:
            assert node["propertyOrdering"] == list(node["properties"])

    def test_an_optional_field_becomes_nullable(self):
        schema = ex.schema_for(_arm("responseSchema", "ir", "list"))
        say = schema["properties"]["script"]["items"]["anyOf"][0]
        assert say["properties"]["prefer"]["nullable"] is True
        assert "anyOf" not in say["properties"]["prefer"]

    def test_a_tuple_becomes_a_fixed_length_list(self):
        schema = ex.schema_for(_arm("responseSchema", "ir", "list"))
        size = schema["properties"]["panel"]["properties"]["size"]
        assert size["type"] == "array"
        assert size["items"]["type"] == "number"
        assert (size["minItems"], size["maxItems"]) == (2, 2)

    def test_every_arm_is_deterministic_and_serialisable(self):
        for arm in ex.ARMS:
            assert json.dumps(ex.schema_for(arm), sort_keys=True) == json.dumps(
                ex.schema_for(arm), sort_keys=True
            )

    def test_arm_names_are_unique(self):
        names = [arm.name for arm in ex.ARMS]
        assert len(names) == len(set(names))


def _nodes(node: object) -> list[dict[str, Any]]:
    """Every object anywhere in a JSON document."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_nodes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_nodes(item))
    return found


def _property_names(schema: dict[str, Any]) -> set[str]:
    """Keys that are field names inside `properties`, not schema keywords."""
    names: set[str] = set()
    for key, value in _walk(schema):
        if key == "properties" and isinstance(value, dict):
            names.update(value)
    return names


class TestRestoringTheCast:
    def test_a_list_is_read_back_in_order(self):
        restored = ex.restore_cast(_as_list(GOOD_IR))
        assert list(restored["cast"]) == ["alice", "bob"]
        assert restored["cast"]["bob"] == {"reference": "bob", "facing": "left"}

    def test_a_mapping_passes_through(self):
        assert ex.restore_cast(GOOD_IR) == GOOD_IR

    def test_a_repeated_id_is_refused_rather_than_overwritten(self):
        document = _as_list(GOOD_IR)
        document["cast"].append({"id": "alice", "reference": "bob"})
        with pytest.raises(ex.DuplicateActorError, match="alice"):
            ex.restore_cast(document)

    def test_a_member_without_an_id_is_refused(self):
        document = {"cast": [{"reference": "alice"}]}
        with pytest.raises(ex.DuplicateActorError, match="no id"):
            ex.restore_cast(document)

    def test_a_repeated_json_key_is_refused_rather_than_overwritten(self):
        with pytest.raises(ex.DuplicateActorError, match="alice"):
            ex.load_json(
                '{"cast": {"alice": {"reference": "alice"}, "alice": {"reference": "bob"}}}'
            )


class TestJudging:
    @pytest.mark.parametrize(
        ("field", "cast"),
        [
            ("responseJsonSchema", "mapping"),
            ("responseJsonSchema", "list"),
            ("responseSchema", "mapping"),
            ("responseSchema", "list"),
        ],
    )
    def test_a_good_ir_panel_compiles_in_every_shape(self, field, cast):
        document = GOOD_IR if cast == "mapping" else _as_list(GOOD_IR)
        verdict = ex.judge(json.dumps(document), _arm(field, "ir", cast))
        assert verdict.stage is ex.Stage.COMPILED, verdict.detail
        assert verdict.conforms is True

    @pytest.mark.parametrize("cast", ["mapping", "list"])
    def test_a_good_surface_panel_compiles_through_the_yaml_frontend(self, cast):
        document = _as_surface(GOOD_IR if cast == "mapping" else _as_list(GOOD_IR))
        verdict = ex.judge(json.dumps(document), _arm("responseJsonSchema", "surface", cast))
        assert verdict.stage is ex.Stage.COMPILED, verdict.detail

    def test_the_ir_shaped_script_is_not_what_the_yaml_frontend_reads(self):
        verdict = ex.judge(json.dumps(GOOD_IR), _arm("responseJsonSchema", "surface", "mapping"))
        assert verdict.stage is ex.Stage.VALIDATION
        assert verdict.conforms is False

    def test_broken_json(self):
        verdict = ex.judge('{"cast": ', _arm("responseJsonSchema", "ir", "mapping"))
        assert verdict.stage is ex.Stage.JSON

    def test_a_top_level_list_is_not_a_panel(self):
        verdict = ex.judge("[]", _arm("responseJsonSchema", "ir", "mapping"))
        assert verdict.stage is ex.Stage.VALIDATION

    def test_an_unknown_speaker_is_a_validation_failure_with_its_rule(self):
        document = {**GOOD_IR, "script": [{"verb": "say", "by": "carol", "text": "Hi."}]}
        verdict = ex.judge(json.dumps(document), _arm("responseJsonSchema", "ir", "mapping"))
        assert verdict.stage is ex.Stage.VALIDATION
        assert verdict.detail.startswith("unknown-actor")
        assert verdict.conforms is True, "the schema cannot see this; that is the point"

    def test_an_ordering_cycle_is_a_validation_failure_with_its_rule(self):
        staging = [
            {"subject": "alice", "predicate": "left_of", "object": "bob"},
            {"subject": "bob", "predicate": "left_of", "object": "alice"},
        ]
        verdict = ex.judge(
            json.dumps({**GOOD_IR, "staging": staging}), _arm("responseJsonSchema", "ir", "mapping")
        )
        assert verdict.stage is ex.Stage.VALIDATION
        assert verdict.detail.startswith("ordering-cycle")

    def test_a_repeated_id_in_a_flattened_cast(self):
        document = _as_list(GOOD_IR)
        document["cast"].append({"id": "bob", "reference": "alice"})
        verdict = ex.judge(json.dumps(document), _arm("responseJsonSchema", "ir", "list"))
        assert verdict.stage is ex.Stage.DUPLICATE

    def test_an_unknown_puppet_gets_as_far_as_the_compiler(self):
        cast = {"alice": {"reference": "zelda"}, "bob": {"reference": "bob"}}
        verdict = ex.judge(
            json.dumps({**GOOD_IR, "cast": cast}), _arm("responseJsonSchema", "ir", "mapping")
        )
        assert verdict.stage is ex.Stage.COMPILE
        assert verdict.detail.startswith("UnknownPuppetError")

    def test_an_empty_cast_with_dialogue_fails_validation(self):
        """What `responseSchema` leaves a mapping cast able to say: nothing."""
        document = {**GOOD_IR, "cast": {}}
        verdict = ex.judge(json.dumps(document), _arm("responseSchema", "ir", "mapping"))
        assert verdict.stage is ex.Stage.VALIDATION

    def test_an_answer_that_breaks_the_schema_is_flagged_even_when_it_compiles(self):
        document = {**GOOD_IR, "panel": {"size": [800, 600], "colour": "red"}}
        verdict = ex.judge(json.dumps(document), _arm("responseJsonSchema", "ir", "mapping"))
        assert verdict.conforms is False


class TestRequests:
    def test_the_body_pins_what_a_rerun_needs(self):
        arm = _arm("responseJsonSchema", "ir", "list")
        body = ex.request_body(arm, ex.PROMPTS[0], seed=3)
        config = body["generationConfig"]
        assert config["temperature"] == ex.TEMPERATURE
        assert config["seed"] == 3
        assert config["responseMimeType"] == "application/json"
        assert config["responseJsonSchema"] == ex.schema_for(arm)
        assert "responseSchema" not in config
        assert body["contents"][0]["parts"][0]["text"] == ex.PROMPTS[0].brief

    def test_the_openapi_arm_uses_the_other_field(self):
        body = ex.request_body(_arm("responseSchema", "ir", "list"), ex.PROMPTS[0], seed=0)
        assert "responseSchema" in body["generationConfig"]
        assert "responseJsonSchema" not in body["generationConfig"]

    def test_the_instructions_do_not_favour_either_cast_shape(self):
        text = ex.SYSTEM_INSTRUCTION
        for word in ("mapping", "dict", "list of", "array", "key", "id"):
            assert f" {word} " not in f" {text.lower()} ", word

    def test_the_instructions_name_every_shipped_puppet(self):
        for name in default_library().names():
            assert name in ex.SYSTEM_INSTRUCTION

    def test_there_are_enough_prompts_and_their_ids_are_unique(self):
        assert len(ex.PROMPTS) >= 20
        assert len({prompt.id for prompt in ex.PROMPTS}) == len(ex.PROMPTS)


class TestSummary:
    def _record(self, arm: str, prompt: str, stage: str) -> dict[str, Any]:
        return {"arm": arm, "prompt": prompt, "seed": 0, "stage": stage}

    def test_counts_and_rates_leave_api_errors_out_of_the_denominator(self):
        records = [
            self._record("a", "p1", "compiled"),
            self._record("a", "p2", "ir_validation"),
            self._record("a", "p3", "api_error"),
        ]
        (row,) = ex.tally(records)
        assert row.arm == "a"
        assert row.attempted == 2
        assert row.counts["compiled"] == 1
        assert row.valid == 1
        assert row.compiled == 1

    def test_valid_counts_anything_that_got_past_validation(self):
        records = [self._record("a", "p1", "compile"), self._record("a", "p2", "compiled")]
        (row,) = ex.tally(records)
        assert (row.valid, row.compiled) == (2, 1)

    @pytest.mark.parametrize(
        ("only_first", "only_second", "expected"),
        [(0, 0, 1.0), (6, 0, 0.03125), (0, 6, 0.03125), (3, 3, 1.0), (1, 0, 1.0)],
    )
    def test_mcnemar_exact(self, only_first, only_second, expected):
        assert ex.mcnemar(only_first, only_second) == pytest.approx(expected)

    def test_paired_comparison_counts_discordant_prompts(self):
        records = [
            self._record("a", "p1", "compiled"),
            self._record("b", "p1", "ir_validation"),
            self._record("a", "p2", "compiled"),
            self._record("b", "p2", "compiled"),
            self._record("a", "p3", "api_error"),
            self._record("b", "p3", "ir_validation"),
        ]
        assert ex.discordant(records, "a", "b") == (1, 0)
