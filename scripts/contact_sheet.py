"""Render every expression at every shot type onto one page.

Whether a furrowed brow reads as anger at fourteen panel units is not a question a
test can answer. It is a question about a picture, and the only way to settle it is to
look -- so this puts every face the library can draw on one sheet, at every framing,
and you look at it.

That makes it the instrument for two decisions the code cannot make on its own: the
level-of-detail threshold in `assets/face.py`, below which features stop being a face
and become a smudge, and the per-state offsets that decide whether `sad` and `bored`
are actually distinguishable.

    uv run python scripts/contact_sheet.py -o out/faces.svg

Each cell is a real 1000-unit panel drawn small, **not** a small panel: the threshold
is measured in panel units, so a genuinely small panel would answer a different
question from the one being asked.
"""

import argparse
import re
from pathlib import Path

from scenet import ShotType, compile_source, default_library, render

CELL = 250
LABEL = 26
GUTTER = 8

#: The rungs worth looking at. `wide` and `medium_full` are omitted only to keep the
#: sheet readable -- they sit between neighbours that are already here.
SHOTS = (
    ShotType.EXTREME_CLOSE_UP,
    ShotType.BIG_CLOSE_UP,
    ShotType.CLOSE_UP,
    ShotType.MEDIUM_CLOSE_UP,
    ShotType.MEDIUM_SHOT,
    ShotType.FULL_SHOT,
    ShotType.LONG_SHOT,
)

INNER = re.compile(r"<svg[^>]*>(.*)</svg>", re.DOTALL)


def cell(reference: str, expression: str, shot: ShotType) -> str:
    """One panel's drawable content, without its document wrapper."""
    core = compile_source(
        f"{{panel: {{size: [1000, 1000]}}, camera: {{shot: {shot.value}}}, "
        f"cast: {{a: {{reference: {reference}, expression: {expression}}}}}}}"
    ).core
    match = INNER.search(render(core))
    return match.group(1) if match else ""


def sheet(reference: str) -> str:
    """Every expression this puppet declares, across the shot ladder."""
    expressions = sorted(default_library().get(reference).expressions)
    width = LABEL * 4 + len(SHOTS) * (CELL + GUTTER)
    height = LABEL * 2 + len(expressions) * (CELL + GUTTER)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#f4f3f1"/>',
        f'<text x="8" y="18" font-family="monospace" font-size="15">{reference}</text>',
    ]
    for column, shot in enumerate(SHOTS):
        x = LABEL * 4 + column * (CELL + GUTTER)
        parts.append(
            f'<text x="{x}" y="18" font-family="monospace" font-size="12">{shot.value}</text>'
        )

    for row, expression in enumerate(expressions):
        y = LABEL * 2 + row * (CELL + GUTTER)
        parts.append(
            f'<text x="8" y="{y + CELL / 2}" font-family="monospace" '
            f'font-size="13">{expression}</text>'
        )
        for column, shot in enumerate(SHOTS):
            x = LABEL * 4 + column * (CELL + GUTTER)
            parts.append(
                f'<svg x="{x}" y="{y}" width="{CELL}" height="{CELL}" viewBox="0 0 1000 1000">'
                f"{cell(reference, expression, shot)}</svg>"
            )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    """Write one contact sheet per puppet in the library."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=Path("out/faces.svg"))
    parser.add_argument(
        "--reference", help="one puppet to render; the default is every puppet shipped"
    )
    args = parser.parse_args()

    references = [args.reference] if args.reference else list(default_library().names())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for reference in references:
        path = (
            args.output
            if len(references) == 1
            else args.output.with_name(f"{args.output.stem}-{reference}{args.output.suffix}")
        )
        path.write_text(sheet(reference), encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
