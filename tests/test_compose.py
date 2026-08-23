"""Sparse override between panels, and the comic-script frontend.

The `over` arc is what makes a sequence writable: consecutive panels in a scene share
nearly all their staging, and restating it per panel is where continuity errors get
in.
"""

from pathlib import Path

import pytest

from scenet.compose import CompositionError, merge, resolve_overrides
from scenet.frontends.script_front import ScriptSyntaxError, load_script, parse_script
from scenet.frontends.yaml_front import PanelSyntaxError, load_scene, parse_panel, parse_scene
from scenet.ir import BalloonKind, ShotType
from scenet.pipeline import compile_document

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class TestMerge:
    def test_override_wins_on_scalars(self):
        assert merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_mappings_merge_recursively(self):
        """Changing one actor's pose must leave the rest of the cast alone."""
        base = {
            "cast": {"alice": {"pose": "standing", "at": "left_third"}, "bob": {"pose": "idle"}}
        }
        result = merge(base, {"cast": {"alice": {"pose": "pointing"}}})
        assert result["cast"]["alice"] == {"pose": "pointing", "at": "left_third"}
        assert result["cast"]["bob"] == {"pose": "idle"}

    def test_lists_replace_rather_than_append(self):
        """Script and staging are ordered wholes. Appending to an inherited script
        would make it impossible to write a panel where somebody says less."""
        assert merge({"script": [1, 2, 3]}, {"script": [9]}) == {"script": [9]}

    def test_the_base_is_not_mutated(self):
        base = {"cast": {"alice": {"pose": "standing"}}}
        merge(base, {"cast": {"alice": {"pose": "pointing"}}})
        assert base["cast"]["alice"]["pose"] == "standing"


class TestResolveOverrides:
    def test_a_panel_without_over_is_unchanged(self):
        assert resolve_overrides({"p": {"camera": {"shot": "close_up"}}}) == {
            "p": {"camera": {"shot": "close_up"}}
        }

    def test_inheritance_chains_compose(self):
        resolved = resolve_overrides(
            {
                "a": {"camera": {"shot": "wide"}, "cast": {"x": {"pose": "idle"}}},
                "b": {"over": "a", "camera": {"shot": "close_up"}},
                "c": {"over": "b", "cast": {"x": {"pose": "pointing"}}},
            }
        )
        assert resolved["c"]["camera"]["shot"] == "close_up"
        assert resolved["c"]["cast"]["x"]["pose"] == "pointing"

    def test_a_panel_may_inherit_from_one_declared_later(self):
        """Resolution is lazy, so declaration order carries no meaning."""
        resolved = resolve_overrides({"b": {"over": "a"}, "a": {"camera": {"shot": "wide"}}})
        assert resolved["b"]["camera"]["shot"] == "wide"

    def test_the_over_key_is_consumed(self):
        resolved = resolve_overrides({"a": {"camera": {}}, "b": {"over": "a"}})
        assert "over" not in resolved["b"]

    def test_declaration_order_is_preserved(self):
        resolved = resolve_overrides({"z": {}, "a": {"over": "z"}, "m": {}})
        assert list(resolved) == ["z", "a", "m"]

    def test_a_cycle_is_reported_with_the_chain(self):
        with pytest.raises(CompositionError, match="cyclic"):
            resolve_overrides({"a": {"over": "b"}, "b": {"over": "a"}})

    def test_self_reference_is_a_cycle(self):
        with pytest.raises(CompositionError, match="cyclic"):
            resolve_overrides({"a": {"over": "a"}})

    def test_an_unknown_parent_names_what_exists(self):
        with pytest.raises(CompositionError, match="does not exist"):
            resolve_overrides({"a": {"over": "nowhere"}})


class TestSceneDocuments:
    def test_a_single_panel_document_needs_no_ceremony(self):
        scene = parse_scene("cast:\n  a: {reference: alice}\n")
        assert list(scene) == ["panel"]

    def test_panels_inherit_document_level_defaults(self):
        scene = parse_scene("""
panel: {size: [640, 480]}
panels:
  one:
    cast: {a: {reference: alice}}
  two:
    cast: {a: {reference: bob}}
""")
        assert all(ir.panel.size == (640.0, 480.0) for ir in scene.values())

    def test_over_is_resolved_before_validation(self):
        """A panel that inherits its cast is valid even though it declares none."""
        scene = parse_scene("""
panels:
  one:
    camera: {shot: full_shot}
    cast: {alice: {reference: alice}}
    script: [{say: {by: alice, text: "Here."}}]
  two:
    over: one
    camera: {shot: close_up}
""")
        assert list(scene["two"].cast) == ["alice"]
        assert scene["two"].camera.shot is ShotType.CLOSE_UP
        assert scene["two"].script[0].text == "Here."

    def test_a_bad_panel_is_named_in_the_error(self):
        with pytest.raises(PanelSyntaxError, match="in panel 'two'"):
            parse_scene("""
panels:
  one: {cast: {a: {reference: alice}}}
  two: {cast: {a: {reference: alice}}, staging: ["a left_of ghost"]}
""")

    def test_shipped_sequence_example_parses(self):
        scene = load_scene(EXAMPLES / "sequence.scene.yaml")
        assert list(scene) == ["establishing", "reaction", "closer"]
        # Only Alice's pose was overridden in the last panel; Bob is untouched.
        assert scene["closer"].cast["alice"].pose == "pointing"
        assert scene["closer"].cast["bob"].pose == scene["establishing"].cast["bob"].pose


