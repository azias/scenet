"""Structured diagnostics, and the SARIF document they serialise to.

The prose diagnostic is for a person. This is the other audience: CI, an editor, an
agent repairing its own output. The two must never disagree, because they are the same
finding rendered twice -- so several of these tests assert exactly that.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from scenet.diagnostics import (
    RULES,
    Diagnostic,
    Position,
    Region,
    _message_of,
    _region_json,
    _rule_for_scenet_error,
    _uri_for,
    diagnose_file,
    diagnose_source,
    to_sarif,
)
from scenet.errors import (
    AssetError,
    BalloonPlacementError,
    CompositionError,
    LayoutError,
    PanelSyntaxError,
    UnknownPuppetError,
)
from scenet.frontends.positions import DOCUMENT_START, locate, syntax_error_region
from scenet.frontends.yaml_front import parse_panel

# A panel whose only fault is the speaker's name. The interesting case, because no JSON
# Schema can catch it: the actor exists as a string, it just is not in the cast.
UNKNOWN_ACTOR = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice}
script:
  - say: {by: bpb, text: Hello}
"""

CYCLE = """\
panel: {size: [420, 560]}
cast:
  a: {reference: alice}
  b: {reference: bob}
staging:
  - a left_of b
  - b left_of a
"""

CLEAN = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice}
script:
  - say: {by: alice, text: Hello}
