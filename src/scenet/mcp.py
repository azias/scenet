"""An MCP server, so a model can check and render the panels it writes.

The spec pack tells a model what the language is; this lets it find out what it got
wrong. A model writes a document, calls `validate`, reads findings that each name a
rule, a line and a fix, corrects its own output and calls `render` -- with no human
copying error text between a terminal and a chat window. It is the only part of the
agent-facing surface that closes that loop.

Install it with the extra, and start it with the `scenet mcp` command:

    pip install 'scenet[mcp]'
    scenet mcp                             # stdio, for a local client
    scenet mcp --transport streamable-http # for a remote one

## The official SDK, and only as an extra

Built on the official [`mcp`](https://github.com/modelcontextprotocol/python-sdk)
package, which already speaks protocol revision 2026-07-28 -- the stateless core, the
extensions framework, cacheable list results -- and adds nothing FastMCP would have to
supply. It is an extra rather than a dependency because it brings an HTTP stack the
compiler has no use for: the browser playground installs the base wheel into Pyodide,
and someone who only wants `scenet build` should not have to put Starlette through
their own licence review.

Transports are stdio and Streamable HTTP. Not SSE: the protocol has deprecated it, and
Streamable HTTP replaced it.

## Five tools, shaped after compilers that are already served this way

[typst-mcp](https://github.com/johannesbrandenburger/typst-mcp) serves its
documentation one chapter at a time, checks a snippet, and renders one;
[d2-mcp](https://github.com/h0rv/d2-mcp) has a cheat sheet, `compile` to validate and
`render` to draw. The same shapes, rather than new ones:

- `get_spec` -- the spec pack, one part at a time, so a model need not read all of it
- `list_puppets` -- the characters it may cast, with their poses and expressions
- `validate` -- every finding at once, shaped rather than dumped as raw SARIF
- `compile` -- the Panel Core: where the compiler put everything, and why
- `render` -- the SVG, byte-identical to what `scenet build` writes

Each takes the document as **text**, not a path. A remote client shares no file
system with the server, and one calling convention for both transports is one less
thing to get wrong. Every tool is read-only and closed-world, and says so in its
annotations: nothing here writes a file or reaches the network.

## Keeping stdout clean

On stdio, stdout *is* the protocol stream, and one stray line corrupts it. That is why
nothing here goes through `cli.run_build`, which prints `wrote` and `note:` lines --
the easiest way there is to ship a broken stdio server. Notes travel in the tool
result instead. The SDK also points file descriptor 1 at stderr while it serves, which
catches a stray `print` from a dependency; the test suite drives a real stdio session
against the installed command to make sure neither ever matters.
"""

import inspect
import json
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import EmbeddedResource, TextContent, TextResourceContents, ToolAnnotations
from pydantic import BaseModel, Field

from scenet import __version__
from scenet.assets.contract import default_library
from scenet.diagnostics import RULE_NAMESPACE, RULES, Diagnostic, diagnose_script, diagnose_source
from scenet.emit.svg import render
from scenet.errors import ScenetError
from scenet.frontends.positions import DOCUMENT_START
from scenet.frontends.script_front import parse_script
from scenet.frontends.yaml_front import parse_scene
from scenet.pipeline import CompileResult, compile_ir
from scenet.spec_pack import part

__all__ = [
    "CompileReport",
    "CompiledPanel",
    "Finding",
    "Puppet",
    "PuppetCatalogue",
    "ValidationReport",
    "build_server",
    "compile_panel",
    "get_spec",
    "list_puppets",
    "render_panel",
    "serve",
    "validate",
]

#: The documentation site, which the server names as its website.
WEBSITE = "https://creatoan.github.io/scenet/"

