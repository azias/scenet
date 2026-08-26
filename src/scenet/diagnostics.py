"""Machine-readable diagnostics, in SARIF.

A compiler failure is prose on stderr. That is right for a person and useless for
anything else: CI cannot annotate a pull request with it, an editor cannot draw a
squiggle under it, and an agent repairing its own output cannot tell which of five
things went wrong.

**This matters more here than the published JSON Schema does.** The checks that catch
what a generator actually gets wrong are `model_validator`s in
:mod:`scenet.ir <scenet.ir>` -- every actor id resolving to a cast member, the
`left_of`/`right_of` graph being acyclic -- and neither is expressible in JSON Schema at
all. Structured diagnostics are what make a generate/validate/repair loop work, whether
the thing doing the repairing is a person pasting an error back into a chat window or a
tool call.

## Why SARIF

[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) is an
OASIS standard. GCC emits it under `-fdiagnostics-format=sarif`, MSVC and Clang emit it,
and GitHub code scanning ingests it directly. A bespoke `{"errors": [...]}` shape would
be one nobody else can read.

**2.1.0, not 2.2.** 2.2 is still a draft, and 2.1.0 documents are forward-consumable by
2.2 processors, so there is nothing to gain by chasing it.

**Hand-built, not `sarif-python-om`.** The document is one run, one driver and a handful
of results; the object model would be a runtime dependency and a licence-gate entry to
build a few nested dicts. `cli.py` already assembles JSON Schema by hand for the same
reason. If the emitted subset grows past a page of code, revisit it.

## Determinism

Byte-identical output for identical input is a project non-negotiable, and it reaches
this module: results come back in source order, rules are emitted sorted by id, and
`partialFingerprints` are content-derived rather than positional -- so a finding keeps
its identity when a comment is added above it, and an alert is not re-raised as new on
every unrelated edit.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from scenet import __version__
from scenet.assets.contract import PuppetLibrary, default_library
from scenet.compose import merge, resolve_overrides
from scenet.errors import (
    BalloonPlacementError,
    CompositionError,
    LayoutError,
    PanelSyntaxError,
    RuleViolationError,
    ScenetError,
    ScriptSyntaxError,
    UnknownExpressionError,
    UnknownPoseError,
    UnknownPuppetError,
)
from scenet.frontends.common import normalise
from scenet.frontends.positions import (
    DOCUMENT_START,
    Position,
    Region,
    locate,
    syntax_error_region,
)
from scenet.frontends.script_front import parse_script
from scenet.ir import PanelIR
from scenet.pipeline import compile_ir

__all__ = [
    "RULES",
    "Diagnostic",
    "Position",
    "Region",
    "Rule",
    "diagnose_file",
    "diagnose_source",
    "to_sarif",
]

#: Where the tool describes itself, for the SARIF driver block.
INFORMATION_URI = "https://github.com/azias/scenet"

#: Prefix on every emitted `ruleId`. Namespacing keeps Scenet's rules distinct from
#: those of every other tool whose results land in the same code-scanning database.
RULE_NAMESPACE = "scenet"

#: The fingerprint scheme's name and version. Versioned because changing how a
#: fingerprint is computed re-raises every existing alert as new, so the day that
#: becomes necessary it should at least be visible in the output.
FINGERPRINT_KEY = "scenetDiagnostic/v1"


@dataclass(frozen=True, slots=True)
class Rule:
    """One thing a document can be wrong about.

    GitHub requires `id`, `shortDescription`, `fullDescription` and `help` on every rule,
    and rejects empty strings for them, so all four are mandatory here too.

    Attributes:
        summary: One line, shown as the alert title.
        description: What the rule checks and why it exists.
        help: What to do about it.
    """

    summary: str
    description: str
    help: str


#: Every rule Scenet can report, keyed by its bare identifier.
#:
#: These identifiers are **stable across releases**. A `ruleId` that changes silently
#: closes every alert that referenced the old one and opens a duplicate under the new
#: one, so renaming one is a breaking change even though nothing stops compiling.
RULES: dict[str, Rule] = {
    "syntax": Rule(
        summary="The document is not valid YAML",
        description=(
            "The file could not be parsed at all, so nothing further could be checked. "
            "Usually an unclosed bracket or quote, or a line indented inconsistently "
            "with the ones around it."
        ),
        help="Fix the reported position; YAML errors cascade, so re-check after each fix.",
    ),
    "not-a-mapping": Rule(
        summary="The document is not a mapping",
        description=(
            "A panel document is a mapping of top-level keys -- panel, camera, cast, "
            "staging, script. A list or a bare scalar cannot be one."
        ),
        help="Wrap the content in top-level keys, or check you meant to compile this file.",
    ),
    "unknown-key": Rule(
        summary="Unknown key",
        description=(
            "Validation is strict everywhere: unknown keys are rejected rather than "
            "ignored. A misspelled key that was silently dropped would produce a panel "
            "that is subtly wrong with no indication of why, which for a language meant "
            "to be precise is the worst possible failure."
        ),
        help="Check the spelling against docs/reference/language.md.",
    ),
    "missing-field": Rule(
        summary="A required field is missing",
        description="The value is required and was not supplied.",
        help="Add the field. `scenet schema` prints the full shape the compiler accepts.",
    ),
    "invalid-field": Rule(
        summary="A field has the wrong shape or value",
        description=(
            "The key is known but what it holds is not what the language accepts there "
            "-- a string where a number belongs, or a value outside the allowed set."
        ),
        help="Check the field's type and permitted values in docs/reference/language.md.",
    ),
    "panel-geometry": Rule(
        summary="The panel has no usable area",
        description=(
            "Panel dimensions must be positive, and the margins must leave something "
            "between them. A panel with no interior has nothing to compose in."
        ),
        help="Give the panel a positive size, and a margin smaller than half its shorter side.",
    ),
    "unknown-actor": Rule(
        summary="Reference to an actor that is not in the cast",
        description=(
            "Every actor id named in `staging` or `script` must exist in `cast`. This is "
            "the check no JSON Schema can perform -- the value is a perfectly good "
            "string, it just does not resolve -- and it is among the most common faults "
            "in generated documents."
        ),
        help="Correct the id, or add the actor to `cast`. The message lists the cast.",
    ),
    "reflexive-relation": Rule(
        summary="A relation relates an actor to itself",
        description=(
            "No predicate in the language means anything reflexively, so an actor "
            "placed left of itself is always a typo for a second actor's id."
        ),
        help="Name a different actor as the object of the relation.",
    ),
    "ordering-cycle": Rule(
        summary="Horizontal ordering contains a cycle",
        description=(
            "`left_of` and `right_of` are resolved into a linear order before the "
            "solver runs, because Cassowary is a linear solver and cannot express the "
            "disjunction 'A left of B or B left of A'. A cycle has no linear order and "
            "so no solution."
        ),
        help="Remove one of the relations in the cycle; the message names an actor on it.",
    ),
    "composition": Rule(
        summary="An `over:` chain cannot be resolved",
        description=(
            "A panel inherits from one that does not exist, or the chain is cyclic and "
            "so has no fixed point to resolve to."
        ),
        help="Check the panel name in `over:` and that the chain terminates.",
    ),
    "unknown-puppet": Rule(
        summary="Reference to a character the library does not contain",
        description="A cast member's `reference` names a puppet that is not installed.",
        help="Check the name against the shipped library, or supply your own.",
    ),
    "unknown-pose": Rule(
        summary="Reference to a pose the character does not have",
        description=(
            "A cast member's `pose` names one its puppet does not declare. The key is "
            "spelled correctly -- `pose` is a real field -- but the value does not "
            "resolve to anything the referenced character can do."
        ),
        help="Check the name against the puppet's declared poses.",
    ),
    "unknown-expression": Rule(
        summary="Reference to an expression the character does not have",
        description=(
            "A cast member's `expression` names one its puppet does not declare. The "
            "counterpart of `unknown-pose`: an expression is selected by name exactly "
            "as a pose is."
        ),
        help="Check the name against the puppet's declared expressions.",
    ),
    "layout": Rule(
        summary="No layout satisfies the panel's constraints",
        description=(
            "Nothing is misspelled and nothing is missing, but the panel as described "
            "has no solution -- most often two actors each required to be left of the "
            "other. Panel bounds are deliberately not required, so a merely crowded "
            "panel is not this."
        ),
        help="Relax or remove a conflicting staging relation.",
    ),
    "balloon-placement": Rule(
        summary="A balloon or caption has no legal position",
        description=(
            "Every candidate position covered a face, left the panel, overlapped a "
            "box already placed, or would have broken reading order."
        ),
        help="Widen the panel, shorten the line, or split it across two panels.",
    ),
    "internal": Rule(
        summary="The compiler failed in a way it does not have a rule for",
        description=(
            "A Scenet error reached the checker without a more specific rule. Worth "
            "reporting: either the document found something genuinely new, or a rule "
            "is missing from the catalogue."
        ),
        help="Please open an issue with the document that produced it.",
    ),
}

#: pydantic error types that deserve their own rule. Everything else that pydantic
#: raises at field level is reported as `invalid-field`, which is honest: the catalogue
#: should not grow a rule per validator in a library this project does not own.
_PYDANTIC_RULES = {
    "missing": "missing-field",
    "extra_forbidden": "unknown-key",
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding: what is wrong, which rule it breaks, and where.

    Attributes:
        rule: Key into :data:`RULES <scenet.diagnostics.RULES>`.
        message: The same text the prose diagnostic shows, so the two renderings of a
            finding cannot drift apart.
        path: Location within the document, in pydantic's `loc` form. Structural rather
            than positional, which is what lets a fingerprint survive an edit above it.
        source: File the finding is in, or `None` for a string compiled in memory.
        region: Where in the text it is, if that could be determined.
    """

    rule: str
    message: str
    path: tuple[str | int, ...] = ()
    source: Path | None = None
    region: Region | None = field(default=None, compare=False)

    def fingerprint(self) -> str:
        """A stable identity for this finding, for `partialFingerprints`.

        Deliberately **not** derived from the line number. A fingerprint that moves when
        a comment is added at the top of the file turns one long-standing alert into a
        new alert on every edit, which is precisely what `partialFingerprints` exists to
        prevent. The path is structural, so it survives the finding moving down the file
        but still distinguishes the same fault in two different places.

        Returns:
            A hex digest, stable across runs, platforms and releases.
        """
        parts = [
            self.rule,
            ".".join(str(step) for step in self.path),
            self.message,
            _uri_for(self.source, root=None) if self.source else "",
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:32]


