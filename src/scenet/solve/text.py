"""Text measurement and line breaking.

Nothing downstream can proceed without this. A balloon's size is a function of its
text, wrapped at some measure, in a specific font -- and placement, occlusion and
reading order all depend on that size. So wrapping is decided here, during
compilation, and the result is carried through Panel Core as explicit lines. The
emitter never re-measures and therefore can never disagree with the solver.

Determinism demands the font be fixed. It arrives as a declared dependency rather
than a system lookup precisely because "whatever font this machine happens to have"
is the opposite of reproducible.
"""

import functools
import math
from dataclasses import dataclass
from pathlib import Path

# The `fonts` packages publish each face through entry_points at install time, so
# the attribute exists at runtime but cannot be seen statically.
from fonts.ttf import (
    SourceSansPro,  # ty: ignore[unresolved-import]  # pyright: ignore[reportAttributeAccessIssue]
)
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

# Comic balloons are markedly wider than they are tall. Wrapping searches for the
# measure whose block lands nearest this ratio.
#
# 2.0 rather than something squarer: a lower target makes short dialogue break into
# too many lines, which is how "You forgot your umbrella!" ends up as
# "You forgot / your / umbrella!" with a word stranded alone. Letterers do not do
# that.
TARGET_ASPECT = 2.0

# Multiplied by font size to give the baseline-to-baseline distance.
LINE_HEIGHT_FACTOR = 1.25

# Space between the text block and the balloon outline, as a multiple of font size.
PADDING_FACTOR = 0.55

# Added to a block's shape score for each line beyond the first. Small, but enough
# that a marginally better aspect ratio cannot justify breaking a short phrase.
LINE_PENALTY = 0.08

# Weight on line-length imbalance. Comic lettering balances lines; a short line
# stranded beneath a long one reads as an accident even when the block as a whole is
# well proportioned.
RAGGEDNESS_WEIGHT = 0.3

DEFAULT_FONT_PATH = Path(SourceSansPro)


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Wrapped text, measured."""

    lines: tuple[str, ...]
    width: float
    height: float
    font_size: float
    line_height: float

    line_widths: tuple[float, ...] = ()

    @property
    def aspect(self) -> float:
        """Width divided by height, or `0.0` for an empty block.

        The quantity the line breaker optimises. Lettering convention wants a balloon
        wider than it is tall -- see `TARGET_ASPECT`.
        """
        return self.width / self.height if self.height else 0.0

    @property
    def raggedness(self) -> float:
        """How unbalanced the lines are, from 0 (equal) to nearly 1 (one line tiny)."""
        if len(self.line_widths) < 2 or self.width <= 0:
            return 0.0
        return 1.0 - min(self.line_widths) / max(self.line_widths)


class FontMetrics:
    """Advance widths read straight from the font's own tables.

    Kerning is deliberately ignored. Reading `kern`/`GPOS` would tighten measurement
    slightly, but SVG renderers do not agree on whether to apply it, and a measurement
    the renderer will not reproduce is worse than a slightly generous one. Erring wide
    means balloons are never too small for their text.
    """

    def __init__(self, path: Path = DEFAULT_FONT_PATH) -> None:
        """Open a font and read the tables needed for measurement.

        Args:
            path: A TrueType or OpenType file. Defaults to the font that ships as an
                ordinary dependency of this package -- never a system font lookup,
                because determinism requires the same metrics everywhere.

        Raises:
            ValueError: The font has no usable Unicode character map, so no text could
                be measured against it at all.
        """
        self.path = path
        self._font = TTFont(str(path), lazy=True)
        # fontTools builds table objects dynamically, so `unitsPerEm` exists at runtime
        # but not in any stub. Both checkers are told, each in its own dialect.
        head = self._font["head"]
        self._units_per_em: float = head.unitsPerEm  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]
        # A font with no usable Unicode cmap cannot be measured against text at all,
        # so this is worth failing on loudly rather than limping along with no glyphs.
        cmap = self._font.getBestCmap()
        if cmap is None:
            raise ValueError(f"{path}: font has no usable Unicode character map")
        self._cmap: dict[int, str] = cmap
        self._widths: dict[str, int] = {
            name: advance for name, (advance, _lsb) in self._font["hmtx"].metrics.items()
        }
        self._missing = self._widths.get(".notdef", 0)

    @property
    def units_per_em(self) -> float:
        """The font's design grid size, from its `head` table."""
        return self._units_per_em

    def advance(self, character: str) -> float:
        """Advance width of one character, in em units."""
        glyph = self._cmap.get(ord(character))
        raw = self._widths.get(glyph, self._missing) if glyph else self._missing
        return raw / self._units_per_em

    def measure(self, text: str, font_size: float) -> float:
        """Width of a string set at a given size.

        Args:
            text: The string to measure. Not wrapped; measured as one run.
            font_size: Type size in panel units.

        Returns:
            Width in panel units. Slightly generous, since kerning is ignored -- which
            errs toward balloons a shade too large rather than text that overflows.

        Example:
            >>> from scenet.solve.text import load_metrics
            >>> metrics = load_metrics()
            >>> metrics.measure("mm", 100) > metrics.measure("ii", 100)
            True
        """
        return sum(self.advance(character) for character in text) * font_size

    def line_height(self, font_size: float) -> float:
        """Baseline-to-baseline distance for a given type size.

        Args:
            font_size: Type size in panel units.

        Returns:
            `font_size * LINE_HEIGHT_FACTOR`. A fixed multiple rather than the font's
            own ascent-plus-descent, because comics lettering is set to a chosen
            leading rather than to whatever the typeface suggests.
        """
        return font_size * LINE_HEIGHT_FACTOR

    def glyph_outlines(self, text: str) -> list[tuple[str, float]]:
        """Each character's outline as SVG path data, with its advance in em units.

        Converting lettering to outlines rather than emitting `<text>` is what makes
        the output genuinely self-contained: no font to embed, no font to be missing,
        and the rendered shapes are by construction the ones that were measured. The
        cost is that the text is no longer selectable, which is why `--live-text`
        exists.
        """
        glyph_set = self._font.getGlyphSet()
        outlines: list[tuple[str, float]] = []
        for character in text:
            name = self._cmap.get(ord(character))
            if name is None or name not in glyph_set:
                outlines.append(("", self.advance(character)))
                continue
            pen = SVGPathPen(glyph_set)
            glyph_set[name].draw(pen)
            outlines.append((pen.getCommands(), self.advance(character)))
        return outlines