class TestComicScript:
    def test_cues_and_dialogue_are_paired(self):
        panels = parse_script("""
---
cast: {ALICE: {reference: alice}}
---
PANEL 1
ALICE
Hello there.
""")
        assert panels["1"].script[0].by == "ALICE"
        assert panels["1"].script[0].text == "Hello there."

    def test_parentheticals_select_the_balloon_kind(self):
        """A regression guard: testing the whole line for capitals rejects
        `BOB (whisper)`, silently dropping every piece of modified dialogue."""
        panels = parse_script("""
---
cast: {BOB: {reference: bob}}
---
PANEL 1
BOB (whisper)
Quietly now.
BOB (shouting)
NOT LIKE THAT!
""")
        kinds = [event.kind for event in panels["1"].script]
        assert kinds == [BalloonKind.WHISPER, BalloonKind.SHOUT]

    def test_prose_descriptions_are_not_interpreted(self):
        """Turning prose into staging needs language understanding, and guessing
        would produce panels that are confidently wrong."""
        panels = parse_script("""
---
cast: {ALICE: {reference: alice}}
---
PANEL 1
Alice stands on a rainy street corner looking furious.
ALICE
Hello.
""")
        assert len(panels["1"].script) == 1

    def test_directives_set_camera_properties(self):
        panels = parse_script("""
---
cast: {A: {reference: alice}}
---
PANEL 1
@shot: close_up
@angle: low
""")
        assert panels["1"].camera.shot is ShotType.CLOSE_UP

    def test_page_headings_are_accepted_but_carry_no_meaning(self):
        panels = parse_script("""
---
cast: {A: {reference: alice}}
---
PAGE ONE
PANEL 1
PAGE TWO
PANEL 2
""")
        assert list(panels) == ["1", "2"]

    def test_content_before_the_first_panel_is_rejected(self):
        with pytest.raises(ScriptSyntaxError, match="before the first PANEL"):
            parse_script("---\ncast: {A: {reference: alice}}\n---\nstray text\nPANEL 1\n")

    def test_a_script_with_no_panels_is_rejected(self):
        with pytest.raises(ScriptSyntaxError, match="no PANEL headings"):
            parse_script("---\ncast: {}\n---\n")

    def test_leading_blank_lines_do_not_break_front_matter(self):
        """A script pasted out of an editor very often starts with a blank line, and
        failing on that would look identical to a working file."""
        panels = parse_script("\n\n---\ncast: {A: {reference: alice}}\n---\nPANEL 1\n")
        assert list(panels) == ["1"]

    def test_shipped_script_example_parses(self):
        panels = load_script(EXAMPLES / "umbrella.script")
        assert list(panels) == ["1", "2"]
        assert [event.kind for event in panels["2"].script] == [
            BalloonKind.WHISPER,
            BalloonKind.SHOUT,
        ]


class TestFrontendDispatch:
    def test_extension_selects_the_frontend(self):
        """Every frontend produces the same IR, so adding a syntax is one line."""
        assert len(compile_document(EXAMPLES / "umbrella.script")) == 2
        assert len(compile_document(EXAMPLES / "sequence.scene.yaml")) == 3
        assert len(compile_document(EXAMPLES / "duel.panel.yaml")) == 1

    def test_an_unsupported_extension_is_rejected(self, tmp_path: Path):
        stray = tmp_path / "panel.txt"
        stray.write_text("cast: {}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unsupported extension"):
            compile_document(stray)

    def test_the_two_frontends_agree(self):
        """The same panel written as YAML and as script must compile identically --
        that is what makes them frontends onto one language rather than two."""
        common_cast = "{reference: alice, at: left_third}"
        yaml_ir = parse_panel(
            f"camera: {{shot: close_up}}\ncast:\n  A: {common_cast}\n"
            'script:\n  - say: {by: A, text: "Same words."}\n'
        )
        script_ir = parse_script(
            f"---\ncast: {{A: {common_cast}}}\n---\nPANEL 1\n@shot: close_up\nA\nSame words.\n"
        )["1"]
        assert yaml_ir == script_ir


class TestLineEndings:
    """Source arrives as a string, and not every string came from a file.

    Python's text mode normalises CRLF on read, which hides this everywhere the tests
    look. The browser playground does not: it hands over exactly the bytes it was given,
    so a script written by a Windows editor -- or pasted out of one -- reaches the parser
    with CRLF intact. It took running the gallery in a browser to notice.
    """

    SCRIPT = "---\ncast:\n  ALICE: {reference: alice}\n---\n\nPANEL 1\n\nALICE\nHello.\n"

    def test_crlf_script_parses(self):
        panels = parse_script(self.SCRIPT.replace("\n", "\r\n"))
        assert list(panels) == ["1"]
        assert panels["1"].script[0].text == "Hello."

    def test_cr_only_script_parses(self):
        """Classic Mac line endings. Rare, free to support, and free to get wrong."""
        panels = parse_script(self.SCRIPT.replace("\n", "\r"))
        assert list(panels) == ["1"]

    def test_line_endings_do_not_change_the_result(self):
        lf = parse_script(self.SCRIPT)
        crlf = parse_script(self.SCRIPT.replace("\n", "\r\n"))
        assert lf == crlf

    def test_crlf_panel_documents_parse(self):
        """PyYAML already handles this, but nothing said so."""
        source = "cast:\n  a: {reference: alice}\n"
        assert parse_panel(source) == parse_panel(source.replace("\n", "\r\n"))
