"""Assemble the GitHub Pages site.

One Pages site per repository, so the documentation, the playground and the published
schemas share an origin:

    site/                     documentation (Sphinx)
    site/playground/          the browser playground (Vite)
    site/schemas/*.json       the JSON Schemas, at stable URLs

The schemas are served from a stable URL on purpose. Any editor with a YAML language
server can validate a panel document against them with a one-line comment and no
Scenet-specific plugin -- see docs/howto/editor_support.md.

Run from the repository root:

    uv run python scripts/build_site.py
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DOCS_BUILD = ROOT / "docs" / "_build" / "html"
PLAYGROUND = ROOT / "playground"
SCHEMAS = ROOT / "editor" / "schemas"


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    """Run a command, echoing it first so a CI log shows what happened.

    Args:
        command: Program and arguments.
        cwd: Directory to run in.
        env: Extra environment variables, merged over the current environment.

    Raises:
        SystemExit: The command failed.
    """
    print(f"$ {' '.join(command)}  (in {cwd.relative_to(ROOT) or '.'})", flush=True)
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(command, cwd=cwd, env=merged, check=False)  # noqa: S603
    if result.returncode != 0:
        sys.exit(result.returncode)


def build_docs() -> None:
    """Build the documentation with warnings as errors."""
    run(
        [
            sys.executable,
            "-m",
            "sphinx",
            "-W",
            "--keep-going",
            "-b",
            "html",
            "docs",
            str(DOCS_BUILD),
        ],
        cwd=ROOT,
    )


def build_playground(base: str) -> None:
    """Build the playground, told where it will be served from.

    Args:
        base: URL path the playground is served under, with leading and trailing
            slashes -- `/scenet/playground/` on GitHub Pages.
    """
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    # `npm ci` wipes node_modules, which fails on Windows if anything is holding a file
    # in it -- a running dev server, most often. CI always starts clean, so only install
    # when there is nothing there.
    if not (PLAYGROUND / "node_modules").is_dir():
        run([npm, "ci"], cwd=PLAYGROUND)
    run([npm, "run", "build"], cwd=PLAYGROUND, env={"SCENET_BASE": base})


def assemble() -> None:
    """Copy the built pieces into `site/`."""
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(DOCS_BUILD, SITE)
    shutil.copytree(PLAYGROUND / "dist", SITE / "playground")

    schemas = SITE / "schemas"
    schemas.mkdir(parents=True, exist_ok=True)
    for name in ("panel.schema.json", "scene.schema.json"):
        shutil.copyfile(SCHEMAS / name, schemas / name)

    # Sphinx writes .nojekyll itself for _static/, but Pages also needs it at the root
    # or every directory beginning with an underscore is silently dropped.
    (SITE / ".nojekyll").touch()

    total = sum(path.stat().st_size for path in SITE.rglob("*") if path.is_file())
    files = sum(1 for path in SITE.rglob("*") if path.is_file())
    print(f"\nsite/: {files} files, {total / 1e6:.1f} MB")


def main() -> None:
    """Build the documentation and the playground, then assemble them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="/",
        help="URL path the playground is served under (default: / for local preview)",
    )
    parser.add_argument("--skip-docs", action="store_true", help="reuse an existing docs build")
    parser.add_argument(
        "--skip-playground", action="store_true", help="reuse an existing playground build"
    )
    args = parser.parse_args()

    if not args.skip_docs:
        build_docs()
    if not args.skip_playground:
        build_playground(f"{args.base.rstrip('/')}/playground/")
    assemble()


if __name__ == "__main__":
    main()
