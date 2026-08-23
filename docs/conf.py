# Sphinx configuration.
#
# Docs source stays Markdown (MyST) so that GitHub renders every page without a build
# step -- a reader who lands in the repository gets the documentation, not a pile of
# markup they have to compile.
#
# Warnings are errors in CI (`sphinx-build -W`). A broken cross-reference or a page
# missing from a toctree fails the build rather than quietly producing a worse site.

import sys
from datetime import UTC, datetime
from importlib.metadata import version as package_version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# -- Project ------------------------------------------------------------------

project = "Scenet"
# No personal name here or anywhere else in the repository, deliberately.
copyright = f"{datetime.now(UTC).year}, Scenet contributors"
author = "Scenet contributors"
release = package_version("scenet")
version = ".".join(release.split(".")[:2])

# -- General ------------------------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # understands the Google-style Args/Returns/Raises sections
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",  # every documented symbol links to its source
    "sphinx_autodoc_typehints",
    "sphinx_design",
    "sphinx_copybutton",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# Single backticks mean "code", matching how the docstrings read in source and in
# `help()`. Without this, rST's default turns them into title references.
default_role = "literal"

# -- MyST ---------------------------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "linkify",  # bare URLs become links
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

# linkify, left to itself, treats anything shaped like a domain as a link -- and `.id`,
# `.by`, `.at`, `.name`, `.ir` and `.cy` are all real top-level domains. So every
# `CoreActor.id` and `SayEvent.by` in the API reference became a hyperlink to somebody
# else's website. Fuzzy linking off: an explicit scheme is now required, which still
# covers every real URL in these documents.
myst_linkify_fuzzy_links = False

# -- autodoc ------------------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",  # source order is meaningful; alphabetical is not
    "show-inheritance": True,
    "undoc-members": False,
    # Pydantic adds a dozen machinery members to every model. They are noise in a
    # reference page and none of them are part of this project's API.
    "exclude-members": (
        "model_config,model_fields,model_computed_fields,model_post_init,"
        "model_construct,model_copy,model_dump,model_dump_json,model_json_schema,"
        "model_parametrized_name,model_rebuild,model_validate,model_validate_json,"
        "model_validate_strings,copy,dict,json,schema,schema_json,construct,"
        "parse_obj,parse_raw,parse_file,from_orm,update_forward_refs,validate"
    ),
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented_params"
autodoc_class_signature = "separated"
always_use_bars_union = True
typehints_use_signature = False
typehints_use_signature_return = False

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_rtype = False

# -- intersphinx ---------------------------------------------------------------
#
# Cross-project links, so a `dict[str, PuppetSpec]` in a signature reaches the standard
# library docs and a `ValidationError` reaches pydantic's. This is the thing Qt gets
# right that most Python projects skip: a reference that dead-ends at a type name you
# have to go and search for is half a reference.

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest", None),
    "shapely": ("https://shapely.readthedocs.io/en/stable", None),
}
# Resolving these needs network access. CI has it; a local build without it should warn
# rather than fail, so the timeout is short.
intersphinx_timeout = 10

# -- HTML ----------------------------------------------------------------------

html_theme = "pydata_sphinx_theme"
html_title = f"Scenet {version}"
html_copy_source = False
html_show_sourcelink = False

html_theme_options = {
    "github_url": "https://github.com/azias/scenet",
    "use_edit_page_button": False,
    "show_prev_next": True,
    "navigation_with_keys": True,
    "show_toc_level": 2,
    "header_links_before_dropdown": 6,
    "icon_links": [
        {
            "name": "PyPI",
            "url": "https://pypi.org/project/scenet/",
            "icon": "fa-solid fa-box",
        },
        {
            "name": "Playground",
            "url": "https://azias.github.io/scenet/playground/",
            "icon": "fa-solid fa-play",
        },
    ],
    "footer_start": ["copyright"],
    "footer_end": [],
}

html_context = {
    "github_user": "azias",
    "github_repo": "scenet",
    "github_version": "main",
    "default_mode": "auto",
}
