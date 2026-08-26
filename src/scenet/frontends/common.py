"""Shared between the frontends.

Both syntaxes -- YAML documents and comic scripts -- produce the same
[`PanelIR`][scenet.ir.PanelIR], and both need the same two things on the way: a rewrite
of the surface conveniences into the IR's canonical shape, and a way to turn pydantic's
error list into a diagnostic a person can act on.

These lived in `yaml_front` and were imported into `script_front` through their private
names, which put a module's internals on another module's import line. Whichever
frontend came first would have owned them by accident. They belong here, where neither
does.
"""

import re
from typing import Any

from pydantic import ValidationError

from scenet.errors import PanelSyntaxError, RuleViolationError
from scenet.ir import Predicate, Relation

__all__ = ["normalise", "parse_relation", "summarise"]

# `alice left_of bob` -- subject, predicate, object, separated by whitespace.
RELATION_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s*$")

# Verbs a script entry may be tagged with. Single-key mappings rather than a
# discriminator field, so a new verb costs the author nothing to adopt and costs this
# table one line.
KNOWN_VERBS = frozenset({"say", "caption"})


def parse_relation(text: str) -> Relation:
    """Parse `subject predicate object` into a relation.

    Written as a sentence rather than a mapping because staging is read far more often
    than it is written, and `alice left_of bob` is legible at a glance in a way that a
    three-key mapping is not.

    Args:
        text: One staging entry.

    Returns:
        The validated relation.

    Raises:
        PanelSyntaxError: The entry is not three whitespace-separated words, names an
            unknown predicate, or relates an actor to itself.

    Example:
        >>> from scenet.frontends.common import parse_relation
        >>> relation = parse_relation("alice left_of bob")
        >>> relation.subject, relation.predicate.value, relation.object
        ('alice', 'left_of', 'bob')
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
        raise PanelSyntaxError(f"in staging entry {text!r}: {summarise(exc)}") from exc


def normalise(data: dict[str, Any]) -> dict[str, Any]:
    """Rewrite surface conveniences into the IR's canonical shape.

    Two shapes differ between the surface syntax and the IR: staging is written as
    sentences, and script entries are written as single-key mappings tagged by verb
    (`- say: {...}`, `- caption: {...}`) so that a new verb can be added without a
    discriminator field the author has to type. The tag is moved into the payload as
    `verb`, which is where the IR's event models expect to find it.

    Args:
        data: A parsed top-level panel mapping, in surface form.

    Returns:
        A new mapping in the shape `PanelIR` validates. The input is not modified.

    Raises:
        PanelSyntaxError: `staging` or `script` is not a list, a script entry is not a
            single-key mapping, or it names a verb that does not exist.
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
        events: list[Any] = []
        for index, entry in enumerate(raw):
            if not isinstance(entry, dict) or len(entry) != 1:
                raise PanelSyntaxError(
                    f"script entry {index} must be a single-key mapping such as "
                    f"'- say: {{by: alice, text: ...}}'"
                )
            verb, payload = next(iter(entry.items()))
            if verb not in KNOWN_VERBS:
                known = ", ".join(sorted(KNOWN_VERBS))
                raise PanelSyntaxError(
                    f"script entry {index}: unknown verb {verb!r}; known verbs are {known}"
                )
            if not isinstance(payload, dict):
                raise PanelSyntaxError(f"script entry {index}: {verb!r} expects a mapping")
            # The tag is injected rather than dropped. Now that a script holds more than
            # one sort of event, discarding it would leave the union to be resolved by
            # which model happens to accept the keys -- guesswork, on documents whose
            # whole point is being unambiguous.
            events.append({**payload, "verb": verb})
        result["script"] = events

    return result


def summarise(exc: ValidationError) -> str:
    """Flatten pydantic's error list into something a human can act on.

    pydantic's default rendering is accurate but verbose; for a language error the useful
    part is the location and the reason, one line each.

    Args:
        exc: The validation error pydantic raised.

    Returns:
        A multi-line diagnostic, one line per problem, each naming where it is.
    """
    lines: list[str] = []
    for error in exc.errors():
        # A model-level validator reports `loc=()` -- the whole document -- because
        # pydantic gives it no way to say which field it was unhappy about. The two
        # checks that matter most here knew the exact path all along, and a
        # `RuleViolationError` carries it through validation in `ctx["error"]`. Without this
        # every unresolved actor id and every ordering cycle reported `at <root>`.
        original = (error.get("ctx") or {}).get("error")
        loc = (
            original.loc
            if isinstance(original, RuleViolationError) and original.loc
            else error["loc"]
        )
        location = ".".join(str(part) for part in loc) or "<root>"
        # pydantic prefixes messages raised by custom validators with "Value error, ",
        # which is noise to somebody reading a language diagnostic.
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  at {location}: {message}")
    return "invalid panel:\n" + "\n".join(lines)
