"""Scenet -- a semantic DSL for comic panels, compiled to SVG.

The compiler is deterministic: the same source always produces byte-identical output.
No generative image model is involved at any stage.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("scenet")
except PackageNotFoundError:  # pragma: no cover -- only when running from a source tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
