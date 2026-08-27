"""Scenet -- a semantic DSL for comic panels, compiled to SVG.

You describe *what is in the panel* -- who is present, how they are framed, who says
what -- and the compiler works out the rest: how large each figure must be for the
requested shot, where each stands, how big each balloon needs to be for its text, where
a balloon can sit without covering a face, and how its tail reaches the speaker's mouth.

**No generative image model is involved at any stage.** This is a deterministic
compiler built from constraint solving and computational geometry: the same source
always produces byte-identical output, which is what makes golden-file testing
meaningful and what lets you diff two versions of a page.

Compiling one panel, end to end:

    >>> from scenet import compile_source, render
    >>> source = '''
    ... panel:
    ...   size: [1000, 800]
    ... camera:
    ...   shot: medium_shot
    ... cast:
    ...   alice: {reference: alice, at: left_third}
    ...   bob:   {reference: bob,   at: right_third, facing: left}
    ... staging:
    ...   - alice left_of bob
    ... script:
    ...   - say: {by: alice, text: "You forgot your umbrella!"}
    ... '''
    >>> result = compile_source(source)
    >>> len(result.core.actors), len(result.core.balloons)
    (2, 1)
    >>> svg = render(result.core)
    >>> svg.splitlines()[1][:4]
    '<svg'

Three tiers, and all three are yours to use:

| Tier | Type | What it is |
|---|---|---|
| Source | `str` / file | What an author writes -- YAML or comic script |
| IR | :class:`PanelIR <scenet.ir.PanelIR>` | Validated scene graph. No coordinates yet |
| Panel Core | :class:`PanelCore <scenet.core.PanelCore>` | Resolved, numeric, still named |

Panel Core is a real, writable format rather than a hidden data structure, so a layout
can be inspected, hand-adjusted and diffed independently of how it is drawn. Reach for
:func:`compile_source <scenet.pipeline.compile_source>` when you want a picture, and for
:class:`PanelCore <scenet.core.PanelCore>` when you want to know *why* the picture looks like
that.

Names not listed in `__all__` are internal and may change without notice.
"""

from importlib.metadata import PackageNotFoundError, version

from scenet.assets.contract import (
    Landmark,
    PuppetLibrary,
    PuppetSpec,
    default_library,
    load_puppet,
)
from scenet.core import PanelCore
from scenet.emit.debug_svg import render_debug
from scenet.emit.strip import render_strip
from scenet.emit.svg import render
from scenet.errors import (
    AssetError,
    BalloonPlacementError,
    CompositionError,
    LayoutError,
    PanelSyntaxError,
    ScenetError,
    ScriptSyntaxError,
    SolverError,
    SourceError,
    UnknownPuppetError,
)
from scenet.frontends.script_front import load_script, parse_script
from scenet.frontends.yaml_front import load_panel, load_scene, parse_panel, parse_scene
from scenet.ir import (
    AnchorX,
    BalloonKind,
    CameraAngle,
    CameraSpec,
    CaptionEvent,
    CaptionKind,
    CaptionTone,
    CastMember,
    Facing,
    Horizon,
    Mass,
    MassKind,
    PanelIR,
    PanelSpec,
    PlacementZone,
    Plane,
    Predicate,
    Relation,
    SayEvent,
    SettingSpec,
    ShotType,
    Spans,
    TimeOfDay,
    Weather,
)
from scenet.pipeline import (
    CompileResult,
    compile_document,
    compile_file,
    compile_ir,
    compile_scene,
    compile_scene_file,
    compile_source,
)
from scenet.places import PLACES, Place

try:
    __version__: str = version("scenet")
except PackageNotFoundError:  # pragma: no cover -- only when running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = [
    # -- compiling -----------------------------------------------------------
    "CompileResult",
    "compile_document",
    "compile_file",
    "compile_ir",
    "compile_scene",
    "compile_scene_file",
    "compile_source",
    # -- parsing, without compiling ------------------------------------------
    "load_panel",
    "load_scene",
    "load_script",
    "parse_panel",
    "parse_scene",
    "parse_script",
    # -- rendering -----------------------------------------------------------
    "render",
    "render_debug",
    "render_strip",
    # -- the intermediate tiers ----------------------------------------------
    "PanelCore",
    "PanelIR",
    # -- describing a panel --------------------------------------------------
    "AnchorX",
    "BalloonKind",
    "CameraAngle",
    "CameraSpec",
    "CaptionEvent",
    "CaptionKind",
    "CaptionTone",
    "CastMember",
    "Facing",
    "PanelSpec",
    "PlacementZone",
    "Predicate",
    "Relation",
    "SayEvent",
    "ShotType",
    # -- describing where and when it happens --------------------------------
    "PLACES",
    "Horizon",
    "Mass",
    "MassKind",
    "Place",
    "Plane",
    "SettingSpec",
    "Spans",
    "TimeOfDay",
    "Weather",
    # -- puppets -------------------------------------------------------------
    "Landmark",
    "PuppetLibrary",
    "PuppetSpec",
    "default_library",
    "load_puppet",
    # -- errors --------------------------------------------------------------
    "AssetError",
    "BalloonPlacementError",
    "CompositionError",
    "LayoutError",
    "PanelSyntaxError",
    "ScenetError",
    "ScriptSyntaxError",
    "SolverError",
    "SourceError",
    "UnknownPuppetError",
    # -- metadata ------------------------------------------------------------
    "__version__",
]
