# Drive Scenet from a model

No model knows Scenet from its training, and none will for a long time: a niche language is not
in anybody's weights. That is not a gap to wait out. It is how every new library works with
models today — you hand the model the language — and Scenet is built to be handed over.

There are four ways in, each reaching a different kind of client. The first reaches the most
clients; further down, the model can do more for itself. Use the lowest row your client
supports.

| Your client | What to use | Can it check its own work? |
|---|---|---|
| A chat app that cannot run code | [The spec pack](#a-chat-app-that-cannot-run-code) | No — you run `scenet check` and paste the result back |
| An agent that loads skills | [The skill](#an-agent-that-loads-skills) | Yes, through the shell |
| An MCP client | [The MCP server](#an-mcp-client) | Yes, through tool calls |
| An API with structured output | [The JSON Schema](#an-api-with-structured-output) | Shape only; still validate |

Whichever you use, the model never writes a coordinate. It writes who is in the panel and what
they say; the compiler decides where everything goes, and gives the same answer every time.

## A chat app that cannot run code

NotebookLM, the Gemini app, ChatGPT without tools: anything you can give a document to but that
cannot call out. This is where most people actually work, so it is the path most likely to be
used.

**The spec pack** is everything needed to write a panel, in one file — the language reference,
the comic-script format, the shipped characters, every diagnostic rule, the JSON Schema and the
whole gallery:

```
https://creatoan.github.io/scenet/scenet-spec.md
```

It is regenerated from the compiler's own sources on every documentation build, so it describes
the language the compiler actually accepts.

**Ask for a comic script, not YAML.** A `.script` is the format comic writers already use —
`PANEL 1`, `@shot:`, a character cue, the dialogue under it — which is far closer to what a model
writes unprompted than a YAML document is, and it has no indentation to get wrong. See
[write a panel as a comic script](write_a_comic_script.md).

### NotebookLM

As of 2026-08-25, NotebookLM has no code execution and no MCP client — the MCP servers built
around it query NotebookLM, rather than letting it call out. So it can develop a scenario well,
and cannot render any of it. The workflow:

1. Download `scenet-spec.md` and add it to a notebook as a source, alongside whatever you are
   developing the story from.
2. Ask for the scene as a Scenet comic script. Being specific about the constraints helps:

   ```
   Write this scene as a Scenet comic script (.script). Follow the spec pack exactly:
   declare the cast in the YAML front matter, cast only the puppets listed under
   Characters, and use only the poses and expressions each one declares. One PANEL per
   beat; name the shot with @shot:. Do not describe positions in prose — the compiler
   ignores prose.
   ```

3. Save the reply as `scene.script` and check it locally:

   ```bash
   scenet check scene.script
   ```

4. Paste anything it reports back into the chat. Each finding names its rule, its line and the
   fix, which is what a model needs to correct its own output. Repeat until it prints `ok`.
5. Compile:

   ```bash
   scenet build scene.script --strip
   ```

The same works in any chat app that accepts an uploaded file.

### Discovery, for crawlers

[`llms.txt`](https://creatoan.github.io/scenet/llms.txt) at the site root indexes the
documentation for retrieval systems, and points them at the spec pack.
[llms.txt](https://llmstxt.org/) is a community convention, not a standard with a body behind
it, so treat it as a distribution format rather than a protocol.

## An agent that loads skills

[Agent Skills](https://agentskills.io/) is an open format that many coding agents load: Claude
Code, Codex, GitHub Copilot, Cursor, Antigravity CLI and more. A skill is a folder with a
`SKILL.md` in it. Scenet's is
[`skills/scenet`](https://github.com/creatoan/scenet/tree/main/skills/scenet) in the
repository.

Only the skill's name and description are loaded up front; the rest is read when the skill is
used, so it costs almost nothing to have installed. `SKILL.md` holds the loop and the rules
generators break most often. The language reference, the characters and the diagnostic rules are
in `references/`, and the whole gallery is in `assets/`, read only when needed.

Copy the folder into wherever your agent reads skills from. For Claude Code that is
`~/.claude/skills/` for every project or `.claude/skills/` for one:

```bash
git clone --depth 1 https://github.com/creatoan/scenet
cp -r scenet/skills/scenet ~/.claude/skills/
```

Other clients document their own location. Gemini CLI stopped working for individual accounts on
2026-06-18; its successor, Antigravity CLI (`agy`), kept Agent Skills.

The skill runs `scenet check` and `scenet build` through the shell, so the agent needs the
package:

```bash
pip install scenet
```

## An MCP client

The [MCP server](../reference/mcp.md) is the only way in that closes the loop with nobody in the
middle: the model validates, reads its own errors, fixes them and renders, all through tool
calls. It needs the optional extra.

Most clients that launch a local server take a command and arguments. With
[uv](https://docs.astral.sh/uv/), nothing needs installing first:

```json
{
  "mcpServers": {
    "scenet": {
      "command": "uvx",
      "args": ["--from", "scenet[mcp]", "scenet", "mcp"]
    }
  }
}
```

In Claude Code:

```bash
claude mcp add scenet -- uvx --from 'scenet[mcp]' scenet mcp
```

Or install it and point the client at the command directly:

```bash
pip install 'scenet[mcp]'
scenet mcp
```

For a remote client, serve Streamable HTTP and connect to `http://HOST:PORT/mcp`:

```bash
scenet mcp --transport streamable-http --port 8765
```

It binds to `127.0.0.1` and has no authentication. Put it behind something that provides both
before exposing it further.

## An API with structured output

APIs that constrain a model's output to a JSON Schema — Gemini's `responseSchema`, for one —
can take the panel schema directly, so the model emits a document with no formatting risk at
all:

```bash
scenet schema -o panel.schema.json
```

The schema describes the syntax people write, not an intermediate form, and JSON is valid YAML:
save the output as `name.panel.yaml` and it compiles as it is.

Two caveats. **Schema conformance is not validity**: no schema can say that every actor id in
`staging` exists in `cast`, or that `left_of` does not loop, and those are exactly what a
generator gets wrong. Always run `scenet check`, or the `validate` tool, on the result. And
whether this schema suits a given provider's constrained decoding is untested here — providers
document that very large or deeply nested schemas may be rejected, and say little more. Measuring
that is tracked in [#11](https://github.com/creatoan/scenet/issues/11).
