r"""Extract one version's section from CHANGELOG.md.

The release workflow uses this to turn the changelog into release notes, and to check
before publishing anything that the section exists at all.

This was inline `awk` in the workflow first. It silently produced nothing, because a
dynamically built `\\[` in an awk regex is treated as a plain `[`, which opens a character
class. The failure was invisible: the release would have been created with empty notes.
A script can be tested; a line of awk buried in YAML cannot.

    uv run python scripts/changelog_section.py 0.1.0
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def section(text: str, version: str) -> str | None:
    r"""Return the body of one version's section, or `None` if there is no such section.

    Args:
        text: The whole changelog.
        version: A version without a leading `v`, e.g. `0.1.0`.

    Returns:
        Everything between that version's heading and the next `## [` heading, stripped
        of surrounding blank lines. `None` when the heading is absent.

    Example:
        >>> from scripts.changelog_section import section
        >>> doc = "# Changelog\\n\\n## [1.0.0]\\n\\nDid a thing.\\n\\n## [0.9.0]\\n\\nOlder.\\n"
        >>> section(doc, "1.0.0")
        'Did a thing.'
        >>> section(doc, "2.0.0") is None
        True
    """
    heading = f"## [{version}]"
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(heading):
            body: list[str] = []
            for following in lines[index + 1 :]:
                if following.startswith("## ["):
                    break
                body.append(following)
            return "\n".join(body).strip("\n")
    return None


def main() -> None:
    """Print one version's changelog section, or fail with a message naming the gap."""
    parser = argparse.ArgumentParser(description="Extract a version's changelog section.")
    parser.add_argument("version", help="version without a leading v, e.g. 0.1.0")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    parser.add_argument("--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args()

    found = section(args.changelog.read_text(encoding="utf-8"), args.version)
    if found is None or not found.strip():
        print(
            f"::error::{args.changelog.name} has no '## [{args.version}]' section, "
            "or it is empty. Release notes come from there.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.output is None:
        # Written as bytes rather than printed. The changelog contains arrows and dashes,
        # and a Windows console defaults to cp1252, where printing them raises
        # UnicodeEncodeError. CI would never have seen it; a maintainer would have.
        sys.stdout.buffer.write((found + "\n").encode("utf-8"))
    else:
        args.output.write_text(found + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
