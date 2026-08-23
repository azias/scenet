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

from scenet.ir import PanelIR, Predicate, Relation

# `alice left_of bob` -- subject, predicate, object, separated by whitespace.
RELATION_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s*$")


class PanelSyntaxError(ValueError):
    """A panel source that could not be understood.

    Distinct from pydantic's ValidationError so a caller can tell a malformed
    document from a well-formed but invalid one, and report each usefully.
    """

    def __init__(self, message: str, *, source: Path | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


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


def parse_panel(text: str, *, source: Path | None = None) -> PanelIR:
    """Parse panel source into validated IR."""
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

    try:
        return PanelIR.model_validate(_normalise(data))
    except PanelSyntaxError as exc:
        raise PanelSyntaxError(str(exc), source=source) from exc
    except ValidationError as exc:
        raise PanelSyntaxError(_summarise(exc), source=source) from exc


def load_panel(path: Path) -> PanelIR:
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
