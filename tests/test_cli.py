"""The command-line interface.

Error handling gets the most attention here. A panel that cannot be compiled is the
user's problem to fix, so it must produce a readable message and a non-zero exit --
never a traceback, which tells them nothing actionable.
"""

from pathlib import Path

import pytest

from scenet import __version__
from scenet.cli import build_parser, main

PANEL = """
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: bob,   at: right_third}
staging:
  - alice left_of bob
script:
  - say: {by: alice, text: "Hello there."}
"""


@pytest.fixture
def panel_file(tmp_path: Path) -> Path:
    path = tmp_path / "scene.panel.yaml"
    path.write_text(PANEL, encoding="utf-8")
    return path


class TestBasics:
    def test_version_is_populated(self):
        assert __version__
        assert __version__ != "0.0.0+unknown", "package metadata should be installed"

    def test_version_flag_exits_zero(self, capsys: pytest.CaptureFixture[str]):
        with pytest.raises(SystemExit) as exc:
            build_parser().parse_args(["--version"])
        assert exc.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_bare_invocation_prints_help_to_stderr_and_fails(
        self, capsys: pytest.CaptureFixture[str]
    ):
        # Exit 2, not 0: a bare `scenet` did nothing, and a shell script chaining off
        # its status must not read that as success.
        assert main([]) == 2
        assert "usage: scenet" in capsys.readouterr().err

    def test_unknown_argument_is_rejected(self):
        with pytest.raises(SystemExit) as exc:
            main(["--definitely-not-a-flag"])
        assert exc.value.code != 0


class TestBuild:
    def test_builds_an_svg_next_to_the_source(self, panel_file: Path, capsys):
        assert main(["build", str(panel_file)]) == 0
        output = panel_file.with_name("scene.svg")
        assert output.exists()
        assert output.read_text(encoding="utf-8").startswith("<?xml")

    def test_panel_suffix_is_not_doubled(self, panel_file: Path, capsys):
        """`scene.panel.yaml` should yield `scene.svg`, not `scene.panel.svg`."""
        main(["build", str(panel_file)])
        assert not panel_file.with_name("scene.panel.svg").exists()
        assert panel_file.with_name("scene.svg").exists()

    def test_explicit_output_path_is_honoured(self, panel_file: Path, tmp_path: Path, capsys):
        target = tmp_path / "nested" / "out.svg"
        assert main(["build", str(panel_file), "-o", str(target)]) == 0
        assert target.exists()

    def test_core_flag_writes_the_intermediate_tier(self, panel_file: Path, tmp_path: Path, capsys):
        target = tmp_path / "out.svg"
        main(["build", str(panel_file), "-o", str(target), "--core"])
        core = tmp_path / "out.core.json"
        assert core.exists()
        assert '"format_version"' in core.read_text(encoding="utf-8")

    def test_debug_flag_writes_the_overlay(self, panel_file: Path, tmp_path: Path, capsys):
        target = tmp_path / "out.svg"
        main(["build", str(panel_file), "-o", str(target), "--debug"])
        assert (tmp_path / "out.debug.svg").exists()

    def test_live_text_switches_to_selectable_text(self, panel_file: Path, tmp_path: Path, capsys):
        outlined = tmp_path / "a.svg"
        live = tmp_path / "b.svg"
        main(["build", str(panel_file), "-o", str(outlined)])
        main(["build", str(panel_file), "-o", str(live), "--live-text"])
        assert "<text" not in outlined.read_text(encoding="utf-8")
        assert "<text" in live.read_text(encoding="utf-8")

    def test_quiet_suppresses_output(self, panel_file: Path, capsys):
        main(["build", str(panel_file), "--quiet"])
        assert capsys.readouterr().out == ""

    def test_notes_are_reported(self, tmp_path: Path, capsys):
        """A retreating camera changes the requested framing, so the user is told."""
        crowded = tmp_path / "crowd.panel.yaml"
        crowded.write_text(
            "camera: {shot: close_up}\ncast:\n"
            + "\n".join(f"  a{i}: {{reference: alice}}" for i in range(4)),
            encoding="utf-8",
        )
        main(["build", str(crowded)])
        assert "note:" in capsys.readouterr().out


class TestErrors:
    def test_missing_file_reports_cleanly(self, tmp_path: Path, capsys):
        assert main(["build", str(tmp_path / "nope.panel.yaml")]) == 2
        assert "no such file" in capsys.readouterr().err

    def test_invalid_panel_reports_without_a_traceback(self, tmp_path: Path, capsys):
        bad = tmp_path / "bad.panel.yaml"
        bad.write_text("cast:\n  a: {reference: alice}\nstaging:\n  - a left_of ghost\n", "utf-8")
        assert main(["build", str(bad)]) == 1
        error = capsys.readouterr().err
        assert error.startswith("scenet:")
        assert "ghost" in error
        assert "Traceback" not in error

    def test_unknown_character_is_reported_cleanly(self, tmp_path: Path, capsys):
        """Naming a character that does not exist is a user error, so it gets a
        message listing the available cast -- not a traceback."""
        bad = tmp_path / "bad.panel.yaml"
        bad.write_text("cast:\n  a: {reference: nobody}\n", encoding="utf-8")
        assert main(["build", str(bad)]) == 1
        error = capsys.readouterr().err
        assert "nobody" in error
        assert "alice" in error
        assert "Traceback" not in error

    def test_error_messages_are_not_wrapped_in_quotes(self, tmp_path: Path, capsys):
        """KeyError stringifies via repr, which would surface the message wrapped in
        quotes. Users should see prose."""
        bad = tmp_path / "bad.panel.yaml"
        bad.write_text("cast:\n  a: {reference: nobody}\n", encoding="utf-8")
        main(["build", str(bad)])
        assert capsys.readouterr().err.startswith("scenet: unknown character")
