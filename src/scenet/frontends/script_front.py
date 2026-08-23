"""A frontend for comic script, the format writers already use.

Checked before building this: Fountain has no native panel, caption or SFX support,
and there is no standardised comic script format at all. But the informal industry
convention is stable across publishers -- `PANEL 1`, a prose description, a character
cue in capitals, the dialogue beneath it -- so that is what this parses.

**The honest limitation.** A prose description like "Alice and Bob face each other on
a rainy street corner" cannot be compiled. Turning that into staging needs natural
language understanding, and guessing would produce panels that are confidently wrong
-- far worse than refusing. So descriptions are preserved but not interpreted, and
anything the compiler must know is declared explicitly: cast and staging in a
front-matter block, per-panel settings as `@` directives.

    ---
    cast:
      ALICE: {reference: alice, at: left_third}
      BOB:   {reference: bob,   at: right_third}
    staging:
      - ALICE left_of BOB
    ---

    PANEL 1
    @shot: full_shot
    Alice and Bob face each other on a rainy street corner.

    ALICE
    You forgot your umbrella!

    BOB (whisper)
    I know.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from scenet.compose import merge
from scenet.errors import PanelSyntaxError, ScriptSyntaxError
from scenet.frontends.common import normalise, summarise
from scenet.ir import BalloonKind, PanelIR

# Leading blank lines are tolerated. A script pasted out of an editor or produced by a
# templating step very often starts with one, and refusing it would be a baffling
# failure for a file that looks identical to a working one.
FRONT_MATTER = re.compile(r"^\s*---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
PANEL_HEADING = re.compile(r"^PANEL\s+(\S+)\s*:?\s*$", re.IGNORECASE)
PAGE_HEADING = re.compile(r"^PAGE\s+(\S+)\s*:?\s*$", re.IGNORECASE)
DIRECTIVE = re.compile(r"^@(\w+)\s*:\s*(.+)$")
# A cue is a character name in capitals, optionally followed by a parenthetical.
CUE = re.compile(r"^([A-Z][A-Z0-9 _'.-]*?)\s*(?:\(([^)]*)\))?\s*:?\s*$")

# Parentheticals a letterer would act on. Anything else is a performance note for the
# artist and is not something the compiler can represent.
KIND_MODIFIERS = {
    "whisper": BalloonKind.WHISPER,
    "whispering": BalloonKind.WHISPER,
    "shout": BalloonKind.SHOUT,
    "shouting": BalloonKind.SHOUT,
    "yell": BalloonKind.SHOUT,
    "yelling": BalloonKind.SHOUT,
    "thought": BalloonKind.THOUGHT,
    "thinking": BalloonKind.THOUGHT,
}

# Directives that name a camera property rather than a top-level panel key.
CAMERA_DIRECTIVES = {"shot", "angle"}


@dataclass
class _PanelDraft:
    """One panel being accumulated as the script is read.

    A typed accumulator rather than a bare dict: the script body contributes several
    kinds of thing -- dialogue, directives, prose -- and keeping them apart until the
    end makes it obvious that prose never reaches the compiler.
    """

    settings: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    dialogue: list[dict[str, Any]] = field(default_factory=list)
    description: list[str] = field(default_factory=list)

    def as_document(self) -> dict[str, Any]:
        """The parts a panel can actually be compiled from.

        `description` is authorial prose the compiler cannot act on, so it is left out
        rather than being passed along and rejected as an unknown key.
        """
        document: dict[str, Any] = dict(self.settings)
        if self.camera:
            document["camera"] = {**document.get("camera", {}), **self.camera}
        document["script"] = self.dialogue
        return document


def _looks_like_a_cue(line: str) -> bool:
    """Whether a line is a character cue rather than prose.

    Cues are conventionally set in capitals, which is the only signal available, so
    the line must also be short to avoid mistaking a shouted description for a cue.

    Only the *name* is tested for capitals. The parenthetical is a performance note
    and is conventionally lower case -- `BOB (whisper)` is a cue, and testing the
    whole line would silently drop every piece of modified dialogue in the script.
    """
    if not line or len(line) > 40:
        return False
    match = CUE.match(line)
    if not match:
        return False
    letters = [character for character in match.group(1) if character.isalpha()]
    return bool(letters) and all(character.isupper() for character in letters)


def _split_front_matter(text: str, source: Path | None) -> tuple[dict[str, Any], str]:
    """Peel off the YAML front-matter block, if there is one."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ScriptSyntaxError(f"invalid front matter: {exc}", source=source) from exc
    if loaded is None:
        return {}, text[match.end() :]
    if not isinstance(loaded, dict):
        raise ScriptSyntaxError("front matter must be a mapping", source=source)
    return loaded, text[match.end() :]