"""


class TestDiagnosingADocument:
    """`diagnose_source` reports what is wrong without raising."""

    def test_a_valid_document_produces_nothing(self):
        assert diagnose_source(CLEAN, source=Path("clean.panel.yaml")) == []

    def test_an_unknown_speaker_is_reported(self):
        (found,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        assert found.rule == "unknown-actor"
        assert "bpb" in found.message

    def test_it_names_the_field_rather_than_the_document(self):
        """A model-level validator reports `loc=()` to pydantic -- the whole document.

        That is useless for an editor squiggle and useless for a fix. The validator
        knows the path; it just had nowhere to put it until `RuleViolationError` existed.
        """
        (found,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        assert found.path == ("script", 0, "by")

    def test_a_cycle_is_reported_against_the_staging_entry(self):
        (found,) = diagnose_source(CYCLE, source=Path("cycle.panel.yaml"))
        assert found.rule == "ordering-cycle"
        assert found.path[0] == "staging"

    def test_a_missing_field_keeps_its_pydantic_path(self):
        source = "panel: {size: [420, 560]}\ncast: {alice: {}}\n"
        (found,) = diagnose_source(source, source=Path("x.panel.yaml"))
        assert found.rule == "missing-field"
        assert found.path == ("cast", "alice", "reference")

    def test_an_unknown_key_is_its_own_rule(self):
        """Strict validation rejects unknown keys, which is usually a typo."""
        source = "panel: {size: [420, 560]}\ncmaera: {shot: close_up}\n"
        (found,) = diagnose_source(source, source=Path("x.panel.yaml"))
        assert found.rule == "unknown-key"

    def test_unparseable_yaml_is_reported_rather_than_raised(self):
        found = diagnose_source("panel: [unclosed\n", source=Path("bad.panel.yaml"))
        assert [item.rule for item in found] == ["syntax"]

    def test_every_rule_used_is_in_the_catalogue(self):
        """A `ruleId` with no rule object is a SARIF document GitHub will reject."""
        for text in (UNKNOWN_ACTOR, CYCLE, "panel: {size: [0, 10]}\n"):
            for found in diagnose_source(text, source=Path("x.panel.yaml")):
                assert found.rule in RULES


class TestSourcePositions:
    """`yaml.compose` keeps the marks `safe_load` throws away."""

    def test_the_speaker_is_located_on_its_own_line(self):
        (found,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        assert found.region is not None
        # `- say: {by: bpb, ...}` is the fifth line of the document.
        assert found.region.start.line == 5

    def test_lines_and_columns_are_one_based(self):
        """PyYAML marks are 0-based and SARIF is 1-based. Exactly the sort of thing
        that is off by one for a year because nobody looks at the first line."""
        source = "cast: {alice: {}}\n"
        (found,) = diagnose_source(source, source=Path("x.panel.yaml"))
        assert found.region is not None
        assert found.region.start.line == 1
        assert found.region.start.column >= 1

    def test_a_document_level_finding_still_has_a_region(self):
        """SARIF requires a location on every result. A finding with no obvious
        position gets the start of the document rather than no location at all."""
        found = diagnose_source("[]\n", source=Path("x.panel.yaml"))
        assert found
        for item in found:
            assert item.region is not None
            assert item.region.start.line >= 1


class TestTheSarifDocument:
    """The shape GitHub code scanning will actually accept."""

    @pytest.fixture
    def document(self) -> dict[str, Any]:
        found = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        return to_sarif(found, root=Path.cwd())

    def test_it_declares_the_version_github_ingests(self, document: dict[str, Any]):
        """2.1.0, not 2.2: 2.2 is still a draft and nothing consumes it yet."""
        assert document["version"] == "2.1.0"

    def test_it_is_json_serialisable(self, document: dict[str, Any]):
        assert json.loads(json.dumps(document)) == document

    def test_the_driver_names_the_tool_and_its_version(self, document: dict[str, Any]):
        driver = document["runs"][0]["tool"]["driver"]
        assert driver["name"] == "scenet"
        assert driver["version"]

    def test_every_result_carries_what_github_requires(self, document: dict[str, Any]):
        for result in document["runs"][0]["results"]:
            assert result["message"]["text"]
            assert result["locations"]
            assert result["partialFingerprints"]
            region = result["locations"][0]["physicalLocation"]["region"]
            for key in ("startLine", "startColumn", "endLine", "endColumn"):
                assert isinstance(region[key], int)
                assert region[key] >= 1

    def test_every_rule_carries_what_github_requires(self, document: dict[str, Any]):
        for rule in document["runs"][0]["tool"]["driver"]["rules"]:
            assert rule["id"]
            for key in ("shortDescription", "fullDescription", "help"):
                # Empty strings are rejected for required properties.
                assert rule[key]["text"].strip()

    def test_rule_index_points_at_the_right_rule(self, document: dict[str, Any]):
        run = document["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        for result in run["results"]:
            assert rules[result["ruleIndex"]]["id"] == result["ruleId"]

    def test_the_artifact_uri_is_relative(self, document: dict[str, Any]):
        """An absolute path would break code scanning's file matching, and the project
        forbids absolute paths in output outright -- it would break determinism."""
        uri = document["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert not Path(uri).is_absolute()
        assert "\\" not in uri, "SARIF URIs use forward slashes on every platform"

    def test_a_clean_document_produces_a_run_with_no_results(self):
        """Not an empty file. A SARIF consumer needs the run to know the tool passed,
        otherwise a clean check is indistinguishable from a check that never ran."""
        document = to_sarif([], root=Path.cwd())
        assert document["runs"][0]["results"] == []


class TestFingerprintsAreStable:
    """`partialFingerprints` de-duplicate alerts across runs, so they must not move."""

    def test_the_same_finding_fingerprints_identically(self):
        first = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        second = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        assert [item.fingerprint() for item in first] == [item.fingerprint() for item in second]

    def test_it_survives_the_finding_moving_down_the_file(self):
        """A fingerprint keyed on line number changes whenever anybody adds a comment
        at the top, which turns one alert into a new alert on every edit."""
        moved = "# a new comment\n# and another\n" + UNKNOWN_ACTOR
        (original,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        (shifted,) = diagnose_source(moved, source=Path("duel.panel.yaml"))
        assert original.region != shifted.region, "the test is meaningless if it did not move"
        assert original.fingerprint() == shifted.fingerprint()

    def test_different_rules_fingerprint_differently(self):
        (actor,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        (cycle,) = diagnose_source(CYCLE, source=Path("cycle.panel.yaml"))
        assert actor.fingerprint() != cycle.fingerprint()

    def test_the_same_fault_in_two_files_fingerprints_differently(self):
        (here,) = diagnose_source(UNKNOWN_ACTOR, source=Path("a.panel.yaml"))
        (there,) = diagnose_source(UNKNOWN_ACTOR, source=Path("b.panel.yaml"))
        assert here.fingerprint() != there.fingerprint()


class TestTheProseAndTheSarifAgree:
    """Two renderings of one finding. They cannot be allowed to drift."""

    def test_the_prose_diagnostic_now_names_the_path(self):
        """This is the improvement the structured work paid for: these findings used to
        render as `at <root>`, because the model validator had nowhere to put a path."""
        with pytest.raises(PanelSyntaxError) as caught:
            parse_panel(UNKNOWN_ACTOR)
        assert "at script.0.by:" in str(caught.value)

    def test_the_message_text_is_the_same_in_both(self):
        (found,) = diagnose_source(UNKNOWN_ACTOR, source=Path("duel.panel.yaml"))
        with pytest.raises(PanelSyntaxError) as caught:
            parse_panel(UNKNOWN_ACTOR)
        assert found.message in str(caught.value)


class TestDiagnosticsAreOrdered:
    """Determinism is a project non-negotiable, and it reaches this far."""

    def test_findings_come_back_in_source_order(self):
        source = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice}
  bob: {}
"""
        found = diagnose_source(source, source=Path("x.panel.yaml"))
        positions = [item.region.start.line for item in found if item.region]
        assert positions == sorted(positions)

    def test_the_sarif_document_is_byte_identical_across_runs(self):
        first = to_sarif(
            diagnose_source(UNKNOWN_ACTOR, source=Path("d.panel.yaml")), root=Path.cwd()
        )
        second = to_sarif(
            diagnose_source(UNKNOWN_ACTOR, source=Path("d.panel.yaml")), root=Path.cwd()
        )
        assert json.dumps(first, sort_keys=False) == json.dumps(second, sort_keys=False)


