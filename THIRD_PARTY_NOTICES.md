# Third-Party Notices

Scenet is distributed under the [BSD Zero Clause License](LICENSE) (0BSD). It incorporates and depends on the
third-party components listed below.

## Bundled assets

### Comic Neue (font)

Licensed under the [SIL Open Font License 1.1][ofl]. Copyright The Comic Neue Project Authors.

The OFL explicitly permits bundling and redistribution alongside software, provided the copyright
notice and license accompany the font. The full license text ships as `fonts/LICENSE-OFL.txt`. The
font is redistributed unmodified, so the Reserved Font Name provision is not engaged.

The font is bundled rather than merely referenced because the compiler measures glyph advance
widths to size speech balloons. Measurement and rendering must agree exactly for output to be
deterministic, which is only guaranteed if the font is fixed and shipped with the compiler.

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
as compositional structure). See [the prior art notes](docs/knowledge_base/domain/prior_art.md) for
the full assessment.
