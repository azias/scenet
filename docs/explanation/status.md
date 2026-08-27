# Implementation status

| Document | Contents |
|---|---|
| [Language specification](../reference/language.md) | The DSL — every construct, with examples |
| [Panel Core](../reference/panel_core.md) | The resolved intermediate format |
| [Shot types](../reference/shot_types.md) | Normative camera framing table |
| [Asset contract](../reference/asset_contract.md) | What a character puppet must declare |

**This specification is free to implement.** The project is released under
[0BSD](https://github.com/azias/scenet/blob/main/LICENSE), which imposes no conditions whatsoever — but to be explicit: anyone may
build a competing compiler, editor, renderer or tool for this language without permission or
attribution. A notation is only worth having if it is not owned.

## Implementation status

| Phase | Scope | State |
|---|---|---|
| 0 | Toolchain, CI, specification, project scaffolding | **Done** |
| 1 | IR, Panel Core schema, YAML frontend, puppets and forward kinematics | **Done** |
| 2 | Camera scale resolution and actor placement (Cassowary) | **Done** |
| 3 | Text metrics, balloon placement, reading order, tails | **Done** |
| 4 | SVG emitter, debug overlay and CLI | **Done** |
| 5 | Comic-script frontend; multi-panel `over` inheritance | **Done** |
| 6 | Browser playground (Pyodide); VS Code extension | **Done** |
| 7 | Machine-readable diagnostics: `scenet check`, in SARIF | **Done** |
| 8 | Captions, faces, and the setting layer — places, masses, planes, atmosphere | **Done** |

Single panels compile end to end. Constructs described in `language.md` are the specification,
not a report of what is implemented — the table above is authoritative on what actually runs.

## Planned

Each of these is scoped to be a release on its own. The order is deliberately not fixed, and the
dependency between them is stated in the tickets rather than implied by this table.

| Scope | Ticket |
|---|---|
| Emanata — the marks that are not on the face | [#21](https://github.com/azias/scenet/issues/21) |
| Tinted caption boxes | [#28](https://github.com/azias/scenet/issues/28) |
| The agent-facing surface — spec pack, skill, MCP server | [#11](https://github.com/azias/scenet/issues/11) |

Still further out, and not yet ticketed: page composition (tiers, panels of varying size) and the
interpretation layer that would give a panel a *style*.