class TestTheValueObjects:
    """Small types, but a wrong comparison here is a wrong squiggle in an editor."""

    def test_a_region_knows_where_it_starts_and_ends(self):
        region = Region(start=Position(line=3, column=5), end=Position(line=3, column=9))
        assert region.start.line == 3
        assert region.end.column == 9

    def test_diagnostics_compare_by_value(self):
        one = Diagnostic(rule="unknown-actor", message="m", path=("script",), source=Path("a.yaml"))
        two = Diagnostic(rule="unknown-actor", message="m", path=("script",), source=Path("a.yaml"))
        assert one == two


class TestPositionsInAwkwardShapes:
    """The walk has to survive paths that do not match the document."""

    def test_it_indexes_into_a_sequence(self):
        region = locate("staging:\n  - a left_of b\n  - b left_of a\n", ("staging", 1))
        assert region is not None
        assert region.start.line == 3

    def test_an_index_past_the_end_falls_back_to_the_sequence(self):
        """Not an error: a `loc` path can name an index the document does not have when
        validation failed before the list was fully built."""
        region = locate("staging:\n  - a left_of b\n", ("staging", 9))
        assert region is not None
        assert region.start.line == 2

    def test_unparseable_text_locates_nothing(self):
        assert locate("panel: [unclosed\n", ("panel",)) is None

    def test_an_empty_document_locates_nothing(self):
        assert locate("", ("panel",)) is None

    def test_a_yaml_error_without_a_mark_falls_back_to_the_start(self):
        assert syntax_error_region(yaml.YAMLError("no mark on this one")) == DOCUMENT_START


class TestErrorsThatEscapeTheCompiler:
    """Not every fault is a validation error. Each still needs a rule."""

    def test_an_unresolvable_over_chain_is_a_composition_finding(self):
        assert _rule_for_scenet_error(CompositionError("cyclic")) == "composition"

    def test_a_missing_puppet_has_its_own_rule(self):
        assert _rule_for_scenet_error(UnknownPuppetError("nobody")) == "unknown-puppet"

    def test_solver_failures_are_distinguished(self):
        assert _rule_for_scenet_error(LayoutError("no room")) == "layout"
        assert _rule_for_scenet_error(BalloonPlacementError("nowhere")) == "balloon-placement"

    def test_anything_unaccounted_for_is_reported_rather_than_dropped(self):
        assert _rule_for_scenet_error(AssetError("malformed puppet")) == "internal"

    def test_a_key_error_message_is_not_repr_quoted(self):
        """`KeyError` stringifies as `repr(args[0])`, which would put quotes round the
        whole diagnostic."""
        assert _message_of(UnknownPuppetError("no puppet 'ghost'")) == "no puppet 'ghost'"