@functools.lru_cache(maxsize=4)
def load_metrics(path: str | None = None) -> FontMetrics:
    """Cached metrics. Parsing a 300 KB font per balloon would be absurd."""
    return FontMetrics(Path(path) if path else DEFAULT_FONT_PATH)


def wrap_to_width(text: str, metrics: FontMetrics, font_size: float, measure: float) -> list[str]:
    """Greedy word wrap at a given measure.

    Greedy rather than Knuth-Plass: balloons hold a handful of words, where the
    optimal-fit algorithm's advantage vanishes, and greedy is trivially deterministic.

    A single word longer than the measure is left to overflow rather than being
    hyphenated or broken. Breaking a word mid-way in comic lettering looks like a
    mistake, and the balloon widening to fit is the correct outcome.
    """
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if metrics.measure(candidate, font_size) <= measure:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def candidate_measures(words: list[str], metrics: FontMetrics, font_size: float) -> list[float]:
    """Every line measure at which the wrapping can change.

    A line is always some contiguous run of words, so the widths of all such runs are
    exactly the measures worth trying. Anything between two of them produces the same
    break points as the lower one.

    The obvious shortcut -- dividing total width by the desired line count -- looks
    equivalent and is not. For "You forgot your umbrella!" it never proposes the
    measure that fits "You forgot your", so the good two-line break is unreachable and
    the search settles for a ragged three-line block instead. Balloons hold a few
    dozen words at most, so enumerating runs costs nothing.
    """
    widths = {
        metrics.measure(" ".join(words[start:end]), font_size)
        for start in range(len(words))
        for end in range(start + 1, len(words) + 1)
    }
    return sorted(widths)


def layout_text(
    text: str,
    *,
    font_size: float,
    metrics: FontMetrics | None = None,
    target_aspect: float = TARGET_ASPECT,
) -> TextBlock:
    """Wrap text into the best-shaped block for a balloon.

    Scored on how close the block comes to the target aspect ratio, plus a penalty per
    line. The penalty is what stops a three-word phrase being split: purely on aspect,
    breaking "I know." into two lines scores marginally better than leaving it alone,
    which is not something any letterer would do.
    """
    metrics = metrics or load_metrics()
    words = text.split()
    line_height = metrics.line_height(font_size)
    if not words:
        return TextBlock((), 0.0, 0.0, font_size, line_height, ())

    widest_word = max(metrics.measure(word, font_size) for word in words)

    best: TextBlock | None = None
    best_score = math.inf
    for measure in candidate_measures(words, metrics, font_size):
        if measure < widest_word:
            # Narrower than the longest word, so it cannot change the wrapping.
            continue
        lines = wrap_to_width(text, metrics, font_size, measure)
        widths = tuple(metrics.measure(line, font_size) for line in lines)
        block = TextBlock(
            tuple(lines), max(widths), len(lines) * line_height, font_size, line_height, widths
        )
        score = _shape_score(block, target_aspect)
        if score < best_score:
            best, best_score = block, score

    if best is None:
        # Only reachable if every candidate measure was narrower than the longest
        # word -- a single word longer than any proposed line. Set it on one line and
        # let the balloon be as wide as it must be; refusing to letter a long word
        # would be worse than an over-wide balloon.
        widths = (widest_word,)
        best = TextBlock(
            (" ".join(words),), widest_word, line_height, font_size, line_height, widths
        )
    return best


def _shape_score(block: TextBlock, target: float) -> float:
    """How poorly a block is shaped. Lower is better.

    Aspect error is measured in log space so that being twice as wide as wanted is
    penalised equally with being half as wide. In linear space the search drifts toward
    tall narrow blocks, because a ratio can fall only to zero but rise without bound.
    """
    if block.height <= 0 or block.width <= 0:
        return math.inf
    aspect_error = abs(math.log(block.aspect / target))
    return (
        aspect_error + LINE_PENALTY * (len(block.lines) - 1) + RAGGEDNESS_WEIGHT * block.raggedness
    )


def balloon_size(block: TextBlock, padding_factor: float = PADDING_FACTOR) -> tuple[float, float]:
    """Outer dimensions of a balloon holding this text block."""
    padding = block.font_size * padding_factor
    return block.width + 2 * padding, block.height + 2 * padding
