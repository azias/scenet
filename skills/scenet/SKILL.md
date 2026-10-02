---
name: scenet
description: >-
  Writes and compiles Scenet documents: semantic descriptions of a comic panel (who is
  in it, how they stand, the camera shot, what they say) that a deterministic compiler
  turns into SVG, with no image model involved. Use when the user wants a comic panel,
  comic strip, storyboard frame or a scene of characters talking drawn as SVG; when
  they hand you a comic script (PAGE ONE, PANEL 1, character cues and dialogue) to turn
  into pictures; or when editing *.panel.yaml, *.scene.yaml or *.script files. Not for
  photorealistic, painted or freely drawn images.
license: 0BSD
compatibility: >-
  Writing a document needs nothing. Checking and compiling it needs Python 3.12+ and the
  scenet package (pip install scenet); the optional MCP server needs pip install
  'scenet[mcp]'.
---

# Scenet

> Scenet is deliberately AI-generated: the compiler, its documentation and this skill
> are almost entirely written by AI under human direction and review.

Scenet compiles a description of **what is in** a comic panel into SVG. You never place
anything — no coordinates, no pixel sizes, no balloon positions. The compiler decides
every one of them, deterministically: the same document always gives the same picture.

## Choose a format

- **YAML** — `name.panel.yaml`, or `name.scene.yaml` for several panels — when you need
  the whole language: camera angles, settings, captions, gaze, placement hints.
  Reference: `references/language.md`.
- **Comic script** — `name.script` — when the user thinks in script form or the story
  comes first. Reference: `references/comic-script.md`.

Start from the closest worked example in `assets/gallery/` rather than from nothing;
`assets/gallery/manifest.yaml` lists them with titles. Every one is known to compile.

## The loop

1. Write the document.
2. Run `scenet check FILE`. It reports every fault at once, as
   `FILE:LINE:COLUMN: RULE: MESSAGE`; add `--format sarif` for JSON.
3. Fix every finding and check again, until it prints `FILE: ok`. What each rule means,
   and its fix: `references/diagnostics.md`.
4. Run `scenet build FILE` to write the SVG. `--core` also writes the resolved layout as
   JSON; `--debug` writes an overlay showing why things went where they did.

`scenet check --deep` also runs the solver, which catches layout and balloon-placement
failures the cheap check cannot see.

When the Scenet MCP tools are connected — `get_spec`, `list_puppets`, `validate`,
`compile`, `render` — use them instead of the shell. They run the same checks, on text
rather than files.

If `scenet` is not installed: `pip install scenet`, or run it once with
`uvx scenet check FILE`.

## Rules generators break

- **Every actor id in `staging` and `script` must be a key of `cast`.** Ids are
  case-sensitive.
- **`reference` must be a shipped puppet, and `pose` and `expression` must be names it
  declares.** They are listed in `references/characters.md`. Do not invent them.
- **Two figures need a left-to-right order**: `at:` (`left_third`, `center`,
  `right_third`, `left_edge`, `right_edge`) or `a left_of b` in `staging`. There is no
  "beside".
- **Script order is reading order.** A balloon can never sit above-and-left of the one
  before it, so write lines in the order they are read.
- **Shots are named, never percentages**: `references/shot-types.md`.
- **Unknown keys are errors**, not ignored.
- **In a comic script, prose lines are kept and never interpreted.** Who stands where,
  and who looks at whom, goes in the front matter.

## A minimal panel

```yaml
panel: {size: [800, 600]}
camera: {shot: medium_shot}
cast:
  alice: {reference: alice, pose: pointing, at: left_third}
  bob:   {reference: bob,   at: right_third, facing: left}
staging:
  - alice left_of bob
  - alice looking_at bob
script:
  - say: {by: alice, text: "You forgot your umbrella!"}
  - say: {by: bob,   text: "I know."}
```
