# API reference

Everything a user is allowed to depend on is named in `scenet.__all__` and imported
straight from the top level:

```python
from scenet import compile_source, render

result = compile_source("cast: {a: {reference: alice}}")
svg = render(result.core)
```

Names outside `__all__` are internal. They are still documented here — the decisions
inside the solver are the interesting part of this project — but their signatures are not
promised to survive a minor version.

## The public surface at a glance

| | Names |
|---|---|
| **Compiling** | `compile_source` · `compile_file` · `compile_scene` · `compile_scene_file` · `compile_document` · `compile_ir` · `CompileResult` |
| **Parsing only** | `parse_panel` · `parse_scene` · `parse_script` · `load_panel` · `load_scene` · `load_script` |
| **Rendering** | `render` · `render_debug` · `render_strip` |
| **Tiers** | `PanelIR` · `PanelCore` |
| **Describing a panel** | `PanelSpec` · `CameraSpec` · `CastMember` · `Relation` · `SayEvent` · `CaptionEvent` · `ShotType` · `CameraAngle` · `AnchorX` · `PlacementZone` · `Facing` · `Predicate` · `BalloonKind` · `CaptionKind` |
| **Describing a setting** | `SettingSpec` · `Mass` · `MassKind` · `Plane` · `Spans` · `Horizon` · `TimeOfDay` · `Weather` · `Place` · `PLACES` |
| **Characters** | `PuppetLibrary` · `PuppetSpec` · `Landmark` · `default_library` · `load_puppet` |
| **Errors** | `ScenetError` · `SourceError` · `SolverError` · `AssetError` · `PanelSyntaxError` · `ScriptSyntaxError` · `CompositionError` · `LayoutError` · `BalloonPlacementError` · `UnknownPuppetError` |

## Types

Scenet ships a `py.typed` marker, so mypy, pyright, ty and basedpyright read these
annotations directly from the installed package. No stubs to install, nothing to
configure.

## By module

```{toctree}
:maxdepth: 2

pipeline
ir
frontends
core
geom
assets
solve
emit
errors
cli
```
