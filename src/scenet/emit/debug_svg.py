"""Diagnostic overlay: what the solver was actually looking at.

Building a geometric solver without this is guesswork. When a balloon lands somewhere
surprising, the question is always "what did the solver think was there?" -- and the
answer is invisible in the finished panel. This draws the hidden geometry: silhouette
hulls, face exclusion circles, anchors, gaze vectors and tail routes.
"""

from scenet.core import PanelCore
from scenet.emit.svg import fmt

HULL = "#2f7fd0"
FACE = "#d94f4f"
ANCHOR = "#1f9c53"
GAZE = "#b060d0"
BALLOON = "#e08a1e"
GRID = "#c9c9c9"


def render_debug(core: PanelCore) -> str:
    """Render the solver's working geometry over a faint copy of the panel."""
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(core.width)}" '
        f'height="{fmt(core.height)}" viewBox="0 0 {fmt(core.width)} {fmt(core.height)}">',
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        'fill="#ffffff"/>',
        _thirds(core),
    ]

    for actor in sorted(core.actors, key=lambda a: a.id):
        parts.append(f'  <g id="debug-{actor.id}">')
        parts.append(
            f'    <polygon points="{_hull_points(actor.hull)}" fill="{HULL}" '
            f'fill-opacity="0.10" stroke="{HULL}" stroke-width="2"/>'
        )
        face = actor.face_exclusion
        parts.append(
            f'    <circle cx="{fmt(face.cx)}" cy="{fmt(face.cy)}" r="{fmt(face.r)}" '
            f'fill="{FACE}" fill-opacity="0.12" stroke="{FACE}" stroke-width="2" '
            'stroke-dasharray="8 6"/>'
        )

        eyes = actor.anchors.get("eyes")
        if eyes is not None:
            reach = face.r * 3.0
            parts.append(
                f'    <line x1="{fmt(eyes[0])}" y1="{fmt(eyes[1])}" '
                f'x2="{fmt(eyes[0] + actor.gaze[0] * reach)}" '
                f'y2="{fmt(eyes[1] + actor.gaze[1] * reach)}" stroke="{GAZE}" '
                'stroke-width="3" stroke-dasharray="10 6"/>'
            )

        for name, (x, y) in sorted(actor.anchors.items()):
            parts.append(
                f'    <circle cx="{fmt(x)}" cy="{fmt(y)}" r="5" fill="{ANCHOR}"/>'
                f'<text x="{fmt(x + 9)}" y="{fmt(y - 6)}" font-size="15" '
                f'font-family="monospace" fill="{ANCHOR}">{name}</text>'
            )
        parts.append(
            f'    <text x="{fmt(actor.bounds.x)}" y="{fmt(actor.bounds.y - 8)}" '
            f'font-size="18" font-family="monospace" fill="{HULL}">'
            f"{actor.id} depth={actor.depth} scale={fmt(actor.transform.scale)}</text>"
        )
        parts.append("  </g>")

    for balloon in sorted(core.balloons, key=lambda b: b.order):
        box = balloon.box
        parts.append(
            f'  <rect x="{fmt(box.x)}" y="{fmt(box.y)}" width="{fmt(box.width)}" '
            f'height="{fmt(box.height)}" fill="{BALLOON}" fill-opacity="0.12" '
            f'stroke="{BALLOON}" stroke-width="2"/>'
        )
        tail = balloon.tail
        route = (
            f"M{fmt(tail.start[0])} {fmt(tail.start[1])} "
            f"Q{fmt(tail.control[0])} {fmt(tail.control[1])} {fmt(tail.end[0])} {fmt(tail.end[1])}"
            if tail.control
            else (
                f"M{fmt(tail.start[0])} {fmt(tail.start[1])} L{fmt(tail.end[0])} {fmt(tail.end[1])}"
            )
        )
        parts.append(f'  <path d="{route}" fill="none" stroke="{BALLOON}" stroke-width="3"/>')
        parts.append(
            f'  <text x="{fmt(box.x + 4)}" y="{fmt(box.y - 8)}" font-size="18" '
            f'font-family="monospace" fill="{BALLOON}">'
            f"{balloon.id} #{balloon.order} -&gt; {balloon.speaker}"
            f"{' curved' if tail.control else ''}</text>"
        )

    parts.append(
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        'fill="none" stroke="#111111" stroke-width="4"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _thirds(core: PanelCore) -> str:
    """Rule-of-thirds guides, which is what the anchor fractions are defined against."""
    lines: list[str] = []
    for fraction in (1 / 3, 2 / 3):
        x = core.width * fraction
        y = core.height * fraction
        lines.append(
            f'  <line x1="{fmt(x)}" y1="0" x2="{fmt(x)}" y2="{fmt(core.height)}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
        lines.append(
            f'  <line x1="0" y1="{fmt(y)}" x2="{fmt(core.width)}" y2="{fmt(y)}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
    return "\n".join(lines)


def _hull_points(hull: tuple[tuple[float, float], ...]) -> str:
    return " ".join(f"{fmt(x)},{fmt(y)}" for x, y in hull)