#: What a client is told when it connects. Many hosts hand this straight to the model,
#: so it says what to do first rather than what the server is.
INSTRUCTIONS = """\
Scenet compiles a semantic description of a comic panel -- who is in it, how they \
relate, what they say -- into SVG, deterministically. There is no image model, and you \
never write coordinates: the compiler decides every one.

Before writing a document, call get_spec with no arguments for the essentials and the \
mistakes to avoid; call it with a section for the full language, the comic-script \
format or worked examples. list_puppets names the characters you can cast.

Then validate the document, fix every finding -- each names its rule, line and fix -- \
and validate again until it is clean. compile shows where everything was placed; \
render returns the SVG. Pass the document's text, not a path."""

#: Every tool here is a pure function of its arguments.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

#: The parts of the spec pack, as the tool schema offers them. Spelled out because a
#: `Literal` must be; `tests/test_mcp.py` checks it against `SPEC_PARTS`.
Section = Literal[
    "preamble",
    "language",
    "shot-types",
    "comic-script",
    "characters",
    "diagnostics",
    "schema",
    "gallery",
]

#: The two frontends. YAML covers both a single panel and a `panels:` sequence, which
#: the document itself distinguishes, so a caller never has to.
Syntax = Literal["yaml", "script"]

# Parameter descriptions live in the annotations rather than in an `Args:` section,
# because the annotation is what reaches the tool's input schema -- which is the only
# documentation a model calling the tool ever sees.
SourceArg = Annotated[
    str,
    Field(description="The whole document as text: a YAML panel or scene, or a comic script"),
]
SyntaxArg = Annotated[
    Syntax,
    Field(
        description=(
            "`yaml` for a *.panel.yaml or *.scene.yaml document, "
            "`script` for a *.script comic script"
        )
    ),
]


class Finding(BaseModel):
    """One thing wrong with a document: which rule, where, and what to do about it."""

    rule: str = Field(description="Stable rule id, such as `scenet/unknown-actor`")
    message: str = Field(description="What is wrong, naming the offending construct")
    fix: str = Field(description="What to do about it")
    where: str = Field(description="Path to the offending value, such as `script.0.by`")
    line: int = Field(description="1-based line the finding starts on")
    column: int = Field(description="1-based column the finding starts at")
    end_line: int
    end_column: int


class ValidationReport(BaseModel):
    """Everything wrong with a document, all at once."""

    valid: bool = Field(description="True when there are no findings")
    findings: list[Finding] = Field(description="In source order; fix all of them")


class CompiledPanel(BaseModel):
    """One compiled panel."""

    name: str = Field(description="`panel` for a single panel, else its name or number")
    notes: list[str] = Field(
        description="Decisions the compiler made that the source did not literally ask for"
    )
    core: dict[str, Any] = Field(
        description="The Panel Core: every resolved coordinate, as `scenet build --core` writes it"
    )


class CompileReport(BaseModel):
    """Every panel in a document, compiled."""

    panels: list[CompiledPanel] = Field(description="In reading order")


class Puppet(BaseModel):
    """A character a cast member's `reference` can name."""

    name: str
    heads_tall: float = Field(description="Height in head-heights; taller reads as older")
    poses: list[str] = Field(description="Every value `pose` may take for this puppet")
    expressions: list[str] = Field(description="Every value `expression` may take")


class PuppetCatalogue(BaseModel):
    """The puppet library."""

    puppets: list[Puppet]


def get_spec(
    section: Annotated[
        Section | None,
        Field(description="Which part to read. Omit it for the essentials and a list of parts"),
    ] = None,
) -> str:
    """Read the Scenet language specification, one part at a time.

    With no section: what Scenet is, the two ways to write a panel, the check-and-fix
    loop, the mistakes generators make most, and what every other part holds. Read it
    first. With a section: that part in full -- `language` for every construct,
    `comic-script` for the script format, `gallery` for worked examples that are known
    to compile.

    Returns:
        Markdown, exactly as it appears in the spec pack.
    """
    if section is None:
        preamble = part("preamble").rstrip("\n")
        return f"{preamble}\n\nCall get_spec with a section to read any of these.\n"
    return part(section)


