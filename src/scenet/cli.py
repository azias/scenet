"""Command-line entry point."""

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from scenet import __version__
from scenet.diagnostics import Diagnostic, diagnose_file, to_sarif
from scenet.emit.debug_svg import render_debug
from scenet.emit.strip import render_strip
from scenet.emit.svg import render
from scenet.errors import ScenetError
from scenet.pipeline import FRONTENDS, compile_document
from scenet.schema import panel_schema, scene_schema

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
        A parser with the `build`, `check`, `schema` and `mcp` subcommands defined.
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

    check = subcommands.add_parser(
        "check",
        help="validate documents without compiling them",
        description=(
            "Report everything wrong with one or more documents, and exit non-zero if "
            "anything is. Nothing is written unless you ask for it.\n\n"
            "The default output is the same prose the compiler prints. `--format sarif` "
            "emits SARIF 2.1.0, which GitHub code scanning ingests directly and which "
            "editors and agents can consume -- the checks that matter most here, such as "
            "an actor id that does not resolve to a cast member, cannot be expressed in "
            "the published JSON Schema, so this is the only machine-readable form of "
            "them."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    check.add_argument(
        "sources",
        type=Path,
        nargs="+",
        help="documents to check; several may be given, and all are reported together",
    )
    check.add_argument(
        "--format",
        choices=("text", "sarif"),
        default="text",
        dest="format",
        help="text for people (default), sarif for everything else",
    )
    check.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write the report to a file instead of stdout",
    )
    check.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the per-file success line; findings are always reported",
    )
    check.add_argument(
        "--deep",
        action="store_true",
        help=(
            "also run the full compiler on documents that pass every cheap check, to "
            "additionally catch layout and balloon-placement failures; costs a real "
            "compile, including font metrics, so off by default"
        ),
    )

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

    mcp = subcommands.add_parser(
        "mcp",
        help="serve the compiler to a model over the Model Context Protocol",
        description=(
            "Run an MCP server whose tools read the specification, list the characters, "
            "validate, compile and render -- so a model can check its own panel and fix "
            "what it got wrong, with nobody relaying error text. Needs the optional "
            "extra: pip install 'scenet[mcp]'.\n\n"
            "stdio is for a client that launches the server itself; streamable-http "
            "listens for remote clients, and has no authentication, so it binds to "
            "localhost unless told otherwise."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mcp.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="stdio (default) or streamable-http",
    )
    mcp.add_argument(
        "--host", default="127.0.0.1", help="address to listen on, for streamable-http"
    )
    mcp.add_argument("--port", type=int, default=8000, help="port, for streamable-http")
    return parser


def _refuse_unsupported(paths: Sequence[Path]) -> bool:
    """Report every path no frontend reads, and say whether there were any.

    `build` dispatches on the extension, so a file it has no frontend for is a mistake in
    the invocation rather than in a panel -- the same class as a missing file, and
    reported the same way rather than escaping as a traceback.
    """
    expected = ", ".join(sorted(FRONTENDS))
    refused = [path for path in paths if path.suffix.lower() not in FRONTENDS]
    for path in refused:
        print(
            f"scenet: {path}: unsupported extension '{path.suffix}'; expected one of {expected}",
            file=sys.stderr,
        )
    return bool(refused)


def run_build(args: argparse.Namespace) -> int:
    """Run the `build` subcommand: compile a document and write its outputs.

    Args:
        args: Parsed arguments from :func:`build_parser <scenet.cli.build_parser>`.

    Returns:
        A process exit status: `0` on success, `1` when the document could not be
        compiled, `2` when the source file does not exist or has an extension no
        frontend reads.

    Every error the compiler can raise inherits `ScenetError`, and all of them mean
    "your panel cannot be compiled" rather than "scenet broke" -- so they are reported
    as a plain one-line message rather than a traceback.
    """
    source: Path = args.source
    if not source.exists():
        print(f"scenet: no such file: {source}", file=sys.stderr)
        return 2
    if _refuse_unsupported([source]):
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
        .removesuffix(".yml")
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


def run_check(args: argparse.Namespace) -> int:
    """Run the `check` subcommand: validate documents and report what is wrong.

    Args:
        args: Parsed arguments from :func:`build_parser <scenet.cli.build_parser>`.

    Returns:
        A process exit status: `0` when every document is valid, `1` when any has a
        finding, `2` when a file does not exist or has an extension no frontend reads.

    Unlike `build`, this never stops at the first fault. pydantic reports every field
    error at once and a run over several files reports all of them, because a caller
    fixing them -- a person or an agent -- wants the whole list, not one round trip per
    mistake.
    """
    sources: list[Path] = args.sources
    missing = [path for path in sources if not path.exists()]
    for path in missing:
        print(f"scenet: no such file: {path}", file=sys.stderr)
    if missing:
        return 2
    # Checked as `build` would read it, or not at all: calling a file `build` refuses
    # "ok" would be a confident false clean.
    if _refuse_unsupported(sources):
        return 2

    found: list[Diagnostic] = []
    for path in sources:
        found.extend(diagnose_file(path, deep=args.deep))

    if args.format == "sarif":
        # Relative to the working directory, which is the repository root under CI and
        # is what code scanning matches results against.
        document = to_sarif(found, root=Path.cwd())
        # A trailing newline because this is a text file people will `cat`, and JSON
        # without one is a nuisance in a terminal and in a diff.
        report = f"{json.dumps(document, indent=2, ensure_ascii=False)}\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            if not args.quiet:
                print(f"wrote {args.output}")
        else:
            # stdout carries the document and nothing else, so that
            # `scenet check --format sarif x > results.sarif` produces a parseable file.
            sys.stdout.write(report)
        return 1 if found else 0

    for item in found:
        where = item.source if item.source else "<string>"
        line = item.region.start.line if item.region else 1
        column = item.region.start.column if item.region else 1
        print(f"{where}:{line}:{column}: {item.rule}: {item.message}", file=sys.stderr)

    if not found and not args.quiet:
        for path in sources:
            print(f"{path}: ok")
    return 1 if found else 0


def run_schema(args: argparse.Namespace) -> int:
    """Emit the panel JSON Schema.

    Generated from the pydantic models rather than hand-written, so editor completion
    is derived from the compiler's own definition of the language and the two cannot
    disagree. It describes the syntax as written, not the IR it normalises into; see
    :mod:`scenet.schema <scenet.schema>`.
    """
    schema = scene_schema() if args.scene else panel_schema()
    document = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(document, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(f"wrote {args.output}")
    return 0


def run_mcp(args: argparse.Namespace) -> int:
    """Run the `mcp` subcommand: serve the tools until the client disconnects.

    Args:
        args: Parsed arguments from :func:`build_parser <scenet.cli.build_parser>`.

    Returns:
        A process exit status: `0` once the client has gone, `2` when the optional `mcp`
        dependency is not installed.

    Nothing is printed to stdout, before or after: on the stdio transport stdout is the
    protocol stream. The server module is imported here rather than at the top of the
    file, so every other command works without the extra installed.
    """
    try:
        server = importlib.import_module("scenet.mcp")
    except ImportError as exc:
        # Only a missing `mcp` package means a missing extra. Anything else is a real
        # fault inside Scenet, and dressing it up as an installation hint would hide it.
        if not (exc.name or "").partition(".")[0] == "mcp":
            raise
        print(
            "scenet: the MCP server needs the optional 'mcp' dependency: pip install 'scenet[mcp]'",
            file=sys.stderr,
        )
        return 2

    if args.transport == "stdio":
        server.serve("stdio")
    else:
        server.serve("streamable-http", host=args.host, port=args.port)
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
    if args.command == "check":
        return run_check(args)
    if args.command == "schema":
        return run_schema(args)
    if args.command == "mcp":
        return run_mcp(args)
    # No subcommand. Help goes to stderr and the status is 2, matching the convention
    # argparse itself uses for a usage error -- a bare `scenet` did not do anything,
    # and a script that runs it should not read that as success.
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
