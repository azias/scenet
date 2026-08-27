"""Diagnostic overlay: what the solver was actually looking at.

Building a geometric solver without this is guesswork. When a balloon lands somewhere
surprising, the question is always "what did the solver think was there?" -- and the
answer is invisible in the finished panel. This draws the hidden geometry: silhouette
hulls, face exclusion circles, anchors, gaze vectors and tail routes.
"""

from scenet.core import FaceDisc, PanelCore
from scenet.emit.svg import fmt

HULL = "#2f7fd0"
FACE = "#d94f4f"
ANCHOR = "#1f9c53"
GAZE = "#b060d0"
AIM = "#8a2be2"
FEATURE = "#d98b1e"
BALLOON = "#e08a1e"
CAPTION = "#7a52c9"
GRID = "#c9c9c9"
MASS = "#3aa39a"
HORIZON = "#c2451f"


def render_debug(core: PanelCore) -> str:
    """Render the solver's working geometry over a faint copy of the panel."""
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt(core.width)}" '
        f'height="{fmt(core.height)}" viewBox="0 0 {fmt(core.width)} {fmt(core.height)}">',
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        'fill="#ffffff"/>',
        _thirds(core),
        _backdrop(core),
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
            # The aim, drawn solid beside the dashed facing vector. Two lines rather
            # than one because they are two different things: what the balloon solver
            # avoids, and what the pupils follow.
            if actor.gaze_aim is not None:
                parts.append(
                    f'    <line x1="{fmt(eyes[0])}" y1="{fmt(eyes[1])}" '
                    f'x2="{fmt(eyes[0] + actor.gaze_aim[0] * reach)}" '
                    f'y2="{fmt(eyes[1] + actor.gaze_aim[1] * reach)}" stroke="{AIM}" '
                    'stroke-width="3"/>'
                )

        for mark in actor.face_marks:
            centre = mark.centre if isinstance(mark, FaceDisc) else mark.points[0]
            parts.append(
                f'    <circle cx="{fmt(centre[0])}" cy="{fmt(centre[1])}" r="3" fill="{FEATURE}"/>'
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

    # Captions in their own colour: they take part in the same reading order but obey
    # a different cost function, so telling them apart at a glance is the point.
    for caption in sorted(core.captions, key=lambda c: c.order):
        box = caption.box
        parts.append(
            f'  <rect x="{fmt(box.x)}" y="{fmt(box.y)}" width="{fmt(box.width)}" '
            f'height="{fmt(box.height)}" fill="{CAPTION}" fill-opacity="0.12" '
            f'stroke="{CAPTION}" stroke-width="2"/>'
        )
        parts.append(
            f'  <text x="{fmt(box.x + 4)}" y="{fmt(box.y - 8)}" font-size="18" '
            f'font-family="monospace" fill="{CAPTION}">'
            f"{caption.id} #{caption.order} {caption.kind.value}</text>"
        )

    parts.append(
        f'  <rect x="0" y="0" width="{fmt(core.width)}" height="{fmt(core.height)}" '
        'fill="none" stroke="#111111" stroke-width="4"/>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _backdrop(core: PanelCore) -> str:
    """The setting as the solver sees it: outlines, planes, and the horizon.

    Drawn as outlines rather than fills, because the question this overlay answers about
    a backdrop is *where the solver thinks the masses are* -- which the finished panel
    hides precisely by filling them in.
    """
    if core.backdrop is None:
        return ""

    lines = [
        f'  <line x1="0" y1="{fmt(core.backdrop.horizon)}" x2="{fmt(core.width)}" '
        f'y2="{fmt(core.backdrop.horizon)}" stroke="{HORIZON}" stroke-width="2" '
        'stroke-dasharray="14 8"/>',
        f'  <text x="6" y="{fmt(core.backdrop.horizon - 6)}" font-size="15" '
        f'font-family="monospace" fill="{HORIZON}">horizon</text>',
    ]
    for mass in core.backdrop.masses:
        points = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in mass.polygon)
        top = min(y for _, y in mass.polygon)
        left = min(x for x, _ in mass.polygon)
        lines.append(
            f'  <polygon points="{points}" fill="{MASS}" fill-opacity="0.10" '
            f'stroke="{MASS}" stroke-width="2"/>'
        )
        lines.append(
            f'  <text x="{fmt(left + 6)}" y="{fmt(top + 18)}" font-size="15" '
            f'font-family="monospace" fill="{MASS}">'
            f"{mass.id} {mass.kind.value} {mass.plane.value} depth={mass.depth}</text>"
        )
    return "\n".join(lines)


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
