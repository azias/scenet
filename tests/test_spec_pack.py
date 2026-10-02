"""The spec pack, `llms.txt` and the skill folder -- how a model is told Scenet exists.

All three are generated from the same sources by `scripts/build_spec.py`: the language
reference, the shot-type table, the comic-script guide, the puppet library, the
diagnostic rule catalogue, the published JSON Schema and the gallery. Two copies are
committed, because neither an installed wheel nor a copied skill folder can read
`docs/` -- so the property these tests guard is the one that makes committing them
safe: **a committed copy can never be stale**, the same rule that keeps the editor's
schemas honest.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from scenet import __version__, default_library
from scenet.diagnostics import RULES, diagnose_source
from scenet.schema import panel_schema
from scenet.spec_pack import SPEC_PARTS, part, spec_pack_text

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "scenet"
GALLERY = ROOT / "examples" / "gallery"
REGENERATE = "run `uv run python scripts/build_spec.py`"


def _load_generator() -> ModuleType:
    """Import `scripts/build_spec.py`, which is a script rather than a package module."""
    path = ROOT / "scripts" / "build_spec.py"
    spec = importlib.util.spec_from_file_location("build_spec", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_spec"] = module
    spec.loader.exec_module(module)
    return module


build_spec = _load_generator()


@pytest.fixture(scope="module")
def pack() -> str:
    return build_spec.spec_pack()


def _manifest() -> list[dict[str, str]]:
    return yaml.safe_load((GALLERY / "manifest.yaml").read_text(encoding="utf-8"))["examples"]


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must open with YAML frontmatter"
    return yaml.safe_load(match.group(1))


class TestCommittedCopiesAreCurrent:
    """A stale copy would teach a model a language the compiler no longer accepts."""

    def test_every_committed_output_matches_a_fresh_build(self):
        for path, content in build_spec.committed_files().items():
            assert path.exists(), f"{path.relative_to(ROOT)} is missing; {REGENERATE}"
            assert path.read_bytes() == content, f"{path.relative_to(ROOT)} is stale; {REGENERATE}"

    def test_no_generated_directory_holds_a_leftover(self):
        """An example deleted from the gallery must not live on in the skill."""
        expected = set(build_spec.committed_files())
        for directory in build_spec.GENERATED_DIRECTORIES:
            for path in directory.rglob("*"):
                if path.is_file():
                    assert path in expected, (
                        f"{path.relative_to(ROOT)} is not generated any more; {REGENERATE}"
                    )

    def test_the_packaged_pack_is_the_generated_one(self, pack: str):
        assert spec_pack_text() == pack

    def test_generation_is_deterministic(self, pack: str):
        assert build_spec.spec_pack() == pack
        assert build_spec.llms_txt() == build_spec.llms_txt()


class TestSpecPack:
    def test_every_part_is_marked_once_and_in_order(self, pack: str):
        found = re.findall(r"<!-- scenet-spec:part=([a-z-]+) -->", pack)
        assert found == list(SPEC_PARTS)

    def test_parts_split_back_out(self, pack: str):
        for name in SPEC_PARTS:
            body = part(name)
            assert body.strip(), name
            assert "scenet-spec:part=" not in body
            assert f"<!-- scenet-spec:part={name} -->\n{body}" in pack

    def test_an_unknown_part_is_refused(self):
        with pytest.raises(KeyError, match="no part"):
            part("chapter-eleven")

    @pytest.mark.parametrize(
        ("name", "source"),
        [
            ("language", "docs/reference/language.md"),
            ("shot-types", "docs/reference/shot_types.md"),
            ("comic-script", "docs/howto/write_a_comic_script.md"),
        ],
    )
    def test_a_document_part_carries_its_source(self, name: str, source: str):
        first_heading = next(
            line
            for line in (ROOT / source).read_text(encoding="utf-8").splitlines()
            if line.startswith("# ")
        )
        assert first_heading in part(name)

    def test_the_schema_is_the_published_one(self):
        body = part("schema")
        block = re.search(r"```json\n(.*?)\n```", body, re.DOTALL)
        assert block, "the schema part must hold one fenced JSON block"
        assert json.loads(block.group(1)) == panel_schema()

    def test_every_rule_is_described(self):
        body = part("diagnostics")
        for name, rule in RULES.items():
            assert f"scenet/{name}" in body
            assert rule.help in body

    def test_every_puppet_pose_and_expression_is_listed(self):
        body = part("characters")
        library = default_library()
        for name in library.names():
            puppet = library.get(name)
            assert f"`{name}`" in body
            for pose in puppet.poses:
                assert f"`{pose}`" in body
            for expression in puppet.expressions:
                assert f"`{expression}`" in body

    def test_the_whole_gallery_is_included_in_manifest_order(self):
        body = part("gallery")
        positions = []
        for entry in _manifest():
            source = (GALLERY / entry["file"]).read_text(encoding="utf-8")
            assert entry["title"] in body
            assert source.strip() in body, entry["file"]
            positions.append(body.index(entry["file"]))
        assert positions == sorted(positions)

    def test_no_relative_link_survives(self, pack: str):
        """`shot_types.md` means nothing once the pack has left the repository."""
        links = re.findall(r"\]\(([^)\s]+)\)", pack)
        relative = [link for link in links if not re.match(r"[a-z]+:|#", link)]
        assert relative == []

    def test_relative_links_become_site_urls(self, pack: str):
        assert f"{build_spec.SITE}/reference/shot_types.html" in pack

    def test_it_names_no_version(self, pack: str):
        """A release bump must not make the committed copy stale."""
        assert __version__ not in pack

    def test_it_points_a_chat_model_at_the_comic_script(self):
        assert ".script" in part("preamble")


class TestLlmsTxt:
    """https://llmstxt.org: an H1, a blockquote, then sections of links."""

    def test_shape(self):
        lines = build_spec.llms_txt().splitlines()
        assert lines[0] == "# Scenet"
        assert next(line for line in lines[1:] if line).startswith("> ")

    def test_it_says_what_it_is(self):
        assert "community convention" in build_spec.llms_txt()

    def test_it_links_the_spec_pack(self):
        assert f"{build_spec.SITE}/scenet-spec.md" in build_spec.llms_txt()

    def test_every_documentation_link_names_a_real_page(self):
        for url in re.findall(r"\]\((\S+?)\)", build_spec.llms_txt()):
            if not url.startswith(build_spec.SITE) or not url.endswith(".html"):
                continue
            page = url.removeprefix(f"{build_spec.SITE}/").removesuffix(".html")
            assert (ROOT / "docs" / f"{page}.md").exists(), url

    def test_site_build_writes_both_files(self, tmp_path: Path):
        build_spec.write_site_files(tmp_path)
        assert (tmp_path / "llms.txt").read_text(encoding="utf-8") == build_spec.llms_txt()
        assert (tmp_path / "scenet-spec.md").read_text(encoding="utf-8") == spec_pack_text()


