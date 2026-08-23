"""The YAML surface syntax.

Error messages get as much attention here as successful parses. A language whose
diagnostics are unhelpful is a language nobody writes twice.
"""

from pathlib import Path

import pytest

from scenet.frontends.common import parse_relation
from scenet.frontends.yaml_front import PanelSyntaxError, load_panel, parse_panel
from scenet.ir import BalloonKind, PlacementZone, Predicate, ShotType

MINIMAL = """
cast:
  alice: {reference: alice}
"""

DUEL = Path(__file__).resolve().parents[1] / "examples" / "duel.panel.yaml"


class TestRelationSentences:
    def test_parses_subject_predicate_object(self):
        relation = parse_relation("alice left_of bob")
        assert (relation.subject, relation.predicate, relation.object) == (
            "alice",
            Predicate.LEFT_OF,
            "bob",
        )

    def test_tolerates_surrounding_whitespace(self):
        assert parse_relation("  alice   left_of   bob  ").object == "bob"

    def test_unknown_predicate_lists_the_known_ones(self):
        with pytest.raises(PanelSyntaxError, match=r"known predicates are.*left_of"):
            parse_relation("alice beside bob")

    def test_wrong_arity_is_reported_as_shape(self):
        with pytest.raises(PanelSyntaxError, match="subject predicate object"):
            parse_relation("alice left_of")


class TestDocumentShape:
    def test_empty_source_is_rejected(self):
        with pytest.raises(PanelSyntaxError, match="empty"):
            parse_panel("")

    def test_non_mapping_top_level_is_rejected(self):
        with pytest.raises(PanelSyntaxError, match="mapping at the top level"):
            parse_panel("- just\n- a list\n")

    def test_malformed_yaml_is_reported_as_yaml(self):
        with pytest.raises(PanelSyntaxError, match="invalid YAML"):
            parse_panel("cast: {unclosed")

    def test_source_path_appears_in_the_message(self, tmp_path: Path):
        bad = tmp_path / "broken.panel.yaml"
        bad.write_text("- nope\n", encoding="utf-8")
        with pytest.raises(PanelSyntaxError, match=r"broken\.panel\.yaml"):
            load_panel(bad)


class TestDefaults:
    def test_a_minimal_panel_gets_sensible_defaults(self):
        panel = parse_panel(MINIMAL)
        assert panel.panel.size == (1000.0, 1000.0)
        assert panel.camera.shot is ShotType.MEDIUM_SHOT
        assert panel.cast["alice"].pose == "standing_neutral"
        assert panel.script == ()


class TestScript:
    def test_say_events_are_parsed(self):
        panel = parse_panel("""
cast:
  alice: {reference: alice}
script:
  - say: {by: alice, text: "Hello", prefer: top_left, kind: shout}
""")
        event = panel.script[0]
        assert event.text == "Hello"
        assert event.prefer is PlacementZone.TOP_LEFT
        assert event.kind is BalloonKind.SHOUT

    def test_unknown_verb_is_rejected(self):
        with pytest.raises(PanelSyntaxError, match="unknown verb 'sing'"):
            parse_panel("""
cast:
  alice: {reference: alice}
script:
  - sing: {by: alice, text: "la"}
""")

    def test_multi_key_script_entry_is_rejected(self):
        """Two verbs in one entry is ambiguous about ordering, so it is refused
        rather than silently resolved."""
        with pytest.raises(PanelSyntaxError, match="single-key mapping"):
            parse_panel("""
cast:
  alice: {reference: alice}
script:
  - {say: {by: alice, text: "a"}, shout: {by: alice, text: "b"}}
""")

    def test_script_order_is_preserved(self):
        panel = parse_panel("""
cast:
  a: {reference: alice}
  b: {reference: bob}
script:
  - say: {by: a, text: "first"}
  - say: {by: b, text: "second"}
  - say: {by: a, text: "third"}
""")
        assert [event.text for event in panel.script] == ["first", "second", "third"]


class TestDiagnostics:
    def test_validation_error_names_the_location(self):
        """Model-level validators report against the block rather than the field,
        because the check spans several fields. Naming the block and the reason is
        enough to locate it."""
        with pytest.raises(PanelSyntaxError, match="at panel: panel size must be positive"):
            parse_panel("panel: {size: [0, 100]}\ncast: {}\n")

    def test_unknown_actor_is_named(self):
        with pytest.raises(PanelSyntaxError, match="carol"):
            parse_panel("""
cast:
  alice: {reference: alice}
staging:
  - alice left_of carol
""")


class TestExample:
    def test_shipped_example_parses(self):
        panel = load_panel(DUEL)
        assert set(panel.cast) == {"alice", "bob"}
        assert panel.ordering_constraints() == (("alice", "bob"),)
        assert panel.gaze_targets() == {"alice": "bob"}
        assert panel.ground_groups() == (frozenset({"alice", "bob"}),)
        assert len(panel.script) == 2

    def test_parsing_is_repeatable(self):
        """Same bytes in, same IR out -- the foundation of every downstream golden
        test."""
        assert load_panel(DUEL) == load_panel(DUEL)
