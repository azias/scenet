"""Make the documentation part of the test suite.

Sybil collects every fenced ``python`` block in the Markdown under `docs/` and in
`README.md` and executes it during the normal pytest run. That is the mechanism behind
one of this project's rules: **a documented example that does not run is a failing
build**.

It is aimed squarely at the commonest complaint about Python library documentation --
snippets that omit their imports, or that were correct against a version three releases
ago. Neither can survive here, because the example in the docs is the example that ran.

A block that genuinely cannot execute (a shell transcript, a deliberately broken sample)
is marked with an HTML comment:

    <!--- skip: next -->
"""

from sybil import Sybil
from sybil.parsers.markdown import PythonCodeBlockParser, SkipParser

pytest_collect_file = Sybil(
    parsers=[PythonCodeBlockParser(), SkipParser()],
    patterns=["*.md"],
).pytest()