def _uri_for(source: Path | None, *, root: Path | None) -> str:
    """A relative, forward-slashed URI for a source file.

    Absolute paths are forbidden in Scenet's output -- they break determinism and, here,
    they also break code scanning's matching of a result to a file in the repository.

    Args:
        source: The file, or `None` for in-memory text.
        root: Directory to make the path relative to, usually the working directory.

    Returns:
        A relative POSIX-style path.
    """
    if source is None:
        return "<string>"
    path = source
    if root is not None:
        try:
            path = source.resolve().relative_to(root.resolve())
        except ValueError:
            # Outside the root -- fall back to the bare name rather than leaking an
            # absolute path into the document.
            path = Path(source.name)
    return PurePosixPath(*path.parts).as_posix() if path.parts else source.name


def _rule_for_pydantic(error: ErrorDetails) -> tuple[str, tuple[str | int, ...]]:
    """Decide which rule a pydantic error belongs to, and where it points.

    A `RuleViolationError` raised inside a validator survives in `ctx["error"]`, carrying the
    rule it broke and the path it knew about -- which is the only way a model-level
    validator can report anything more precise than "the document".
    """
    original = (error.get("ctx") or {}).get("error")
    if isinstance(original, RuleViolationError):
        return original.rule, original.loc or tuple(error["loc"])

    kind = str(error["type"])
    return _PYDANTIC_RULES.get(kind, "invalid-field"), tuple(error["loc"])