def _read_panels(body: str, source: Path | None) -> dict[str, _PanelDraft]:
    """Walk the script body, accumulating one draft per PANEL heading."""
    panels: dict[str, _PanelDraft] = {}
    current: _PanelDraft | None = None
    pending_cue: tuple[str, BalloonKind] | None = None

    for number, raw in enumerate(body.splitlines(), start=1):
        line = raw.strip()

        if not line:
            # A blank line ends a dialogue block, so a cue never reaches across one
            # and picks up the next panel's description as its speech.
            pending_cue = None
            continue

        if PAGE_HEADING.match(line):
            # Page structure is recognised so that a real script parses, but page
            # composition is out of scope and it carries no meaning yet.
            continue

        panel_match = PANEL_HEADING.match(line)
        if panel_match:
            current = _PanelDraft()
            panels[panel_match.group(1)] = current
            pending_cue = None
            continue

        if current is None:
            raise ScriptSyntaxError(
                f"line {number}: content before the first PANEL heading: {line!r}", source=source
            )

        if _apply_directive(line, current, number, source):
            continue

        if pending_cue is not None:
            speaker, kind = pending_cue
            current.dialogue.append({"say": {"by": speaker, "text": line, "kind": kind.value}})
            pending_cue = None
            continue

        pending_cue = _read_cue(line)
        if pending_cue is None:
            # Prose. Kept for tooling and round-tripping, never interpreted.
            current.description.append(line)

    return panels


def _apply_directive(line: str, draft: _PanelDraft, number: int, source: Path | None) -> bool:
    """Handle an `@key: value` line. Returns whether the line was one."""
    directive = DIRECTIVE.match(line)
    if not directive:
        return False
    key, value = directive.group(1), directive.group(2).strip()
    if key in CAMERA_DIRECTIVES:
        draft.camera[key] = value
        return True
    try:
        draft.settings[key] = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise ScriptSyntaxError(
            f"line {number}: cannot read directive '@{key}': {exc}", source=source
        ) from exc
    return True


def _read_cue(line: str) -> tuple[str, BalloonKind] | None:
    """Parse a character cue, or return None if the line is not one."""
    if not _looks_like_a_cue(line):
        return None
    cue = CUE.match(line)
    if cue is None:  # pragma: no cover -- _looks_like_a_cue already matched
        return None
    modifier = (cue.group(2) or "").strip().lower()
    return cue.group(1).strip(), KIND_MODIFIERS.get(modifier, BalloonKind.SPEECH)


def parse_script(text: str, *, source: Path | None = None) -> dict[str, PanelIR]:
    """Parse comic script into one validated panel per PANEL heading."""
    # Normalise line endings first. Python's text mode does this silently when reading
    # a file, which is why it took a browser to notice: the playground hands over the
    # bytes it was given, and a script saved by a Windows editor -- or pasted from one --
    # arrives with CRLF. The front-matter pattern then does not match, the `---` fence is
    # read as prose, and the whole document is rejected for having content before the
    # first PANEL heading. Anything that reaches here as a string gets the same treatment
    # a file would have had.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    front_matter, body = _split_front_matter(text, source)
    panels = _read_panels(body, source)

    if not panels:
        raise ScriptSyntaxError("no PANEL headings found", source=source)

    result: dict[str, PanelIR] = {}
    for name, draft in panels.items():
        combined = merge(front_matter, draft.as_document())
        try:
            result[name] = PanelIR.model_validate(normalise(combined))
        except PanelSyntaxError as exc:
            raise ScriptSyntaxError(f"in PANEL {name}: {exc}", source=source) from exc
        except ValidationError as exc:
            raise ScriptSyntaxError(f"in PANEL {name}: {summarise(exc)}", source=source) from exc
    return result


def load_script(path: Path) -> dict[str, PanelIR]:
    """Read and validate a comic script from disk.

    Args:
        path: A `*.script` file in the comic-script format writers already use.

    Returns:
        Panel name to scene graph, in the order the panels appear.

    Raises:
        OSError: The file cannot be read.
        ScriptSyntaxError: The script cannot be parsed -- dialogue before the first
            `PANEL` heading, or no `PANEL` headings at all.
    """
    return parse_script(path.read_text(encoding="utf-8"), source=path)
