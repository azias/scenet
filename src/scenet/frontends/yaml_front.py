"""The YAML surface syntax: text in, validated IR out.

This is one frontend among several planned -- a comic-script frontend will target the
same IR. Keeping parsing separate from the IR is what makes that possible without
touching anything downstream.
"""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scenet.compose import merge, resolve_overrides
from scenet.errors import CompositionError, PanelSyntaxError
from scenet.ir import PanelIR, Predicate, Relation

# `alice left_of bob` -- subject, predicate, object, separated by whitespace.
RELATION_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s*$")


def parse_relation(text: str) -> Relation:
    """Parse `subject predicate object` into a relation.

    Written as a sentence rather than a mapping because staging is read far more
    often than it is written, and `alice left_of bob` is legible at a glance in a way
    that a three-key mapping is not.
    """
    match = RELATION_RE.match(text)
    if not match:
        raise PanelSyntaxError(
            f"staging entry {text!r} is not of the form 'subject predicate object'"
        )
    subject, predicate_text, obj = match.groups()
    try:
        predicate = Predicate(predicate_text)
    except ValueError as exc:
        known = ", ".join(sorted(member.value for member in Predicate))
        raise PanelSyntaxError(
            f"in staging entry {text!r}: unknown predicate {predicate_text!r}; "
            f"known predicates are {known}"
        ) from exc
    try:
        return Relation(subject=subject, predicate=predicate, object=obj)
    except ValidationError as exc:
        raise PanelSyntaxError(f"in staging entry {text!r}: {_summarise(exc)}") from exc


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Rewrite surface conveniences into the IR's canonical shape.

    Two shapes differ between the surface syntax and the IR: staging is written as
    sentences, and script entries are written as single-key mappings tagged by verb
    (`- say: {...}`) so that future verbs can be added without a discriminator field
    the author has to type.
    """
    result = dict(data)

    if "staging" in result:
        raw = result["staging"]
        if not isinstance(raw, list):
            raise PanelSyntaxError("'staging' must be a list of relation sentences")
        result["staging"] = [
            parse_relation(entry) if isinstance(entry, str) else entry for entry in raw
        ]

    if "script" in result:
        raw = result["script"]
        if not isinstance(raw, list):
            raise PanelSyntaxError("'script' must be a list of narrative events")
        events = []
        for index, entry in enumerate(raw):
            if not isinstance(entry, dict) or len(entry) != 1:
                raise PanelSyntaxError(
                    f"script entry {index} must be a single-key mapping such as "
                    f"'- say: {{by: alice, text: ...}}'"
                )
            verb, payload = next(iter(entry.items()))
            if verb != "say":
                raise PanelSyntaxError(
                    f"script entry {index}: unknown verb {verb!r}; only 'say' is defined"
                )
            if not isinstance(payload, dict):
                raise PanelSyntaxError(f"script entry {index}: 'say' expects a mapping")
            events.append(payload)
        result["script"] = events

    return result


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
        return PanelIR.model_validate(_normalise(data))
    except PanelSyntaxError as exc:
        raise PanelSyntaxError(str(exc), source=source) from exc
    except ValidationError as exc:
        raise PanelSyntaxError(_summarise(exc), source=source) from exc


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


def _summarise(exc: ValidationError) -> str:
    """Flatten pydantic's error list into something a human can act on.

    pydantic's default rendering is accurate but verbose; for a language error the
    useful part is the location and the reason, one line each.
    """
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        # pydantic prefixes messages raised by custom validators with "Value error, ",
        # which is noise to someone reading a language diagnostic.
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  at {location}: {message}")
    return "invalid panel:\n" + "\n".join(lines)


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
