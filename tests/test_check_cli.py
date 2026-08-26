"""`scenet check` -- the machine-readable half of the compiler's diagnostics.

The prose output is what a person reads. SARIF is what CI, an editor and an agent read.
Both come out of this one command, and the exit status has to mean the same thing in
either mode.
"""

import json
from pathlib import Path

import pytest

from scenet.cli import main

VALID = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice, at: left_third}
  bob:   {reference: bob,   at: right_third}
staging:
  - alice left_of bob
script:
  - say: {by: alice, text: "Hello there."}
"""

UNKNOWN_ACTOR = """\
panel: {size: [420, 560]}
cast:
  alice: {reference: alice}
script:
  - say: {by: bpb, text: Hello}
"""


@pytest.fixture
def good(tmp_path: Path) -> Path:
    path = tmp_path / "good.panel.yaml"
    path.write_text(VALID, encoding="utf-8")
    return path


@pytest.fixture
def bad(tmp_path: Path) -> Path:
    path = tmp_path / "bad.panel.yaml"
    path.write_text(UNKNOWN_ACTOR, encoding="utf-8")
    return path


class TestExitStatus:
    """CI keys off this, so it matters more than what is printed."""

    def test_a_valid_document_exits_zero(self, good: Path):
        assert main(["check", str(good)]) == 0

    def test_an_invalid_document_exits_one(self, bad: Path):
        assert main(["check", str(bad)]) == 1

    def test_a_missing_file_exits_two(self, tmp_path: Path):
        """Distinct from 'the panel is wrong': the invocation is wrong."""
        assert main(["check", str(tmp_path / "nope.panel.yaml")]) == 2

    def test_one_bad_file_among_several_still_fails(self, good: Path, bad: Path):
        assert main(["check", str(good), str(bad)]) == 1

    def test_sarif_output_uses_the_same_status(self, bad: Path):
        assert main(["check", "--format", "sarif", str(bad)]) == 1


class TestProseOutput:
    """The default. Unchanged in spirit from what `build` already printed."""

    def test_it_reports_the_fault_on_stderr(self, bad: Path, capsys: pytest.CaptureFixture[str]):
        main(["check", str(bad)])
        assert "bpb" in capsys.readouterr().err

    def test_it_names_the_file_and_position(self, bad: Path, capsys: pytest.CaptureFixture[str]):
        main(["check", str(bad)])
        err = capsys.readouterr().err
        assert "bad.panel.yaml" in err
        assert ":5:" in err, "the speaker is on line 5"

    def test_a_clean_check_says_so(self, good: Path, capsys: pytest.CaptureFixture[str]):
        main(["check", str(good)])
        assert "good.panel.yaml" in capsys.readouterr().out

    def test_quiet_suppresses_the_success_line(
        self, good: Path, capsys: pytest.CaptureFixture[str]
    ):
        main(["check", "--quiet", str(good)])
        assert capsys.readouterr().out == ""

    def test_quiet_does_not_suppress_findings(self, bad: Path, capsys: pytest.CaptureFixture[str]):
        """`--quiet` hides the reassurance, never the diagnosis."""
        main(["check", "--quiet", str(bad)])
        assert "bpb" in capsys.readouterr().err


class TestSarifOutput:
    def test_it_writes_a_sarif_document_to_stdout(
        self, bad: Path, capsys: pytest.CaptureFixture[str]
    ):
        main(["check", "--format", "sarif", str(bad)])
        document = json.loads(capsys.readouterr().out)
        assert document["version"] == "2.1.0"

    def test_a_clean_run_still_emits_a_document(
        self, good: Path, capsys: pytest.CaptureFixture[str]
    ):
        """A consumer needs the run to know the tool passed. An empty file would be
        indistinguishable from a check that never ran."""
        main(["check", "--format", "sarif", str(good)])
        document = json.loads(capsys.readouterr().out)
        assert document["runs"][0]["results"] == []

    def test_findings_from_several_files_share_one_run(
        self, good: Path, bad: Path, capsys: pytest.CaptureFixture[str]
    ):
        main(["check", "--format", "sarif", str(good), str(bad)])
        document = json.loads(capsys.readouterr().out)
        assert len(document["runs"]) == 1

    def test_nothing_but_json_reaches_stdout(self, bad: Path, capsys: pytest.CaptureFixture[str]):
        """`scenet check --format sarif file > results.sarif` has to produce a file a
        parser accepts, so no note, warning or progress line may share stdout."""
        main(["check", "--format", "sarif", str(bad)])
        captured = capsys.readouterr()
        json.loads(captured.out)
        assert not captured.out.startswith("wrote")

    def test_the_output_file_option_writes_instead_of_printing(self, bad: Path, tmp_path: Path):
        target = tmp_path / "results.sarif"
        main(["check", "--format", "sarif", "-o", str(target), str(bad)])
        document = json.loads(target.read_text(encoding="utf-8"))
        assert document["runs"][0]["results"]

    def test_paths_are_relative_to_the_working_directory(
        self,
        bad: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """Code scanning matches results to files by relative path, and the project
        forbids absolute paths in output anyway."""
        monkeypatch.chdir(tmp_path)
        main(["check", "--format", "sarif", "bad.panel.yaml"])
        document = json.loads(capsys.readouterr().out)
        uri = document["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        assert uri == "bad.panel.yaml"


class TestItChecksRatherThanBuilds:
    def test_it_writes_no_svg(self, good: Path, tmp_path: Path):
        main(["check", str(good)])
        assert list(tmp_path.glob("*.svg")) == []

    def test_a_syntax_error_is_a_finding_not_a_crash(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        path = tmp_path / "broken.panel.yaml"
        path.write_text("panel: [unclosed\n", encoding="utf-8")
        assert main(["check", "--format", "sarif", str(path)]) == 1
        document = json.loads(capsys.readouterr().out)
        assert document["runs"][0]["results"][0]["ruleId"] == "scenet/syntax"


class TestDeterminism:
    def test_the_same_input_produces_the_same_bytes(
        self, bad: Path, capsys: pytest.CaptureFixture[str]
    ):
        main(["check", "--format", "sarif", str(bad)])
        first = capsys.readouterr().out
        main(["check", "--format", "sarif", str(bad)])
        second = capsys.readouterr().out
        assert first == second


class TestComicScripts:
    """The other frontend. Line-oriented, so positions are lines and nothing finer."""

    SCRIPT = """\
---
cast:
  ALICE: {reference: alice}
---

PANEL 1
ALICE
Hello there.
"""

    def test_a_valid_script_passes(self, tmp_path: Path):
        path = tmp_path / "good.script"
        path.write_text(self.SCRIPT, encoding="utf-8")
        assert main(["check", str(path)]) == 0

    def test_a_broken_script_is_reported_with_its_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        path = tmp_path / "bad.script"
        # Content before the first PANEL heading, which the parser rejects by line.
        path.write_text("stray prose\n\nPANEL 1\n", encoding="utf-8")
        assert main(["check", str(path)]) == 1
        assert ":1:" in capsys.readouterr().err

    def test_it_produces_sarif_like_any_other_document(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        path = tmp_path / "bad.script"
        path.write_text("stray prose\n\nPANEL 1\n", encoding="utf-8")
        main(["check", "--format", "sarif", str(path)])
        document = json.loads(capsys.readouterr().out)
        region = document["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 1