def _from_validation_error(
    exc: ValidationError,
    text: str,
    source: Path | None,
    *,
    prefix: tuple[str | int, ...] = (),
) -> list[Diagnostic]:
    """Turn pydantic's error list into findings, one per error.

    `prefix` places the finding within the whole document: pydantic validates one panel
    and reports paths relative to it, but a panel inside a `panels:` sequence needs its
    own name in front of that, or every finding in a scene points at the top level.
    """
    found: list[Diagnostic] = []
    for error in exc.errors():
        rule, path = _rule_for_pydantic(error)
        path = prefix + path
        # pydantic prefixes messages from custom validators with "Value error, ", which
        # is noise in a language diagnostic.
        message = str(error["msg"]).removeprefix("Value error, ")
        found.append(
            Diagnostic(
                rule=rule,
                message=message,
                path=path,
                source=source,
                region=locate(text, path) or DOCUMENT_START,
            )
        )
    return found


# Checked in order, first match wins. A tuple rather than an if/elif chain: the
# chain grew a branch per error type until it tripped the "too many returns" lint,
# and a new asset-lookup error (this module has already grown two more than the
# original three) is now one row here rather than another branch there.
_RULE_FOR_ERROR_TYPE: tuple[tuple[type[ScenetError], str], ...] = (
    (CompositionError, "composition"),
    (UnknownPuppetError, "unknown-puppet"),
    (UnknownPoseError, "unknown-pose"),
    (UnknownExpressionError, "unknown-expression"),
    (BalloonPlacementError, "balloon-placement"),
    (LayoutError, "layout"),
    (PanelSyntaxError, "invalid-field"),
)


