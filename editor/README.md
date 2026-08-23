# VS Code extension

Authoring support for Scenet documents: completion, inline validation, and a preview.

## Why there is no language server

Completion and validation come from the JSON Schemas in `schemas/`, which are
**generated from the compiler's own pydantic models** by `scenet schema`. Writing a
language server by hand would mean maintaining a second description of the language,
which drifts from the first the moment anybody adds a keyword. Deriving it means what
the editor suggests is what compiles, by construction.

A test in `tests/test_schema.py` fails if the shipped schemas fall behind the models,
so a stale schema cannot ship.

Preview shells out to `scenet build` rather than reimplementing the pipeline — the same
refusal to fork the compiler.

## Building

```bash
npm ci
npm run schemas   # regenerate from the models
npm run build
```

Press F5 in VS Code to launch an Extension Development Host.

## Requirements

`redhat.vscode-yaml` provides the YAML language service the schema contributions hook
into, and is declared as an extension dependency. The `scenet` command must be on PATH,
or set `scenet.executable` (for example to `uv run scenet`).
