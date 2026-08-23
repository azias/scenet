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
    "ScenetError",
    "ScriptSyntaxError",
    "SolverError",
    "SourceError",
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
    """


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
    """No legal position exists for a balloon.

    Every candidate position was rejected: it covered a face, left the panel,
    overlapped a balloon already placed, or would have broken reading order. Usually
    this means too much dialogue for the panel size -- widen the panel, shorten the
    line, or split it across two panels.
    """


class UnknownPuppetError(AssetError, KeyError):
    """A cast member referencing a puppet the library does not contain.

    Also a `KeyError`, because that is what a lookup miss has always been, and because
    the library is a mapping in all but name.

    Note:
        `KeyError` stringifies as `repr(args[0])`, so `str(exc)` comes out quoted.
        Read `exc.args[0]` for the bare message -- which is what the CLI does.
    """
