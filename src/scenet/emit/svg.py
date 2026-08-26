"""Panel Core into SVG.

Purely mechanical: every position here was decided by the solver. The emitter makes
no layout decisions, which is what keeps rendering swappable and golden tests
meaningful.

Numbers are formatted through one helper at fixed precision so that output is
byte-identical across platforms, whose float repr differs in the last digit.
"""

import math
from xml.sax.saxutils import escape, quoteattr

from scenet.core import CoreActor, CoreBalloon, CoreCaption, PanelCore, Tail
from scenet.ir import BalloonKind
from scenet.solve.text import ITALIC_FONT_PATH, FontMetrics, load_metrics

STROKE = "#111111"
FILL_FIGURE = "#e8e6e1"
FILL_BALLOON = "#ffffff"
FILL_PANEL = "#ffffff"

FIGURE_STROKE_WIDTH = 3.0
BALLOON_STROKE_WIDTH = 3.0

# Corner rounding of a speech balloon, as a fraction of its smaller side.
BALLOON_CORNER = 0.42

# Half-width of a tail where it meets the balloon, as a fraction of balloon height.
TAIL_BASE_FRACTION = 0.18

CAPTION_STROKE_WIDTH = 2.5


def fmt(value: float) -> str:
    """Format a number for SVG output.

    Trailing zeros are stripped so `100.00` prints as `100`, which keeps files small
    and diffs readable without making them any less exact.
    """
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _points(pairs: list[tuple[float, float]]) -> str:
    return " ".join(f"{fmt(x)},{fmt(y)}" for x, y in pairs)


