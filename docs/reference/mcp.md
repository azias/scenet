# MCP server

`scenet mcp` serves the compiler over the [Model Context Protocol](https://modelcontextprotocol.io/),
targeting revision [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28). It is
the one way of driving Scenet from a model that closes the loop: the model writes a document,
validates it, reads findings that name the rule, the line and the fix, corrects its own output,
and renders it — with no person copying error text from a terminal into a chat window.

Starting it, transports and exit status are in the [command-line reference](cli.md#scenet-mcp);
connecting a client is in [driving Scenet from a model](../howto/drive_from_a_model.md). This
page is the tools.

## Tools

Five, deliberately. Each extra tool is more for a model to read before it can choose one.

| Tool | Takes | Returns |
|---|---|---|
| `get_spec` | `section` (optional) | The spec pack, one part at a time, as Markdown |
| `list_puppets` | — | Every character, with each pose and expression it declares |
| `validate` | `source`, `syntax`, `deep` | `{valid, findings}`, every finding at once |
| `compile` | `source`, `syntax` | Each panel's notes and [Panel Core](panel_core.md) |
| `render` | `source`, `syntax`, `live_text` | A summary, then one SVG per panel |

Every tool is annotated **read-only, idempotent and closed-world**: none writes a file, reaches
the network, or answers differently on a second call. A client can run them without asking.

### Arguments

`source`
: The whole document, **as text**. Not a path: a remote client shares no file system with the
  server, and one calling convention for both transports is one less thing to get wrong.

`syntax`
: `yaml` (default) for a `*.panel.yaml` or `*.scene.yaml` document — a top-level `panels:` key
  is what makes it a scene, so there is no third value — or `script` for a comic script.

`section`
: One of `preamble`, `language`, `shot-types`, `comic-script`, `characters`, `diagnostics`,
  `schema`, `gallery`. Omitted, `get_spec` returns the preamble — what Scenet is, the
  check-and-fix loop, the mistakes generators make most — and a list of the other parts.

`deep`
: Also run the solver, as `scenet check --deep` does, to catch `layout` and
  `balloon-placement` failures the cheap pass cannot see.

`live_text`
: Emit selectable `<text>` instead of glyph outlines, as `scenet build --live-text` does. About
  a third the size, which matters inside a model's context, but it depends on the viewer having
  a matching font.

### Findings

`validate` returns every finding, in source order:

| Field | |
|---|---|
| `rule` | Stable rule id, such as `scenet/unknown-actor` — the [same catalogue](cli.md#rules) `scenet check` reports |
| `message` | What is wrong, naming the offending construct |
| `fix` | What to do about it |
| `where` | Path to the offending value, such as `script.0.by`; empty for the whole document |
| `line`, `column`, `end_line`, `end_column` | 1-based |

`compile` and `render` refuse a document that does not compile with a **tool error**, whose
text lists the same findings with the same fixes. A solver failure is located as well as a
syntax one: only a failure pays for the deep check that locates it, so a document that compiles
is compiled once.

The findings travel in two forms: as structured content for clients that read it, and as text
for the many hosts that show a model only a result's text.

### Rendering

`render` returns a short text summary — how many panels, and the compiler's notes — then one
embedded resource per panel, `scenet://panels/NAME.svg`, of type `image/svg+xml`. The SVG is
**byte-identical** to what `scenet build` writes for the same document.

It is never sent as an image content block. Hosts forward image blocks to the model, and model
APIs that accept images do not accept SVG, so an image block would fail the whole turn instead
of showing a picture. There is no PNG either: rasterising would put a renderer in the runtime
dependencies for one tool.

## Instructions

On connecting, the server sends instructions that many hosts hand straight to the model. They
say what to do rather than what the server is: read `get_spec` first, cast only what
`list_puppets` lists, validate until clean, and pass text rather than paths.

## Keeping stdout clean

On the stdio transport, stdout *is* the protocol stream, and one stray line corrupts it. Nothing
in the server goes through the code `scenet build` uses to print `wrote` and `note:` lines; the
compiler's notes travel inside tool results instead. The SDK additionally points file descriptor
1 at stderr while it serves, which catches a stray `print` from a dependency. The test suite
drives a real stdio session against the installed command, so neither can regress quietly.

## From Python

The tools are plain functions, importable without starting a server:

```python
from scenet.mcp import list_puppets, validate

report = validate("""
cast:
  alice: {reference: alice}
script:
  - say: {by: bpb, text: Hello}
""")

assert not report.valid
finding = report.findings[0]
assert finding.rule == "scenet/unknown-actor"
assert finding.where == "script.0.by"
assert (finding.line, finding.column) == (5, 5)

assert [puppet.name for puppet in list_puppets().puppets] == ["alice", "bob"]
```

`build_server()` returns the configured server without running it, for a host that wants to
connect in process or mount it inside a server of its own.

## Publishing

[`server.json`](https://github.com/creatoan/scenet/blob/main/server.json) at the repository root
describes the server for the [official MCP registry](https://github.com/modelcontextprotocol/registry),
which holds metadata only and points at the package on PyPI. Ownership of the
`io.github.creatoan/scenet` namespace is proved by the `mcp-name` marker in the README, which
becomes the PyPI project description. Publishing is a maintainer step; see
[releasing](../maintainer/releasing.md).
