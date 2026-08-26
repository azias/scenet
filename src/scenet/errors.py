"""Every exception Scenet raises, in one place.

A library that scatters its exception types across the modules that happen to raise
them forces callers to import from six places to write one `except` clause. Everything
Scenet can raise is defined here instead, under a single root, so that

    except ScenetError:

catches all of it and nothing else.

The hierarchy is three deep and the middle tier answers the question a caller actually
has, which is *whose fault is it*:

    ScenetError
    |-- SourceError    the document is wrong -- report it to whoever wrote the panel
    |-- SolverError    the document is fine, but no layout satisfies it
    `-- AssetError     a puppet is missing or malformed

Each also inherits the built-in exception a caller would have reached for before this
module existed -- `SourceError` is a `ValueError`, `UnknownPuppetError` is a `KeyError`
-- so pre-existing `except ValueError` handlers keep working unchanged.
"""

from pathlib import Path

__all__ = [
    "AssetError",
    "BalloonPlacementError",
    "CompositionError",
    "LayoutError",
    "PanelSyntaxError",
    "RuleViolationError",
    "ScenetError",
    "ScriptSyntaxError",
    "SolverError",
    "SourceError",
    "UnknownExpressionError",
    "UnknownPoseError",
    "UnknownPuppetError",
]


class ScenetError(Exception):
    """Root of every error Scenet raises.

    Catch this to handle anything the compiler can go wrong with, without having to
    enumerate the specific cases or accidentally swallowing unrelated `ValueError`s
    from elsewhere in your program.

    Example:
        >>> from scenet import ScenetError, compile_source
        >>> try:
        ...     compile_source("{panel: {size: [1000, 1000]}, cast: {ghost: {reference: nobody}}}")
        ... except ScenetError as exc:
        ...     print(type(exc).__name__)
        UnknownPuppetError

    See Also:
        :exc:`SourceError <scenet.errors.SourceError>`, for the "bad document" branch.
        :exc:`SolverError <scenet.errors.SolverError>`, for the "impossible layout" branch.
    """


class RuleViolationError(ValueError):
    """A named rule, broken at a known place in the document.

    Raised *inside* pydantic validators rather than out of them. pydantic wraps whatever
    a validator raises into its own `ValidationError`, and for a model-level validator
    it records the location as `()` -- the whole document -- because a validator has no
    way to say which field it was unhappy about. That is accurate and useless: the two
    checks that matter most here, `check_references_resolve` and
    `check_ordering_is_consistent`, both knew the exact path and had nowhere to put it,
    so every such diagnostic read `at <root>`.

    pydantic keeps the exception object it caught, under `ctx["error"]`, so a subclass
    carrying extra attributes survives validation intact and can be recovered on the
    other side. That is the whole trick.

    A plain `ValueError` so that a validator raising one behaves exactly as before for
    anybody not looking for the extra attributes. It deliberately does *not* inherit
    `ScenetError`: it never escapes validation as itself -- pydantic catches it and
    re-raises its own `ValidationError` -- so putting it in that hierarchy would promise
    a `except ScenetError` clause could catch it, which it cannot.

    Attributes:
        rule: Identifier from the catalogue in
            :mod:`scenet.diagnostics <scenet.diagnostics>`. Stable across releases,
            because a `ruleId` that moves breaks every alert that referenced it.
        loc: Path to the offending value, in pydantic's `loc` form -- string keys and
            integer indices, as in `("script", 0, "by")`.
    """

    def __init__(self, message: str, *, rule: str, loc: tuple[str | int, ...] = ()) -> None:
        """Build the violation.

        Args:
            message: What is wrong, phrased for whoever wrote the document.
            rule: Catalogue identifier for the rule that was broken.
            loc: Path to the offending value. Empty means the document as a whole.
        """
        self.rule = rule
        self.loc = loc
        super().__init__(message)


class SourceError(ScenetError, ValueError):
    """A document that could not be understood.

    Raised whenever the input is at fault: malformed YAML, an unknown predicate, a
    reference to a panel that does not exist, a negative panel size. The message names
    the location and the reason, and is written to be shown directly to whoever wrote
    the document -- no traceback required.

    Also a `ValueError`, since that is what a malformed value has always been.

    Attributes:
        source: Path the document was read from, or `None` for a string compiled in
            memory. Prefixed to the message when present, so a diagnostic never loses
            the file it came from.
    """

    def __init__(self, message: str, *, source: Path | None = None) -> None:
        """Build the error, prefixing the source path when there is one.

        Args:
            message: What went wrong, phrased for the person who wrote the document.
            source: Path the document came from, if it was read from disk.
        """
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


class SolverError(ScenetError, ValueError):
    """A document that is valid but cannot be laid out.

    The distinction from :exc:`SourceError <scenet.errors.SourceError>` matters: nothing is
    misspelled and nothing is missing, but the panel as described has no solution --
    a cast with nowhere left to stand, or a balloon with no legal position. The fix is
    an editorial change to the panel, not a correction to its syntax.

    Also a `ValueError`.
    """


