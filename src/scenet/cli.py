"""Command-line entry point."""

import argparse
import sys
from collections.abc import Sequence

from scenet import __version__

DESCRIPTION = "Compile a semantic comic-panel description into SVG."

EPILOGUE = """\
Scenet is pre-alpha: the compiler is not implemented yet, so no build command is
offered. Exposing one that always failed would be worse than not having it.

See docs/spec/language.md for the language, and the README for current status.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenet",
        description=DESCRIPTION,
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"scenet {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # With no subcommands yet, invoking bare `scenet` should explain itself rather
    # than exit silently with success as if it had done something.
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
