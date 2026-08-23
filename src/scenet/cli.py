"""Command-line entry point."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scenet import __version__
from scenet.assets.contract import UnknownPuppetError
from scenet.emit.debug_svg import render_debug
from scenet.emit.svg import render
from scenet.frontends.yaml_front import PanelSyntaxError
from scenet.pipeline import compile_file
from scenet.solve.balloons import BalloonPlacementError
from scenet.solve.staging import LayoutError

DESCRIPTION = "Compile a semantic comic-panel description into SVG."

EPILOGUE = """\
Scenet is a deterministic compiler: the same source always produces byte-identical
output. No generative image model is involved at any stage.

See docs/spec/language.md for the language.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenet",
        description=DESCRIPTION,
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"scenet {__version__}")

    subcommands = parser.add_subparsers(dest="command")
    build = subcommands.add_parser("build", help="compile a panel source to SVG")
    build.add_argument("source", type=Path, help="a *.panel.yaml file")
    build.add_argument(
        "-o", "--output", type=Path, help="output SVG path (default: alongside the source)"
    )
    build.add_argument(
        "--core",
        action="store_true",
        help="also write the resolved Panel Core JSON, the inspectable intermediate tier",
    )
    build.add_argument(
        "--debug",
        action="store_true",
        help="also write a diagnostic overlay showing hulls, face zones, anchors and gaze",
    )
    build.add_argument(
        "--live-text",
        action="store_true",
        help=(
            "emit selectable <text> instead of glyph outlines; smaller, but depends on the "
            "reader having a metrically compatible font installed"
        ),
    )
    build.add_argument("--quiet", action="store_true", help="suppress diagnostic notes")
    return parser


def run_build(args: argparse.Namespace) -> int:
    source: Path = args.source
    if not source.exists():
        print(f"scenet: no such file: {source}", file=sys.stderr)
        return 2

    try:
        result = compile_file(source)
    except (PanelSyntaxError, LayoutError, BalloonPlacementError, UnknownPuppetError) as exc:
        # These are all "your panel cannot be compiled" rather than "scenet broke", so
        # they get a plain message instead of a traceback.
        #
        # KeyError stringifies as repr(args[0]), which wraps the message in whichever
        # quote style avoids escaping -- so a message containing an apostrophe comes
        # out double-quoted. Reading args[0] directly sidesteps that entirely.
        message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        print(f"scenet: {message}", file=sys.stderr)
        return 1

    # `foo.panel.yaml` becomes `foo.svg`, not `foo.panel.svg`.
    stem = source.name.removesuffix(".yaml").removesuffix(".panel")
    output: Path = args.output or source.with_name(f"{stem}.svg")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(result.core, live_text=args.live_text), encoding="utf-8")
    written = [output]

    if args.core:
        core_path = output.with_suffix(".core.json")
        core_path.write_text(result.core.to_json(), encoding="utf-8")
        written.append(core_path)

    if args.debug:
        debug_path = output.with_name(f"{output.stem}.debug.svg")
        debug_path.write_text(render_debug(result.core), encoding="utf-8")
        written.append(debug_path)

    if not args.quiet:
        for path in written:
            print(f"wrote {path}")
        for note in result.notes:
            print(f"note: {note}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        return run_build(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
