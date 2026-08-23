# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project scaffolding: uv-managed toolchain pinned to Python 3.14, ruff, ty, pytest.
- CI with blocking gates for tests, lint, formatting, types and dependency licenses.
- Language specification and knowledge base documenting the prior art the design draws on.

- Scene-graph IR with strict validation, and a YAML frontend.
- Skeletal puppets: a pose is a set of joint angles, so the solver sees only a geometric
  contract and never artwork.
- Camera framing from crop landmarks, with the camera retreating when a cast will not fit.
- Constraint-based actor placement via Cassowary, resolving anchor conflicts by priority.
- Text measurement from real font metrics, with line breaking scored on lettering craft.
- Balloon placement with face avoidance, reading-order enforcement and tail routing.
- SVG emitter using glyph outlines, a diagnostic overlay, and the `scenet build` command.
- Multi-panel documents with USD-style `over` sparse override, so a panel states only
  what changed from the one before.
- A comic-script frontend, so panels can be written in the format writers already use.
- A minimal strip emitter for reading a sequence in order.

Single panels compile end to end — see the README for current status.