def list_puppets() -> PuppetCatalogue:
    """List the characters a panel can cast, with every pose and expression each declares.

    A cast member's `reference` names one of these; its `pose` and `expression` must be
    names that puppet declares. Anything else fails validation.

    Returns:
        Every shipped puppet, by name, with its poses and expressions sorted.
    """
    library = default_library()
    puppets = []
    for name in library.names():
        puppet = library.get(name)
        puppets.append(
            Puppet(
                name=name,
                heads_tall=round(puppet.heads_tall, 1),
                poses=sorted(puppet.poses),
                expressions=sorted(puppet.expressions),
            )
        )
    return PuppetCatalogue(puppets=puppets)


def validate(
    source: SourceArg,
    syntax: SyntaxArg = "yaml",
    deep: Annotated[
        bool,
        Field(
            description=(
                "Also run the solver, to catch layout and balloon-placement failures the "
                "cheap check cannot see. Slower"
            )
        ),
    ] = False,
) -> ValidationReport:
    """Check a document and report everything wrong with it, without compiling it.

    Runs the checks `scenet check` runs: the language, every actor id resolving to a
    cast member, staging order that does not loop, and every puppet, pose and
    expression existing. These are the faults no JSON Schema can catch. Each finding
    names its rule, its line and column, and the fix. Fix them all and validate again.

    Returns:
        Whether the document is valid, and every finding in source order.
    """
    found = _diagnose(source, syntax, deep=deep)
    return ValidationReport(valid=not found, findings=[_finding(item) for item in found])


def compile_panel(source: SourceArg, syntax: SyntaxArg = "yaml") -> CompileReport:
    """Compile a document and return where the compiler put everything.

    The result is the Panel Core for each panel: every figure's position and scale,
    every balloon's box and tail. Its notes say what the compiler did that the source
    did not literally ask for -- a camera that pulled back so the cast would fit, a
    tail that bent around a face. A document that does not compile is an error
    carrying the same findings `validate` reports.

    Returns:
        Every panel, in reading order, with its notes and its Panel Core.

    Raises:
        ToolError: The document does not compile. The message lists every finding.
    """
    return CompileReport(
        panels=[
            CompiledPanel(
                name=name, notes=list(result.notes), core=json.loads(result.core.to_json())
            )
            for name, result in _compile(source, syntax).items()
        ]
    )


def render_panel(
    source: SourceArg,
    syntax: SyntaxArg = "yaml",
    live_text: Annotated[
        bool,
        Field(
            description=(
                "Emit selectable <text> rather than glyph outlines: about a third the size, "
                "but it depends on the viewer having a matching font"
            )
        ),
    ] = False,
) -> list[TextContent | EmbeddedResource]:
    """Compile a document and return each panel as SVG.

    The SVG is exactly what `scenet build` writes, one embedded `image/svg+xml`
    resource per panel, after a short text summary with the compiler's notes. A
    document that does not compile is an error carrying the same findings `validate`
    reports.

    Returns:
        A summary, then one SVG resource per panel in reading order.

    Raises:
        ToolError: The document does not compile. The message lists every finding.
    """
    results = _compile(source, syntax)
    count = f"{len(results)} panel{'' if len(results) == 1 else 's'}"
    lines = [f"Rendered {count}: {', '.join(results)}."]
    lines.extend(
        f"note ({name}): {note}" for name, result in results.items() for note in result.notes
    )
    # SVG goes out as an embedded resource and never as an image block. Hosts pass image
    # blocks to the model, and model APIs that accept images do not accept SVG -- so an
    # image block would fail the whole turn rather than show a picture.
    blocks: list[TextContent | EmbeddedResource] = [TextContent(type="text", text="\n".join(lines))]
    blocks.extend(
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri=f"scenet://panels/{name}.svg",
                mime_type="image/svg+xml",
                text=render(result.core, live_text=live_text),
            ),
        )
        for name, result in results.items()
    )
    return blocks