class TestUriHandling:
    def test_a_path_outside_the_root_does_not_leak_an_absolute_path(self, tmp_path: Path):
        """Absolute paths in output are forbidden outright -- they break determinism."""
        uri = _uri_for(tmp_path / "elsewhere.panel.yaml", root=Path.cwd())
        assert not Path(uri).is_absolute()
        assert uri == "elsewhere.panel.yaml"

    def test_in_memory_text_is_named_rather_than_left_blank(self):
        """SARIF rejects an empty string for a required property."""
        assert _uri_for(None, root=None) == "<string>"


class TestRegionsSarifWillAccept:
    def test_a_zero_width_region_is_widened(self):
        """GitHub rejects a region that does not cover at least one character."""
        region = Region(start=Position(line=4, column=7), end=Position(line=4, column=7))
        assert _region_json(region)["endColumn"] > _region_json(region)["startColumn"]

    def test_bounds_below_one_are_lifted(self):
        emitted = _region_json(Region(start=Position(line=0, column=0), end=Position(0, 0)))
        assert emitted["startLine"] == 1
        assert emitted["startColumn"] == 1


class TestSceneDocuments:
    """A `panels:` document is a sequence, not a panel with an odd key.

    Validating one as a single panel reported `panels` as an unknown key -- a confident
    and completely wrong diagnostic on every valid scene file in the repository.
    """

    SCENE = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice}
panels:
  wide: {camera: {shot: long_shot}}
  tight: {camera: {shot: close_up}}
"""

    def test_a_valid_scene_produces_nothing(self):
        assert diagnose_source(self.SCENE, source=Path("s.scene.yaml")) == []

    def test_the_gallery_scenes_are_clean(self):
        """The examples are the language's shop window; a false positive on them would
        make the checker useless the first time anybody ran it."""
        for path in sorted(Path("examples/gallery").glob("*.scene.yaml")):
            assert diagnose_file(path) == [], path

    def test_a_fault_inside_a_panel_names_that_panel(self):
        broken = self.SCENE.replace(
            "  tight: {camera: {shot: close_up}}",
            "  tight: {camera: {shot: close_up}, script: [{say: {by: nobody, text: hi}}]}",
        )
        (found,) = diagnose_source(broken, source=Path("s.scene.yaml"))
        assert found.rule == "unknown-actor"
        assert found.path[:2] == ("panels", "tight")

    def test_every_broken_panel_is_reported(self):
        """One finding per bad panel, not one and two more runs to discover the rest."""
        broken = self.SCENE.replace(
            "  wide: {camera: {shot: long_shot}}",
            "  wide: {camera: {shot: nonsense}}",
        ).replace(
            "  tight: {camera: {shot: close_up}}",
            "  tight: {camera: {shot: also_nonsense}}",
        )
        found = diagnose_source(broken, source=Path("s.scene.yaml"))
        assert len(found) == 2

    def test_a_broken_over_chain_is_a_composition_finding(self):
        cyclic = "panels:\n  a: {over: b}\n  b: {over: a}\n"
        (found,) = diagnose_source(cyclic, source=Path("s.scene.yaml"))
        assert found.rule == "composition"

    def test_panels_must_be_a_mapping(self):
        (found,) = diagnose_source("panels: [1, 2]\n", source=Path("s.scene.yaml"))
        assert found.rule == "invalid-field"
        assert "mapping" in found.message

    def test_a_panel_that_is_not_a_mapping_is_reported(self):
        (found,) = diagnose_source("panels:\n  a: 3\n", source=Path("s.scene.yaml"))
        assert found.rule == "invalid-field"
        assert "'a'" in found.message
