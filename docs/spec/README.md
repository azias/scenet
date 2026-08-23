# Specification

| Document | Contents |
|---|---|
| [language.md](language.md) | The DSL — every construct, with examples |
| [panel_core.md](panel_core.md) | The resolved intermediate format |
| [shot_types.md](shot_types.md) | Normative camera framing table |
| [asset_contract.md](asset_contract.md) | What a character puppet must declare |

**This specification is free to implement.** The project is released under
[0BSD](../../LICENSE), which imposes no conditions whatsoever — but to be explicit: anyone may
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

Single panels compile end to end. Constructs described in `language.md` are the specification,
not a report of what is implemented — the table above is authoritative on what actually runs.