@pytest.fixture(scope="module")
def text() -> str:
    return (SKILL / "SKILL.md").read_text(encoding="utf-8")


class TestSkill:
    """https://agentskills.io/specification, checked 2026-10-01."""

    def test_name_matches_the_folder(self, text: str):
        name = _frontmatter(text)["name"]
        assert name == SKILL.name
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
        assert len(name) <= 64

    def test_description_is_within_bounds(self, text: str):
        description = _frontmatter(text)["description"]
        assert 0 < len(description) <= 1024

    def test_description_says_when_rather_than_what(self, text: str):
        """Progressive disclosure makes the description the whole discovery surface."""
        assert "Use when" in _frontmatter(text)["description"]

    def test_compatibility_is_within_bounds(self, text: str):
        assert 0 < len(_frontmatter(text)["compatibility"]) <= 500

    def test_only_specified_fields_are_used(self, text: str):
        allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
        assert set(_frontmatter(text)) <= allowed

    def test_body_stays_small(self, text: str):
        """The specification recommends under 500 lines; this is meant to be far under."""
        assert len(text.splitlines()) < 200

    def test_every_file_it_mentions_exists(self, text: str):
        mentioned = re.findall(
            r"`((?:references|assets)/[^`]+)`|\]\(((?:references|assets)/[^)]+)\)", text
        )
        paths = {first or second for first, second in mentioned}
        assert paths, "SKILL.md should point into references/ and assets/"
        for relative in paths:
            assert (SKILL / relative).exists(), relative

    def test_its_example_is_a_valid_panel(self, text: str):
        """The one example a model is most likely to copy had better compile."""
        (block,) = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
        assert diagnose_source(block, deep=True) == []

    def test_references_hold_the_language_and_assets_hold_the_gallery(self):
        assert (SKILL / "references" / "language.md").exists()
        for entry in _manifest():
            copy = SKILL / "assets" / "gallery" / entry["file"]
            assert copy.read_bytes() == (GALLERY / entry["file"]).read_bytes()
