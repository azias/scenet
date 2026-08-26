"""Where in the source a value came from.

`yaml.safe_load` returns values and throws away everything about where they were
written, which is fine for compiling and useless for reporting. `yaml.compose` parses
the same text into a *node* tree instead, and every node carries `start_mark` and
`end_mark`. So the document is composed a second time, purely to answer "where is
`script.0.by`?".

**`ruamel.yaml` is the library usually reached for here**, and its `.lc` line/column
marks would do the same job. It was not used: PyYAML is already a dependency and this
needs one function, so adding a second YAML implementation to the runtime -- and to the
licence gate -- would buy nothing.

Marks are 0-based; SARIF is 1-based. The conversion happens once, here, at the boundary.
"""

from dataclasses import dataclass

import yaml

__all__ = ["Position", "Region", "locate"]


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A one-based line and column, as SARIF and every editor count them.

    Attributes:
        line: One-based line number.
        column: One-based column number.
    """

    line: int
    column: int


@dataclass(frozen=True, slots=True, order=True)
class Region:
    """A span of source, from `start` up to `end`.

    Attributes:
        start: Where the value begins.
        end: Where it ends. SARIF treats the end column as exclusive, which is also how
            PyYAML's end marks behave, so the two agree without adjustment.
    """

    start: Position
    end: Position


#: Where a diagnostic points when nothing better is known. SARIF requires a region on
#: every result, and refusing to emit one would lose the finding entirely.
DOCUMENT_START = Region(start=Position(line=1, column=1), end=Position(line=1, column=2))


def _mark_to_region(node: yaml.Node) -> Region:
    """Convert a node's PyYAML marks into a one-based region."""
    return Region(
        start=Position(line=node.start_mark.line + 1, column=node.start_mark.column + 1),
        end=Position(line=node.end_mark.line + 1, column=node.end_mark.column + 1),
    )


def _descend(node: yaml.Node, step: str | int) -> yaml.Node | None:
    """Take one step into a composed node tree.

    Args:
        node: The node to descend from.
        step: A mapping key or a sequence index.

    Returns:
        The child node, or `None` if this node cannot be stepped into that way -- which
        happens routinely, because a pydantic `loc` path may name a field of a value
        that is not the shape the schema expected.
    """
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            # Compare as text: YAML keys arrive as scalar nodes, and `1` written as a
            # key is the string "1" here whether the path step is an int or a str.
            if isinstance(key, yaml.ScalarNode) and key.value == str(step):
                return value
        return None

    if isinstance(node, yaml.SequenceNode) and isinstance(step, int):
        if 0 <= step < len(node.value):
            return node.value[step]
        return None

    return None


def locate(text: str, path: tuple[str | int, ...]) -> Region | None:
    r"""Find where `path` was written in `text`.

    Walks as far down the path as the document allows and reports the deepest node it
    reached, so a path naming a field of something malformed still points at the
    malformed thing rather than giving up and pointing at the document.

    Args:
        text: The YAML source.
        path: A pydantic-style location, as in `("script", 0, "by")`.

    Returns:
        The region, or `None` if the text does not compose at all -- in which case the
        caller has a syntax error to report and no use for a path.

    Example:
        >>> from scenet.frontends.positions import locate
        >>> region = locate("cast:\n  alice: {reference: alice}\n", ("cast", "alice"))
        >>> region.start.line
        2
    """
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return None
    if node is None:
        return None

    deepest = node
    for step in path:
        child = _descend(deepest, step)
        if child is None:
            break
        deepest = child

    return _mark_to_region(deepest)


def syntax_error_region(exc: yaml.YAMLError) -> Region:
    """Where a YAML parse error happened.

    Args:
        exc: The error PyYAML raised.

    Returns:
        The problem mark as a region, or the start of the document when the error
        carries no mark -- which some do.
    """
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return DOCUMENT_START
    start = Position(line=mark.line + 1, column=mark.column + 1)
    return Region(start=start, end=Position(line=start.line, column=start.column + 1))
