# Get completion and validation in your editor

Panel documents are YAML, and Scenet publishes a JSON Schema for them. Any editor with a
YAML language server can therefore offer completion, hover documentation and inline
validation — with no Scenet-specific plugin at all.

The schema is **generated from the compiler's own pydantic models**, so what your editor
suggests cannot drift from what actually compiles. A test fails if the shipped copy goes
stale.

## Any editor, via a schema comment

Put this on the first line of a panel document:

```yaml
# yaml-language-server: $schema=https://azias.github.io/scenet/schemas/panel.schema.json
panel:
  size: [1000, 800]
cast:
  alice: {reference: alice}
```

For a multi-panel document use `scene.schema.json` instead.

That comment is understood by the YAML language server used by VS Code, Neovim, Helix,
Emacs (lsp-mode), IntelliJ and Zed, among others. You get:

- Completion on every key, and on every enum value — all ten shot types, all four balloon
  kinds, all nine placement zones.
- **Hover documentation**, because the docstrings on the models become `description`
  fields in the schema. Hovering `shot:` explains that it is an upper bound on tightness,
  not a promise.
- Inline errors for unknown keys, wrong types and out-of-range values, as you type.

## The VS Code extension

A small extension bundles the same schemas plus a side-by-side preview:

1. Download `scenet.vsix` from the
   [latest release](https://github.com/azias/scenet/releases/latest).
2. In VS Code: **Extensions** → **⋯** → **Install from VSIX…**

It contributes:

- Schema association for `*.panel.yaml` and `*.scene.yaml`, so no `$schema` comment is
  needed.
- Syntax highlighting for `.script` comic scripts.
- **Scenet: Preview panel**, which compiles the current document and shows the SVG beside
  it.

The preview shells out to the `scenet` command, so it needs the compiler installed. If it
is not on your PATH, set `scenet.executable` — `uv run scenet` works, as does an absolute
path.

It depends on the Red Hat YAML extension, which VS Code will offer to install for you.

## Generating the schema yourself

```bash
scenet schema -o panel.schema.json
scenet schema --scene -o scene.schema.json
```

Both go to stdout without `-o`. This is the same command CI runs, and the same one that
produces the copies shipped in the extension.

From Python:

```python
import json

from scenet import PanelIR

schema = PanelIR.model_json_schema()

assert schema["$defs"]["ShotType"]["enum"][0] == "long_shot"

# The docstrings travel with it -- which is where the hover text comes from.
assert "upper bound" in schema["$defs"]["ShotType"]["description"]

document = json.dumps(schema, indent=2, sort_keys=True)
```

## Why it is generated and not written

A hand-written schema is a second definition of the language, and second definitions
drift. Within a release or two the editor is suggesting a key the compiler rejects, or
failing to suggest one it accepts, and nobody notices because nothing checks.

Here there is one definition — the pydantic models — and the schema is a projection of it.
The prose in the models is the prose in your editor's hover. The enum in the models is the
enum in your completion list. Adding a construct to the language updates both by
construction.