def _rule_for_scenet_error(exc: ScenetError) -> str:
    """Map an exception that escaped the compiler onto a rule."""
    for error_type, rule in _RULE_FOR_ERROR_TYPE:
        if isinstance(exc, error_type):
            return rule
    return "internal"


def _message_of(exc: BaseException) -> str:
    """The bare message, without `KeyError`'s repr quoting.

    `KeyError` stringifies as `repr(args[0])`, which wraps the message in whichever
    quote style avoids escaping -- so a message containing an apostrophe comes out
    double-quoted. Reading `args[0]` sidesteps that, exactly as the CLI does.
    """
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _read_mapping(text: str, source: Path | None) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    """Parse the document far enough to know it is a mapping.

    Everything here fails the same way -- one finding, and nothing further can be
    checked -- so it is separated from the validation that follows, where several
    findings come back at once.

    Args:
        text: The document source.
        source: Path it came from.

    Returns:
        The mapping and an empty list, or `None` and the single finding explaining why.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [
            Diagnostic(
                rule="syntax",
                message=f"invalid YAML: {exc}",
                source=source,
                region=syntax_error_region(exc),
            )
        ]

    if data is None:
        return None, [
            Diagnostic(
                rule="syntax",
                message="panel source is empty",
                source=source,
                region=DOCUMENT_START,
            )
        ]

    if not isinstance(data, dict):
        return None, [
            Diagnostic(
                rule="not-a-mapping",
                message=f"expected a mapping at the top level, found {type(data).__name__}",
                source=source,
                region=locate(text, ()) or DOCUMENT_START,
            )
        ]

    return data, []


def _asset_diagnostic(
    rule: str,
    exc: BaseException,
    text: str,
    source: Path | None,
    path: tuple[str | int, ...],
) -> Diagnostic:
    """Build a `Diagnostic` from a caught asset-lookup error, at a specific path."""
    return Diagnostic(
        rule=rule,
        message=_message_of(exc),
        path=path,
        source=source,
        region=locate(text, path) or DOCUMENT_START,
    )


def _diagnose_cast(
    panel: PanelIR,
    text: str,
    source: Path | None,
    *,
    prefix: tuple[str | int, ...],
    library: PuppetLibrary | None,
) -> list[Diagnostic]:
    """Resolve every cast member against the puppet library.

    The IR does not know the puppet library exists -- `CastMember.reference`, `.pose`
    and `.expression` are plain `str`s, and validating them is what tells `pointing`
    from `smirking`. This runs after `PanelIR.model_validate` succeeds, so it only sees
    a cast that is otherwise well-formed, and it resolves the library lazily -- only
    when the panel actually has a cast to check -- so a cast-less document costs
    nothing extra.

    Every actor is checked, not just the first, mirroring `_diagnose_scene`'s reasoning:
    a panel with three bad references should report three findings.
    """
    if not panel.cast:
        return []
    library = library or default_library()

    found: list[Diagnostic] = []
    for actor_id, member in panel.cast.items():
        actor_path = (*prefix, "cast", actor_id)
        try:
            spec = library.get(member.reference)
        except UnknownPuppetError as exc:
            found.append(
                _asset_diagnostic("unknown-puppet", exc, text, source, (*actor_path, "reference"))
            )
            continue

        try:
            spec.pose_angles(member.pose)
        except UnknownPoseError as exc:
            found.append(
                _asset_diagnostic("unknown-pose", exc, text, source, (*actor_path, "pose"))
            )

        # Guarded exactly as `resolve` guards it: a puppet that declares no
        # expressions at all was never asked to have `neutral`, which is what
        # `CastMember.expression` defaults to.
        if spec.expressions:
            try:
                spec.expression_states(member.expression)
            except UnknownExpressionError as exc:
                found.append(
                    _asset_diagnostic(
                        "unknown-expression", exc, text, source, (*actor_path, "expression")
                    )
                )

    return found


def _diagnose_panel(
    data: dict[str, Any],
    text: str,
    source: Path | None,
    *,
    prefix: tuple[str | int, ...],
    library: PuppetLibrary | None = None,
    deep: bool = False,
) -> list[Diagnostic]:
    """Validate one panel mapping and report what is wrong with it.

    Args:
        data: The panel, in surface form.
        text: The whole document, for locating positions.
        source: Path it came from.
        prefix: Path to this panel within the document, so a finding inside a sequence
            points at the panel it is in rather than at the top level.
        library: Puppet library to resolve cast references against. Resolved lazily
            (see `_diagnose_cast`) when not given.
        deep: Also run the full compiler once the cheap checks come back clean, to
            reach `layout` and `balloon-placement` -- rules the cheap pass cannot
            produce because they only surface once the solver runs.

    Returns:
        Findings, unsorted.
    """
    try:
        normalised = normalise(data)
    except ScenetError as exc:
        return [
            Diagnostic(
                rule=_rule_for_scenet_error(exc),
                message=_message_of(exc),
                path=prefix,
                source=source,
                region=locate(text, prefix) or DOCUMENT_START,
            )
        ]

    try:
        panel = PanelIR.model_validate(normalised)
    except ValidationError as exc:
        return _from_validation_error(exc, text, source, prefix=prefix)
    except ScenetError as exc:
        return [
            Diagnostic(
                rule=_rule_for_scenet_error(exc),
                message=_message_of(exc),
                path=prefix,
                source=source,
                region=locate(text, prefix) or DOCUMENT_START,
            )
        ]

    found = _diagnose_cast(panel, text, source, prefix=prefix, library=library)
    if found:
        # A cast that does not resolve is not a document `--deep` can usefully
        # compile -- it would fail on the same reference with a worse location.
        return found

    if deep:
        try:
            compile_ir(panel, library=library)
        except ScenetError as exc:
            return [
                Diagnostic(
                    rule=_rule_for_scenet_error(exc),
                    message=_message_of(exc),
                    path=prefix,
                    source=source,
                    region=locate(text, prefix) or DOCUMENT_START,
                )
            ]

    return []


def _diagnose_scene(
    data: dict[str, Any],
    text: str,
    source: Path | None,
    *,
    library: PuppetLibrary | None,
    deep: bool,
) -> list[Diagnostic]:
    """Validate a `panels:` sequence, one panel at a time.

    Mirrors `parse_scene`: anything alongside `panels` is a default every panel inherits,
    and `over:` chains are resolved before validation. Every panel is checked rather than
    stopping at the first bad one -- a scene with three broken panels should report three
    findings, not one and two more runs.
    """
    panels = data["panels"]
    if not isinstance(panels, dict):
        return [
            Diagnostic(
                rule="invalid-field",
                message="'panels' must be a mapping of name to panel",
                path=("panels",),
                source=source,
                region=locate(text, ("panels",)) or DOCUMENT_START,
            )
        ]

    found: list[Diagnostic] = []
    for name, document in panels.items():
        if not isinstance(document, dict):
            found.append(
                Diagnostic(
                    rule="invalid-field",
                    message=f"panel '{name}' must be a mapping",
                    path=("panels", name),
                    source=source,
                    region=locate(text, ("panels", name)) or DOCUMENT_START,
                )
            )
    if found:
        return found

    try:
        composed = resolve_overrides(panels)
    except CompositionError as exc:
        return [
            Diagnostic(
                rule="composition",
                message=_message_of(exc),
                path=("panels",),
                source=source,
                region=locate(text, ("panels",)) or DOCUMENT_START,
            )
        ]

    defaults = {key: value for key, value in data.items() if key != "panels"}
    for name, document in composed.items():
        merged = merge(defaults, document) if defaults else document
        found.extend(
            _diagnose_panel(
                merged, text, source, prefix=("panels", name), library=library, deep=deep
            )
        )
    return found


def diagnose_source(
    text: str,
    *,
    source: Path | None = None,
    library: PuppetLibrary | None = None,
    deep: bool = False,
) -> list[Diagnostic]:
    """Check a document and report everything wrong with it, without raising.

    Runs the same validation the compiler does. Where the compiler raises on the first
    fault, this collects: pydantic reports every field error at once, so a document with
    four mistakes yields four findings rather than one and three more compilations.

    Beyond IR validation, every cast member's `reference`, `pose` and `expression` is
    resolved against a puppet library -- the IR alone cannot tell `pointing` from
    `smirking`, so without this a document with a nonsense pose reports clean here and
    then fails `build` with no rule and no location. The library is read once per call,
    only when a panel actually has a cast.

    Args:
        text: The document source, in the YAML surface syntax.
        source: Path it came from, used for the reported file and the fingerprint.
        library: Puppet library to resolve cast references, poses and expressions
            against. Defaults to the two shipped puppets, exactly as `build` does.
        deep: Also run the full compiler on any panel that passes every cheap check,
            to additionally catch `layout` and `balloon-placement` -- at the cost of a
            real compile, including font metrics. Off by default so `check` stays the
            cheap pass it is documented as.

    Returns:
        Findings in source order. Empty means the document is valid.

    Example:
        >>> from scenet.diagnostics import diagnose_source
        >>> found = diagnose_source("panel: {size: [0, 10]}")
        >>> found[0].rule
        'panel-geometry'
    """
    data, refused = _read_mapping(text, source)
    if data is None:
        return refused

    # A document with a top-level `panels:` key is a sequence, and validating it as a
    # single panel reports `panels` as an unknown key -- a confident, wrong diagnostic on
    # every valid scene file in the repository. The frontend has always made this
    # distinction; the checker has to make it too.
    if "panels" in data:
        return _in_source_order(_diagnose_scene(data, text, source, library=library, deep=deep))

    return _in_source_order(
        _diagnose_panel(data, text, source, prefix=(), library=library, deep=deep)
    )


def _in_source_order(found: list[Diagnostic]) -> list[Diagnostic]:
    """Sort findings by where they are, so output does not depend on validator order.

    Ties break on the rule and then the message, so two findings at the same position
    still come out in the same order on every run.
    """
    return sorted(
        found,
        key=lambda item: (
            item.region.start if item.region else Position(0, 0),
            item.rule,
            item.message,
        ),
    )


def diagnose_script(
    text: str,
    *,
    source: Path | None = None,
    library: PuppetLibrary | None = None,
    deep: bool = False,
) -> list[Diagnostic]:
    """Check a comic script.

    The script frontend is line-oriented and hand-written, so parsing itself stops at
    the first fault rather than collecting -- there is no equivalent of pydantic's
    error list to gather, so at most one finding of that kind is ever returned.

    Once parsing succeeds, though, the result is the same `PanelIR` per panel that the
    YAML frontend produces -- the `cast:` block accepts `pose:` and `expression:` here
    too -- so it is resolved against the puppet library the same way, and can report
    several findings if several panels have a bad reference.

    Positions for a parse fault are lines only: a script line is prose, and pointing
    at a column within it would imply a precision the parser does not have. Cast
    findings carry the same structural path a YAML document's would.

    Args:
        text: The script source.
        source: Path it came from.
        library: Puppet library to resolve cast references, poses and expressions
            against. Defaults to the two shipped puppets.
        deep: Also run the full compiler on any panel that passes every cheap check.
            See `diagnose_source`.

    Returns:
        Findings in source order, empty if the script is valid.
    """
    try:
        panels = parse_script(text, source=source)
    except ScriptSyntaxError as exc:
        line = exc.line or 1
        return [
            Diagnostic(
                rule=_rule_for_scenet_error(exc),
                message=_message_of(exc),
                source=source,
                region=Region(
                    start=Position(line=line, column=1),
                    end=Position(line=line, column=2),
                ),
            )
        ]
    except ScenetError as exc:
        return [
            Diagnostic(
                rule=_rule_for_scenet_error(exc),
                message=_message_of(exc),
                source=source,
                region=DOCUMENT_START,
            )
        ]

    found: list[Diagnostic] = []
    for name, panel in panels.items():
        found.extend(_diagnose_cast(panel, text, source, prefix=(name,), library=library))
    if found:
        return _in_source_order(found)

    if deep:
        for name, panel in panels.items():
            prefix = (name,)
            try:
                compile_ir(panel, library=library)
            except ScenetError as exc:
                return [
                    Diagnostic(
                        rule=_rule_for_scenet_error(exc),
                        message=_message_of(exc),
                        path=prefix,
                        source=source,
                        region=DOCUMENT_START,
                    )
                ]

    return []


def diagnose_file(
    path: Path, *, library: PuppetLibrary | None = None, deep: bool = False
) -> list[Diagnostic]:
    """Check a document on disk, choosing the frontend by extension.

    Args:
        path: The file to check.
        library: Puppet library to resolve cast references, poses and expressions
            against. Defaults to the two shipped puppets.
        deep: Also run the full compiler on any panel that passes every cheap check.
            See `diagnose_source`.

    Returns:
        Findings in source order, empty if the document is valid.

    Raises:
        OSError: The file cannot be read. Not reported as a finding, because a file that
            cannot be opened is a problem with the invocation rather than with a panel.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".script":
        return diagnose_script(text, source=path, library=library, deep=deep)
    return diagnose_source(text, source=path, library=library, deep=deep)


