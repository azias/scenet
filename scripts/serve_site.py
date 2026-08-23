"""Serve the assembled site locally, the way GitHub Pages will.

`python -m http.server` is not good enough here. It takes its MIME types from the
system, and on Windows that means `.mjs` and `.wasm` come back as `text/plain` --
which browsers refuse to execute as modules. The page then fails locally for a reason
that has nothing to do with the page.

Run from the repository root, after `scripts/build_site.py`:

    uv run python scripts/serve_site.py
"""

import argparse
import functools
import http.server
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent

# What GitHub Pages sends for these, and what browsers require.
EXTRA_TYPES = {
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".whl": "application/octet-stream",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    """A static handler that knows about the file types a modern page actually uses."""

    extensions_map: ClassVar[dict[str, str]] = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        **EXTRA_TYPES,
    }

    def end_headers(self) -> None:
        """Add the headers Pages sets, so local behaviour matches deployed behaviour."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Log only failures. A page that loads 200 assets should not print 200 lines."""
        status = str(args[1]) if len(args) > 1 else ""
        if not status.startswith("2"):
            super().log_message(format, *args)


def main() -> None:
    """Serve a directory over HTTP until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=str(ROOT / "site"))
    parser.add_argument("--port", type=int, default=8125)
    args = parser.parse_args()

    handler = functools.partial(Handler, directory=args.directory)
    # Threading matters. A single-threaded server deadlocks the moment a browser opens
    # several connections at once, which every modern page does -- and this one fetches
    # a 10 MB WebAssembly runtime alongside a dozen other assets.
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"serving {args.directory} at http://127.0.0.1:{args.port}/", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
