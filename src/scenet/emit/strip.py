"""Several panels laid out as a strip.

Deliberately minimal. Real page composition -- tiers, panels of varying size, the
page-level reading path, bleeds -- is a substantial design problem in its own right
and is explicitly out of scope. This is the smallest thing that lets a sequence be
read as a sequence: panels in a row, separated by a gutter, in declaration order.

The gutter is not decoration. It is where the reader performs what Scott McCloud calls
closure -- inferring what happened between two panels -- and it is the one formal
element that distinguishes comics from a series of illustrations.
"""

from scenet.core import PanelCore
from scenet.emit.svg import fmt, render

# Space between panels, as a fraction of the tallest panel.
GUTTER_FRACTION = 0.04

MARGIN_FRACTION = 0.03


def render_strip(panels: list[tuple[str, PanelCore]], *, live_text: bool = False) -> str:
    """Lay panels left to right in reading order.

    Each panel is rendered independently and then placed, rather than being
    re-solved: a panel's composition must not depend on what sits beside it, or the
    same source would compile differently in isolation.
    """
    if not panels:
        raise ValueError("a strip needs at least one panel")

    tallest = max(core.height for _name, core in panels)
    gutter = tallest * GUTTER_FRACTION
    margin = tallest * MARGIN_FRACTION

    total_width = sum(core.width for _name, core in panels) + gutter * (len(panels) - 1)
    width = total_width + 2 * margin
    height = tallest + 2 * margin

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(width)}" height="{fmt(height)}" '
        f'viewBox="0 0 {fmt(width)} {fmt(height)}">',
        f'  <rect x="0" y="0" width="{fmt(width)}" height="{fmt(height)}" fill="#ffffff"/>',
    ]

    cursor = margin
    for name, core in panels:
        # Panels of differing height sit on a common top edge, which is how a tier of
        # unequal panels is conventionally aligned.
        inner = render(core, live_text=live_text)
        body = inner.split("\n", 2)[2].rsplit("</svg>", 1)[0]
        parts.append(f'  <g id="panel-{name}" transform="translate({fmt(cursor)} {fmt(margin)})">')
        parts.append(body.rstrip())
        parts.append("  </g>")
        cursor += core.width + gutter

    parts.append("</svg>")
    return "\n".join(parts) + "\n"
