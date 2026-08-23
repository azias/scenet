"""The CLI is thin, but these lock in that the package imports and the entry point runs."""

import pytest

from scenet import __version__
from scenet.cli import build_parser, main


def test_version_is_populated():
    assert __version__
    assert __version__ != "0.0.0+unknown", "package metadata should be installed"


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_main_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: scenet" in out
    assert "pre-alpha" in out


def test_unknown_argument_is_rejected():
    with pytest.raises(SystemExit) as exc:
        main(["--definitely-not-a-flag"])
    assert exc.value.code != 0
