# Reference

Facts, tables and signatures. Nothing here teaches — for that, start with the
[tutorial](../tutorial/index) or a [how-to guide](../howto/index).

## The language

| | |
|---|---|
| [Language specification](language.md) | Every construct in the DSL, with examples |
| [Shot types](shot_types.md) | **Normative.** What each shot type means, in head-heights |
| [Panel Core](panel_core.md) | The resolved intermediate format |
| [Asset contract](asset_contract.md) | What a character puppet must declare |

The language specification is what a second implementation would target. It is free to
implement: the project is 0BSD, and to be explicit, anyone may build a competing compiler,
editor or renderer for this language without permission or attribution. A notation is only
worth having if it is not owned.

## The tools

| | |
|---|---|
| [Command line](cli.md) | Every command and flag |
| [Python API](api/index.md) | Every public name, and the internals behind them |

## Version and status

The table of what actually runs, as opposed to what is specified, is in
[implementation status](../explanation/status.md). The specification describes the
language; the status table is authoritative about the compiler.

```{toctree}
:hidden:
:maxdepth: 2

language
shot_types
panel_core
asset_contract
cli
api/index
```