class AssetError(ScenetError):
    """A puppet asset that is missing, unreadable or self-inconsistent."""


class PanelSyntaxError(SourceError):
    """A panel document that could not be parsed or validated.

    Carries the source path when one is known, so the message reads
    `path/to/duel.panel.yaml: invalid panel: ...` rather than losing the file it came
    from.

    Example:
        >>> from scenet import PanelSyntaxError, compile_source
        >>> try:
        ...     compile_source("panel: {size: [0, 100]}")
        ... except PanelSyntaxError as exc:
        ...     print(exc)
        invalid panel:
          at panel: panel size must be positive
    """


class ScriptSyntaxError(PanelSyntaxError):
    """A comic script that could not be parsed.

    A subclass of :exc:`PanelSyntaxError <scenet.errors.PanelSyntaxError>` rather than a
    sibling, because both frontends produce the same IR and a caller handling "bad
    input" should not have to care which syntax it was written in.

    Attributes:
        line: One-based line the fault is on, when the parser knows it. The comic-script
            frontend is line-oriented, so it usually does -- but it had only ever put
            the number into the message text, which is fine to read and useless to an
            editor drawing a squiggle. Structured diagnostics need it as a number.
            There is no column: a script line is prose, and pointing at a character
            within it would imply a precision the parser does not have.
    """

    def __init__(
        self, message: str, *, source: Path | None = None, line: int | None = None
    ) -> None:
        """Build the error, keeping the line number as data as well as prose.

        Args:
            message: What went wrong, phrased for whoever wrote the script.
            source: Path the script came from, if it was read from disk.
            line: One-based line the fault is on, if known.
        """
        self.line = line
        super().__init__(message, source=source)


class CompositionError(SourceError):
    """A `panels:` document whose `over:` inheritance cannot be resolved.

    Raised for a panel inheriting from one that does not exist, and for a cycle --
    `a` over `b` over `a` -- which has no fixed point to resolve to.

    Example:
        >>> from scenet import CompositionError, compile_scene
        >>> try:
        ...     compile_scene("panels: {a: {over: b}, b: {over: a}}")
        ... except CompositionError as exc:
        ...     print(exc)
        'over' chain is cyclic: a -> b -> a
    """


class LayoutError(SolverError):
    """A panel whose required constraints cannot all be satisfied.

    Actor placement runs a Cassowary solver in which non-overlap and declared
    left-to-right ordering are *required* constraints. If those genuinely conflict --
    two actors each required to be left of the other -- there is no solution and this
    is raised. Panel bounds are deliberately not required, so a merely crowded panel
    lets figures bleed off the edge instead of failing.
    """


class BalloonPlacementError(SolverError):
    """No legal position exists for a balloon or a caption.

    Every candidate position was rejected: it covered a face, left the panel,
    overlapped a box already placed, or would have broken reading order. Usually this
    means too many words for the panel size -- widen the panel, shorten the line, or
    split it across two panels.

    Captions raise this too. They obey the same hard rules and are placed in the same
    pass, so the failure is the same failure; the name is kept because the rule id
    `balloon-placement` is stable across releases.
    """


class UnknownPuppetError(AssetError, KeyError):
    """A cast member referencing a puppet the library does not contain.

    Also a `KeyError`, because that is what a lookup miss has always been, and because
    the library is a mapping in all but name.

    Note:
        `KeyError` stringifies as `repr(args[0])`, so `str(exc)` comes out quoted.
        Read `exc.args[0]` for the bare message -- which is what the CLI does.
    """


class UnknownPoseError(AssetError, KeyError):
    """A cast member's `pose` naming one its puppet does not declare.

    Also a `KeyError`, for the same reason as
    :exc:`UnknownPuppetError <scenet.errors.UnknownPuppetError>`: a pose lookup has
    always failed this way, and `PuppetSpec.pose_angles`'s documented `Raises: KeyError`
    stays true. `except KeyError` keeps working; a caller that wants the rule and
    location this now carries catches `UnknownPoseError` (or `AssetError`) instead.

    Note:
        `KeyError` stringifies as `repr(args[0])`, so `str(exc)` comes out quoted.
        Read `exc.args[0]` for the bare message.
    """


class UnknownExpressionError(AssetError, KeyError):
    """A cast member's `expression` naming one its puppet does not declare.

    The counterpart of :exc:`UnknownPoseError <scenet.errors.UnknownPoseError>` for
    `PuppetSpec.expression_states`, and deliberately identical in shape -- an
    expression is selected by name exactly as a pose is.

    Note:
        `KeyError` stringifies as `repr(args[0])`, so `str(exc)` comes out quoted.
        Read `exc.args[0]` for the bare message.
    """
