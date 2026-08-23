"""The YAML surface syntax: text in, validated IR out.

This is one frontend among several planned -- a comic-script frontend will target the
same IR. Keeping parsing separate from the IR is what makes that possible without
touching anything downstream.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scenet.compose import merge, resolve_overrides
from scenet.errors import CompositionError, PanelSyntaxError
from scenet.frontends.common import normalise, summarise
from scenet.ir import PanelIR


def _load_document(text: str, source: Path | None) -> dict[str, Any]:
    """Read YAML text and check it is a mapping, or raise a language diagnostic.

    Args:
        text: The document source.
        source: Path it came from, used only to prefix error messages.

    Returns:
        The parsed top-level mapping.

    Raises:
        PanelSyntaxError: The text is not valid YAML, is empty, or is not a mapping.
    """
    try:
        # safe_load, never load: panel sources are untrusted input and full YAML can
        # construct arbitrary Python objects.
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PanelSyntaxError(f"invalid YAML: {exc}", source=source) from exc

    if data is None:
        raise PanelSyntaxError("panel source is empty", source=source)
    if not isinstance(data, dict):
        raise PanelSyntaxError(
            f"expected a mapping at the top level, found {type(data).__name__}", source=source
        )
    return data


def _validate_panel(data: dict[str, Any], source: Path | None) -> PanelIR:
    """Normalise a parsed mapping and validate it into IR.

    Args:
        data: A parsed top-level panel mapping.
        source: Path it came from, used only to prefix error messages.

    Returns:
        The validated scene graph.

    Raises:
        PanelSyntaxError: The document is well-formed YAML but not a valid panel.
    """
    try:
        return PanelIR.model_validate(normalise(data))
    except PanelSyntaxError as exc:
        raise PanelSyntaxError(str(exc), source=source) from exc
    except ValidationError as exc:
        raise PanelSyntaxError(summarise(exc), source=source) from exc


def parse_panel(text: str, *, source: Path | None = None) -> PanelIR:
    """Parse panel source into validated IR."""
    return _validate_panel(_load_document(text, source), source)


def load_panel(path: Path) -> PanelIR:
    """Read and validate a single-panel document from disk.

    Args:
        path: A `*.panel.yaml` file.

    Returns:
        The validated scene graph. No coordinates yet -- that is the solver's job.

    Raises:
        OSError: The file cannot be read.
        PanelSyntaxError: The document is malformed or invalid. The path is included in
            the message.
    """
    return parse_panel(path.read_text(encoding="utf-8"), source=path)


def parse_scene(text: str, *, source: Path | None = None) -> dict[str, PanelIR]:
    """Parse a multi-panel document, resolving `over` inheritance.

    A document with a top-level `panels:` mapping holds a sequence; anything else is
    treated as a single panel named "panel", so the two forms share one entry point
    and a single-panel file needs no ceremony.

    Panel order follows declaration order, which is reading order.
    """
    data = _load_document(text, source)

    if "panels" not in data:
        # A document with no `panels:` key is a single panel. Validated from the mapping
        # already in hand rather than by handing the text back to parse_panel, which
        # would run the YAML parser over it a second time.
        return {"panel": _validate_panel(data, source)}

    panels = data["panels"]
    if not isinstance(panels, dict):
        raise PanelSyntaxError("'panels' must be a mapping of name to panel", source=source)
    for name, document in panels.items():
        if not isinstance(document, dict):
            raise PanelSyntaxError(f"panel '{name}' must be a mapping", source=source)

    # Anything alongside `panels` is a default every panel inherits, which saves
    # restating the panel size and camera on each one.
    defaults = {key: value for key, value in data.items() if key != "panels"}

    try:
        composed = resolve_overrides(panels)
    except CompositionError as exc:
        # Re-raised rather than converted: a caller that wants to distinguish an
        # unresolvable `over:` chain from a syntax error can only do so if the type
        # survives. Both are SourceError, so a caller that does not care is unaffected.
        raise CompositionError(str(exc), source=source) from exc

    result: dict[str, PanelIR] = {}
    for name, document in composed.items():
        merged = merge(defaults, document) if defaults else document
        try:
            result[name] = _validate_panel(merged, None)
        except PanelSyntaxError as exc:
            raise PanelSyntaxError(f"in panel '{name}': {exc}", source=source) from exc
    return result


def load_scene(path: Path) -> dict[str, PanelIR]:
    """Read and validate a multi-panel document from disk.

    Args:
        path: A `*.scene.yaml` file. A single-panel document also works and comes back
            as one entry named `panel`.

    Returns:
        Panel name to scene graph, in declaration order -- which is reading order.

    Raises:
        OSError: The file cannot be read.
        PanelSyntaxError: A panel is malformed or invalid.
        CompositionError: An `over:` chain is unresolvable or cyclic.
    """
    return parse_scene(path.read_text(encoding="utf-8"), source=path)
