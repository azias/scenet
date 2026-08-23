# Install Scenet

## Requirements

Python **3.12 or newer**. No system libraries, no fonts to install, no configuration.

The 3.12 floor is not arbitrary — see [why 3.12](../explanation/design_decisions.md) if
you are curious, but the short version is that a bug only reproducible on older Pythons
made it worth testing against them.

## As a tool

To use the `scenet` command without adding it to a project:

```bash
uv tool install scenet
```

or

```bash
pipx install scenet
```

Either puts `scenet` on your PATH in its own isolated environment.

## As a library

```bash
uv add scenet
```

or

```bash
pip install scenet
```

## Verify

```bash
scenet --version
```

And from Python:

```python
import scenet

assert scenet.__version__
assert "compile_source" in scenet.__all__
```

## Types

Scenet ships a `py.typed` marker, so mypy, pyright, ty and basedpyright all read its
annotations directly from the installed package. There is no separate stubs package to
install and nothing to configure.

```python
from scenet import CompileResult, compile_source

result: CompileResult = compile_source("cast: {a: {reference: alice}}")
assert result.core.actors[0].id == "a"
```

## What gets installed with it

Scenet has eight runtime dependencies, all under permissive licenses, all checked by a
CI gate that fails if any dependency ever changes to a license outside the allowed set:

| Dependency | What for |
|---|---|
| `pydantic` | Validating the scene graph, and generating the JSON Schema |
| `pyyaml` | The YAML surface syntax |
| `kiwisolver` | The Cassowary constraint solver behind actor placement |
| `shapely` | Polygon intersection for the balloon occlusion cost |
| `fonttools` | Reading real font metrics, and extracting glyph outlines |
| `numpy` | A transitive requirement of shapely |
| `fonts`, `font-source-sans-pro` | The lettering font, as a dependency rather than a system lookup |

That last row is the unusual one. Determinism requires that text measures identically
everywhere, and a system font lookup cannot promise that — so the font arrives as an
ordinary package. It is under the SIL Open Font License, which is the one dependency
whose notice must travel with redistribution; see `THIRD_PARTY_NOTICES.md`.

## Without installing anything

The [playground](https://azias.github.io/scenet/playground/) runs the same compiler in
your browser under WebAssembly. It installs the real wheel, so it is not a
reimplementation and cannot drift from what the command line does.
