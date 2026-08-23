# Third-Party Notices

Scenet is distributed under the [BSD Zero Clause License](LICENSE) (0BSD). It incorporates and depends on the
third-party components listed below.

## Fonts

### Source Sans Pro

Licensed under the [SIL Open Font License 1.1][ofl]. Copyright Adobe Systems Incorporated.

The OFL explicitly permits bundling and redistributing a font alongside software, provided the
copyright notice and license accompany it. Here the font is not vendored into this repository at
all: it arrives through the `font-source-sans-pro` package as an ordinary declared dependency, so
`uv.lock` pins it and the license travels with the package.

That indirection is deliberate. The compiler measures glyph advance widths to size speech balloons,
and measurement must agree exactly with rendering or the output stops being deterministic. Looking
up a system font would make the result depend on whichever machine compiled it, which is precisely
what a reproducible compiler cannot allow.

Source Sans Pro is a legible humanist sans rather than a comic lettering face. That is a placeholder
choice: style belongs to the deferred interpretation layer, and the font is configurable.

[ofl]: https://openfontlicense.org/

## Runtime dependencies

All runtime dependencies are permissively licensed. CI enforces this on every build via
`pip-licenses` against an allowlist, so this table cannot silently drift.

| Package | Purpose | License |
|---|---|---|
| `pydantic` | Runtime validation of untrusted panel input | MIT |
| `pyyaml` | Parsing the surface syntax | MIT |
| `kiwisolver` | Cassowary constraint solver for actor placement | BSD |
| `shapely` | Occlusion polygons, free-space and intersection tests | BSD |
| `fonttools` | Glyph advance widths for balloon sizing | MIT |
| `numpy` | Numeric arrays in the geometry layer | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `typing-extensions` | Typing backports pulled in by pydantic | PSF-2.0 |
| `annotated-types`, `typing-inspection` | pydantic support packages | MIT |

License strings above are reproduced exactly as each package declares them in its metadata, which
is what the CI gate compares against.

## Prior art used as reference, not as code

### Comic Chat (Microsoft Research, 1996)

The algorithms for automatic character placement, camera zoom selection, balloon construction and
reading-order enforcement are informed by Kurlander, Skelly and Salesin, *Comic Chat*, SIGGRAPH '96.

**Nothing from that project is vendored here — neither code nor artwork.** The implementation is
written from the published paper. This is deliberate: although the
[source release](https://github.com/microsoft/comic-chat) is MIT-licensed, the bundled character
artwork is the work of an individual artist and was not confirmed to fall under the code license.
Scenet's skeletal-puppet approach requires none of it, so the cleanest position is to take the ideas
from the literature and write the code from scratch.

### Other influences

Design influences that contributed concepts but no code: Pixar's
[OpenUSD](https://openusd.org/) (composition arcs — references, variant sets, sparse overrides),
[Vega-Lite](https://vega.github.io/vega-lite/) (a high-level grammar compiling to a lower-level one),
the Visual Genome scene-graph vocabulary, and Kress & van Leeuwen's *Reading Images* (gaze vectors
as compositional structure). See [the prior art notes](docs/explanation/prior_art.md) for
the full assessment.
