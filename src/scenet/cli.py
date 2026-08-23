"""Command-line entry point."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scenet import __version__
from scenet.emit.debug_svg import render_debug
from scenet.emit.strip import render_strip
from scenet.emit.svg import render
from scenet.errors import ScenetError
from scenet.ir import PanelIR
from scenet.pipeline import compile_document

DESCRIPTION = "Compile a semantic comic-panel description into SVG."

EPILOGUE = """\
Scenet is a deterministic compiler: the same source always produces byte-identical
output. No generative image model is involved at any stage.

See docs/reference/language.md for the language.
"""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the `scenet` command.

    Exposed separately from :func:`main <scenet.cli.main>` so that tests, shell-completion
    generators and documentation tooling can inspect the interface without running it.

    Returns:
        A parser with the `build` and `schema` subcommands defined.
    """
    parser = argparse.ArgumentParser(
        prog="scenet",
        description=DESCRIPTION,
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"scenet {__version__}")

    subcommands = parser.add_subparsers(dest="command")
    build = subcommands.add_parser("build", help="compile a panel source to SVG")
    build.add_argument(
        "source",
        type=Path,
        help="a *.panel.yaml or *.scene.yaml document, or a *.script comic script",
    )
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
    build.add_argument(
        "--strip",
        action="store_true",
        help="for a multi-panel document, also lay the panels out as a strip",
    )
    build.add_argument("--quiet", action="store_true", help="suppress diagnostic notes")

    schema = subcommands.add_parser(
        "schema",
        help="print the JSON Schema for a panel document",
        description=(
            "Emit the JSON Schema describing a panel, derived from the same models the "
            "compiler validates against. Editors use it for completion and inline "
            "validation, so what the editor suggests cannot drift from what compiles."
        ),
    )
    schema.add_argument("-o", "--output", type=Path, help="write to a file instead of stdout")
    schema.add_argument(
        "--scene",
        action="store_true",
        help="emit the multi-panel scene schema instead of the single-panel one",
    )
    return parser


def run_build(args: argparse.Namespace) -> int:
    """Run the `build` subcommand: compile a document and write its outputs.

    Args:
        args: Parsed arguments from :func:`build_parser <scenet.cli.build_parser>`.

    Returns:
        A process exit status: `0` on success, `1` when the document could not be
        compiled, `2` when the source file does not exist.

    Every error the compiler can raise inherits `ScenetError`, and all of them mean
    "your panel cannot be compiled" rather than "scenet broke" -- so they are reported
    as a plain one-line message rather than a traceback.
    """
    source: Path = args.source
    if not source.exists():
        print(f"scenet: no such file: {source}", file=sys.stderr)
        return 2

    try:
        results = compile_document(source)
    except ScenetError as exc:
        # Every ScenetError is "your panel cannot be compiled" rather than "scenet
        # broke", so they all get a plain message instead of a traceback.
        #
        # KeyError stringifies as repr(args[0]), which wraps the message in whichever
        # quote style avoids escaping -- so a message containing an apostrophe comes
        # out double-quoted. Reading args[0] directly sidesteps that entirely.
        message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
        print(f"scenet: {message}", file=sys.stderr)
        return 1

    # `foo.panel.yaml` becomes `foo.svg`, not `foo.panel.svg`.
    stem = (
        source.name.removesuffix(".yaml")
        .removesuffix(".script")
        .removesuffix(".panel")
        .removesuffix(".scene")
    )
    base: Path = args.output or source.with_name(f"{stem}.svg")
    base.parent.mkdir(parents=True, exist_ok=True)

    single = len(results) == 1 and "panel" in results
    written: list[Path] = []
    notes: list[str] = []

    for name, result in results.items():
        # A single-panel document writes to the requested name; a sequence suffixes
        # each panel with its own name, so the mapping back to source is obvious.
        target = base if single else base.with_name(f"{base.stem}.{name}{base.suffix}")
        target.write_text(render(result.core, live_text=args.live_text), encoding="utf-8")
        written.append(target)

        if args.core:
            core_path = target.with_suffix(".core.json")
            core_path.write_text(result.core.to_json(), encoding="utf-8")
            written.append(core_path)
        if args.debug:
            debug_path = target.with_name(f"{target.stem}.debug.svg")
            debug_path.write_text(render_debug(result.core), encoding="utf-8")
            written.append(debug_path)
        notes.extend(f"{name}: {note}" if not single else note for note in result.notes)

    if args.strip and not single:
        strip_path = base.with_name(f"{base.stem}.strip.svg")
        strip_path.write_text(
            render_strip(
                [(name, result.core) for name, result in results.items()],
                live_text=args.live_text,
            ),
            encoding="utf-8",
        )
        written.append(strip_path)

    if not args.quiet:
        for path in written:
            print(f"wrote {path}")
        for note in notes:
            print(f"note: {note}")
    return 0


def scene_schema() -> dict[str, Any]:
    """The schema for a multi-panel document.

    Built from the panel schema rather than declared separately, so the two can never
    describe different languages. A scene allows the same keys as a panel -- there they
    act as defaults every panel inherits -- plus `panels`, whose members may
    additionally carry `over`.
    """
    panel = PanelIR.model_json_schema()
    definitions = panel.pop("$defs", {})
    properties = panel.get("properties", {})

    member = {key: value for key, value in panel.items() if key != "title"}
    member["properties"] = {
        **properties,
        "over": {
            "type": "string",
            "description": (
                "Name of a panel to inherit from. Only the differences need stating: "
                "mappings merge recursively and lists replace."
            ),
        },
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Scenet scene",
        "$defs": definitions,
        "type": "object",
        "properties": {
            **properties,
            "panels": {
                "type": "object",
                "description": (
                    "Panels in reading order. Each may inherit from another with `over`."
                ),
                "additionalProperties": member,
            },
        },
        "additionalProperties": False,
    }


def run_schema(args: argparse.Namespace) -> int:
    """Emit the panel JSON Schema.

    Generated from the pydantic models rather than hand-written, so editor completion
    is derived from the compiler's own definition of the language and the two cannot
    disagree.
    """
    schema = scene_schema() if args.scene else PanelIR.model_json_schema()
    document = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(document, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the `scenet` command.

    Args:
        argv: Arguments to parse. Defaults to `sys.argv[1:]`, which is what happens
            when the installed console script runs; pass a list explicitly from tests.

    Returns:
        A process exit status. `0` on success, `1` for a document that will not
        compile, `2` for a usage error or a missing file.

    Example:
        >>> from scenet.cli import main
        >>> main(["--definitely-not-a-flag"])
        Traceback (most recent call last):
          ...
        SystemExit: 2
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        return run_build(args)
    if args.command == "schema":
        return run_schema(args)
    # No subcommand. Help goes to stderr and the status is 2, matching the convention
    # argparse itself uses for a usage error -- a bare `scenet` did not do anything,
    # and a script that runs it should not read that as success.
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