#: Tool name, title and function. `compile` is the name a client sees; the Python
#: function is `compile_panel`, so as not to shadow the builtin.
TOOLS: tuple[tuple[str, str, Callable[..., Any]], ...] = (
    ("get_spec", "Read the Scenet specification", get_spec),
    ("list_puppets", "List the characters", list_puppets),
    ("validate", "Check a panel document", validate),
    ("compile", "Compile a panel to Panel Core", compile_panel),
    ("render", "Render a panel to SVG", render_panel),
)


def build_server() -> MCPServer[Any]:
    """Build the server with every tool registered, without starting it.

    Separate from :func:`serve <scenet.mcp.serve>` so that a test, or a host embedding
    Scenet in a server of its own, can connect to it in process.

    Returns:
        The server, ready to run on any transport.
    """
    server: MCPServer[Any] = MCPServer(
        name="scenet",
        title="Scenet",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url=WEBSITE,
    )
    for name, title, function in TOOLS:
        server.tool(name=name, title=title, description=_describe(function), annotations=READ_ONLY)(
            function
        )
    return server


def serve(transport: Literal["stdio", "streamable-http"], **options: Any) -> None:  # noqa: ANN401
    """Run the server until the client disconnects.

    Args:
        transport: `stdio` for a local client that launches the server itself, or
            `streamable-http` to listen for remote ones.
        **options: Passed to the transport: `host` and `port` for Streamable HTTP.
    """
    build_server().run(transport, **options)


def _describe(function: Callable[..., Any]) -> str:
    """A tool's description: its docstring, up to the first Google-style section.

    `Returns:` and `Raises:` are for Python readers; the schema already says what comes
    back. Everything before them is written for the model.
    """
    doc = inspect.getdoc(function) or ""
    match = re.search(r"^(Args|Returns|Raises|Example|Examples):$", doc, re.MULTILINE)
    return (doc[: match.start()] if match else doc).strip()


def _diagnose(source: str, syntax: Syntax, *, deep: bool) -> list[Diagnostic]:
    if syntax == "script":
        return diagnose_script(source, deep=deep)
    return diagnose_source(source, deep=deep)


def _finding(item: Diagnostic) -> Finding:
    region = item.region or DOCUMENT_START
    return Finding(
        rule=f"{RULE_NAMESPACE}/{item.rule}",
        message=item.message,
        fix=RULES[item.rule].help,
        where=".".join(str(step) for step in item.path),
        line=region.start.line,
        column=region.start.column,
        end_line=region.end.line,
        end_column=region.end.column,
    )


def _compile(source: str, syntax: Syntax) -> dict[str, CompileResult]:
    """Compile every panel, or raise a tool error that lists every finding.

    The success path compiles once. Only a failure pays for the deep check, which is
    what turns "the solver gave up" into a located finding with a rule and a fix.
    """
    try:
        panels = parse_script(source) if syntax == "script" else parse_scene(source)
        library = default_library()
        return {name: compile_ir(panel, library=library) for name, panel in panels.items()}
    except ScenetError as exc:
        found = _diagnose(source, syntax, deep=True)
        if not found:
            # A clean deep check means a successful build -- the diagnostics tests hold
            # the two to that -- so this is a disagreement between them, and is reported
            # as one rather than hidden behind an empty list.
            raise ToolError(
                f"the document did not compile, but no rule explains why: {exc}"
            ) from exc
        raise ToolError(_report(found)) from exc


def _report(found: list[Diagnostic]) -> str:
    """Findings as text, for hosts that show a model only the text of an error."""
    count = f"{len(found)} problem{'' if len(found) == 1 else 's'}"
    entries = []
    for item in found:
        finding = _finding(item)
        where = f" at {finding.where}" if finding.where else ""
        entries.append(
            f"{finding.line}:{finding.column} {finding.rule}{where}\n"
            f"  {finding.message}\n"
            f"  fix: {finding.fix}"
        )
    return f"The document has {count}. Fix each, then validate again.\n\n" + "\n\n".join(entries)