def to_sarif(found: list[Diagnostic], *, root: Path | None = None) -> dict[str, Any]:
    """Build a SARIF 2.1.0 document from a list of findings.

    Only the rules actually referenced are emitted. The catalogue is small enough that
    emitting all of it would be harmless, but a consumer showing "14 rules, 1 result"
    invites the reader to wonder what the other thirteen did.

    Args:
        found: The findings, in the order they should appear.
        root: Directory to report paths relative to, usually the working directory.

    Returns:
        A JSON-serialisable SARIF document. A clean run still produces a full document
        with an empty `results` list -- a consumer needs the run to know the tool passed,
        or a clean check is indistinguishable from a check that never ran.
    """
    used = sorted({item.rule for item in found})
    index_of = {rule: index for index, rule in enumerate(used)}

    rules = [
        {
            "id": f"{RULE_NAMESPACE}/{name}",
            "name": name,
            "shortDescription": {"text": RULES[name].summary},
            "fullDescription": {"text": RULES[name].description},
            "help": {"text": RULES[name].help},
            "defaultConfiguration": {"level": "error"},
        }
        for name in used
    ]

    results = [
        {
            "ruleId": f"{RULE_NAMESPACE}/{item.rule}",
            "ruleIndex": index_of[item.rule],
            "level": "error",
            "message": {"text": item.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": _uri_for(item.source, root=root)},
                        "region": _region_json(item.region or DOCUMENT_START),
                    }
                }
            ],
            "partialFingerprints": {FINGERPRINT_KEY: item.fingerprint()},
        }
        for item in found
    ]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "scenet",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def _region_json(region: Region) -> dict[str, int]:
    """A SARIF region, with every bound at least 1.

    GitHub rejects a region whose numbers are below one, and a zero-width region is not
    useful to look at, so an end that did not come out after its start is nudged.
    """
    start_line = max(region.start.line, 1)
    start_column = max(region.start.column, 1)
    end_line = max(region.end.line, start_line)
    end_column = max(region.end.column, start_column + 1 if end_line == start_line else 1)
    return {
        "startLine": start_line,
        "startColumn": start_column,
        "endLine": end_line,
        "endColumn": end_column,
    }