def render(
    core: PanelCore,
    *,
    metrics: FontMetrics | None = None,
    live_text: bool = False,
) -> str:
    """Render a compiled panel as a standalone SVG document."""
    metrics = metrics or load_metrics()
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(core.width)}" '
        f'height="{fmt(core.height)}" viewBox="0 0 {fmt(core.width)} {fmt(core.height)}">',
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        f'fill="{FILL_PANEL}"/>',
        f'  <g stroke="{STROKE}" stroke-linecap="round" stroke-linejoin="round">',
    ]

    # Painter's order: lower depth first, so higher-depth actors land in front.
    for actor in sorted(core.actors, key=lambda a: (a.depth, a.id)):
        parts.append(_render_actor(actor))

    # Balloons and captions sit above the figures and share one reading order, so they
    # are emitted as one sequence rather than one layer stacked on the other.
    italic = load_metrics(str(ITALIC_FONT_PATH)) if core.captions else metrics
    lettering = sorted([*core.balloons, *core.captions], key=lambda item: item.order)
    for item in lettering:
        if isinstance(item, CoreCaption):
            parts.append(
                _render_caption(item, italic if item.italic else metrics, live_text=live_text)
            )
        else:
            parts.append(_render_balloon(item, metrics, live_text=live_text))

    parts.append("  </g>")
    parts.append(
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        f'fill="none" stroke="{STROKE}" stroke-width="6"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def attr(value: str) -> str:
    r"""Quote a string for use as an XML attribute value, delimiters included.

    Returns the value *with* its surrounding quotes, because choosing the quote
    character is part of escaping correctly -- `quoteattr` picks whichever one avoids
    the most escaping.

    This exists because `xml.sax.saxutils.escape` does **not** escape quotation marks.
    That is fine for element content and wrong for an attribute: identifiers here come
    from user documents -- a cast key, a panel name -- and one containing a double quote
    would close the attribute early and let the rest of it be read as markup. The output
    is injected with `innerHTML` by the browser playground, so that is a scripting
    vector, not merely malformed XML.

    Args:
        value: Any string, trusted or not.

    Returns:
        The value, escaped and wrapped in quotes.

    Example:
        >>> from scenet.emit.svg import attr
        >>> attr("alice")
        '"alice"'
        >>> attr('a" onload=x')
        '\'a" onload=x\''
    """
    return quoteattr(value)


def _render_actor(actor: CoreActor) -> str:
    lines = [
        f'    <g id={attr("actor-" + actor.id)} fill="{FILL_FIGURE}" '
        f'stroke-width="{fmt(FIGURE_STROKE_WIDTH)}">'
    ]

    # Limbs are drawn as thick round-capped strokes rather than outlined capsules:
    # one path element each instead of a constructed outline, and the joins between
    # segments merge cleanly.
    for capsule in actor.capsules:
        (x1, y1), (x2, y2) = capsule.start, capsule.end
        lines.append(
            f'      <path d="M{fmt(x1)} {fmt(y1)} L{fmt(x2)} {fmt(y2)}" '
            f'fill="none" stroke="{STROKE}" stroke-width="{fmt(capsule.width)}"/>'
        )
        lines.append(
            f'      <path d="M{fmt(x1)} {fmt(y1)} L{fmt(x2)} {fmt(y2)}" '
            f'fill="none" stroke="{FILL_FIGURE}" '
            f'stroke-width="{fmt(max(capsule.width - 2 * FIGURE_STROKE_WIDTH, 1.0))}"/>'
        )

    for blob in actor.blobs:
        cx, cy = blob.centre
        lines.append(
            f'      <circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(blob.radius)}" '
            f'fill="{FILL_FIGURE}" stroke="{STROKE}" stroke-width="{fmt(FIGURE_STROKE_WIDTH)}"/>'
        )

    lines.append("    </g>")
    return "\n".join(lines)


def _render_balloon(balloon: CoreBalloon, metrics: FontMetrics, *, live_text: bool) -> str:
    box = balloon.box
    lines = [f"    <g id={attr('balloon-' + balloon.id)}>"]

    lines.append(_tail_shape(balloon))
    lines.append(_balloon_outline(balloon))

    # Text is laid out from the top of the box: padding, then one line height per
    # line, landing each baseline where the solver's measurement assumed it.
    padding = (box.height - len(balloon.lines) * balloon.line_height) / 2
    ascent = balloon.font_size * 0.74
    for index, text in enumerate(balloon.lines):
        baseline = box.y + padding + index * balloon.line_height + ascent
        width = metrics.measure(text, balloon.font_size)
        start_x = box.x + (box.width - width) / 2
        lines.append(
            _live_text(text, start_x, baseline, balloon.font_size)
            if live_text
            else _outlined_text(text, start_x, baseline, balloon.font_size, metrics)
        )

    lines.append("    </g>")
    return "\n".join(lines)


def _render_caption(caption: CoreCaption, metrics: FontMetrics, *, live_text: bool) -> str:
    """A caption box: a plain rectangle with its text set flush left.

    Square corners, because a caption is a box and not a balloon -- rounding it would
    read as a speech balloon that had lost its tail.

    Left alignment is a **convention**, not a rule the way reading order is. Multiple
    lettering references describe it as the norm while calling it a house preference,
    so it is implemented as the default and recorded as a choice. It is also the one
    place captions deliberately differ from balloons, which centre their text.
    """
    box = caption.box
    lines = [f"    <g id={attr('caption-' + caption.id)}>"]
    lines.append(
        f'      <rect x="{fmt(box.x)}" y="{fmt(box.y)}" width="{fmt(box.width)}" '
        f'height="{fmt(box.height)}" fill="{FILL_BALLOON}" stroke="{STROKE}" '
        f'stroke-width="{fmt(CAPTION_STROKE_WIDTH)}"/>'
    )

    # Padding is derived from the box the solver produced rather than restated as a
    # constant here, so the emitter cannot drift out of agreement with it. The box was
    # padded equally on both axes, so the vertical inset gives the horizontal one too.
    padding = (box.height - len(caption.lines) * caption.line_height) / 2
    ascent = caption.font_size * 0.74
    for index, text in enumerate(caption.lines):
        baseline = box.y + padding + index * caption.line_height + ascent
        lines.append(
            _live_text(text, box.x + padding, baseline, caption.font_size, italic=caption.italic)
            if live_text
            else _outlined_text(text, box.x + padding, baseline, caption.font_size, metrics)
        )

    lines.append("    </g>")
    return "\n".join(lines)


def _balloon_outline(balloon: CoreBalloon) -> str:
    box = balloon.box
    dash = ' stroke-dasharray="12 9"' if balloon.kind is BalloonKind.WHISPER else ""

    if balloon.kind is BalloonKind.SHOUT:
        return (
            f'      <polygon points="{_points(_burst(balloon))}" fill="{FILL_BALLOON}" '
            f'stroke="{STROKE}" stroke-width="{fmt(BALLOON_STROKE_WIDTH)}"/>'
        )
    if balloon.kind is BalloonKind.THOUGHT:
        return (
            f'      <ellipse cx="{fmt(box.x + box.width / 2)}" '
            f'cy="{fmt(box.y + box.height / 2)}" rx="{fmt(box.width / 2)}" '
            f'ry="{fmt(box.height / 2)}" fill="{FILL_BALLOON}" stroke="{STROKE}" '
            f'stroke-width="{fmt(BALLOON_STROKE_WIDTH)}"/>'
        )

    radius = min(box.width, box.height) * BALLOON_CORNER
    return (
        f'      <rect x="{fmt(box.x)}" y="{fmt(box.y)}" width="{fmt(box.width)}" '
        f'height="{fmt(box.height)}" rx="{fmt(radius)}" ry="{fmt(radius)}" '
        f'fill="{FILL_BALLOON}" stroke="{STROKE}" '
        f'stroke-width="{fmt(BALLOON_STROKE_WIDTH)}"{dash}/>'
    )


def _burst(balloon: CoreBalloon) -> list[tuple[float, float]]:
    """A spiky outline for a shout.

    Spike count follows the balloon's perimeter so a long balloon does not end up with
    a handful of enormous points.
    """
    box = balloon.box
    cx, cy = box.x + box.width / 2, box.y + box.height / 2
    rx, ry = box.width / 2, box.height / 2
    spikes = max(10, int((box.width + box.height) / 26) * 2)
    points: list[tuple[float, float]] = []
    for index in range(spikes * 2):
        angle = math.pi * index / spikes
        reach = 1.22 if index % 2 == 0 else 0.94
        points.append((cx + math.cos(angle) * rx * reach, cy + math.sin(angle) * ry * reach))
    return points


def _tail_shape(balloon: CoreBalloon) -> str:
    """The pointer from balloon to mouth.

    A thought balloon gets a trail of shrinking circles instead of a triangle, which
    is the established convention and reads instantly.
    """
    tail: Tail = balloon.tail
    (sx, sy), (ex, ey) = tail.start, tail.end

    if balloon.kind is BalloonKind.THOUGHT:
        bubbles: list[str] = []
        for index, t in enumerate((0.35, 0.62, 0.85)):
            x = sx + (ex - sx) * t
            y = sy + (ey - sy) * t
            radius = balloon.font_size * (0.34 - index * 0.09)
            bubbles.append(
                f'      <circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(radius)}" '
                f'fill="{FILL_BALLOON}" stroke="{STROKE}" '
                f'stroke-width="{fmt(BALLOON_STROKE_WIDTH)}"/>'
            )
        return "\n".join(bubbles)

    # A tapered triangle: wide where it leaves the balloon, a point at the mouth.
    base = max(balloon.box.height * TAIL_BASE_FRACTION, balloon.font_size * 0.35)
    dx, dy = ex - sx, ey - sy
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * base / 2, dx / length * base / 2

    if tail.control is not None:
        cx, cy = tail.control
        path = (
            f"M{fmt(sx + nx)} {fmt(sy + ny)} "
            f"Q{fmt(cx)} {fmt(cy)} {fmt(ex)} {fmt(ey)} "
            f"Q{fmt(cx)} {fmt(cy)} {fmt(sx - nx)} {fmt(sy - ny)} Z"
        )
    else:
        path = (
            f"M{fmt(sx + nx)} {fmt(sy + ny)} L{fmt(ex)} {fmt(ey)} L{fmt(sx - nx)} {fmt(sy - ny)} Z"
        )
    return (
        f'      <path d="{path}" fill="{FILL_BALLOON}" stroke="{STROKE}" '
        f'stroke-width="{fmt(BALLOON_STROKE_WIDTH)}"/>'
    )


def _outlined_text(
    text: str, x: float, baseline: float, font_size: float, metrics: FontMetrics
) -> str:
    """Lettering as glyph outlines.

    Glyph coordinates are y-up in font units, so each is scaled by size/unitsPerEm and
    flipped. The result depends on no font being installed anywhere.
    """
    scale = font_size / metrics.units_per_em
    cursor = x
    glyphs: list[str] = []
    for path, advance in metrics.glyph_outlines(text):
        if path:
            glyphs.append(
                f'      <path d="{path}" fill="{STROKE}" stroke="none" '
                f'transform="translate({fmt(cursor)} {fmt(baseline)}) '
                f'scale({fmt(scale)} {fmt(-scale)})"/>'
            )
        cursor += advance * font_size
    return "\n".join(glyphs)


def _live_text(
    text: str, x: float, baseline: float, font_size: float, *, italic: bool = False
) -> str:
    """Lettering as a real `<text>` element.

    Selectable and editable, at the cost of depending on the reader having a
    metrically compatible font. Offered as an option, never the default.
    """
    style = ' font-style="italic"' if italic else ""
    return (
        f'      <text x="{fmt(x)}" y="{fmt(baseline)}" font-size="{fmt(font_size)}" '
        f'font-family="Source Sans Pro, sans-serif"{style} fill="{STROKE}" '
        f'stroke="none">{escape(text)}</text>'
    )
