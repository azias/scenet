"""The release workflows hold credentials, so their shape is tested.

A workflow is the one place in this repository that can publish to something other
people read. Nothing here runs it -- that needs GitHub -- but the properties that keep
it safe are properties of the file, and a file can be checked: the credential is minted
by one job and no other, nothing installs an unverified binary, and every action is
pinned to a commit rather than to a tag somebody can move.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _load(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads a bare `on` as the boolean True, which is how PyYAML sees it.
    return workflow.get("on") or workflow[True]


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path: Path):
    """A tag can be re-pointed at different code by whoever controls the repository."""
    text = path.read_text(encoding="utf-8")
    for use in re.findall(r"^\s*-?\s*uses:\s*(\S+)", text, re.MULTILINE):
        if use.startswith("./"):
            continue
        assert re.search(r"@[0-9a-f]{40}$", use), f"{path.name}: {use} is not pinned to a SHA"


class TestRegistryWorkflow:
    """Publishing to the MCP registry, by OIDC, from the repository's own identity."""

    @pytest.fixture(scope="class")
    @classmethod
    def registry(cls) -> dict[Any, Any]:
        return _load("registry.yml")

    def test_it_can_be_run_by_hand_and_called_by_the_release(self, registry: dict[Any, Any]):
        """By hand because the first release needs listing without re-tagging it."""
        triggers = _triggers(registry)
        assert set(triggers) == {"workflow_dispatch", "workflow_call"}
        assert "tag" in triggers["workflow_dispatch"]["inputs"]
        assert "tag" in triggers["workflow_call"]["inputs"]

    def test_nothing_is_granted_workflow_wide(self, registry: dict[Any, Any]):
        assert registry["permissions"] == {"contents": "read"}

    def test_the_credential_is_minted_by_one_job_only(self, registry: dict[Any, Any]):
        minting = [
            name
            for name, job in registry["jobs"].items()
            if (job.get("permissions") or {}).get("id-token") == "write"
        ]
        assert minting == ["publish"]

    def test_the_tool_is_pinned_and_checksummed(self, registry: dict[Any, Any]):
        """The binary runs with the OIDC credential in reach, so it is not `latest`."""
        (step,) = [
            s
            for s in registry["jobs"]["publish"]["steps"]
            if "mcp-publisher" in s.get("name", "") and "Install" in s["name"]
        ]
        assert re.fullmatch(r"v\d+\.\d+\.\d+", step["env"]["VERSION"])
        assert re.fullmatch(r"[0-9a-f]{64}", step["env"]["SHA256"])
        assert "releases/download/${VERSION}/" in step["run"]
        assert "/releases/latest/" not in step["run"]
        assert "sha256sum --check" in step["run"]
        assert step["run"].index("sha256sum --check") < step["run"].index("tar ")

    def test_it_checks_before_it_publishes(self, registry: dict[Any, Any]):
        script = "\n".join(step.get("run", "") for step in registry["jobs"]["publish"]["steps"])
        order = [
            script.index(command)
            for command in (
                "./mcp-publisher validate",
                "./mcp-publisher login github-oidc",
                "./mcp-publisher publish",
            )
        ]
        assert order == sorted(order)

    def test_it_never_relies_on_a_dry_run_flag(self, registry: dict[Any, Any]):
        """`publish` has no such flag, so one would be ignored and the publish would happen."""
        script = "\n".join(step.get("run", "") for step in registry["jobs"]["publish"]["steps"])
        assert "--dry-run" not in script

    def test_it_waits_for_the_package_it_points_at(self, registry: dict[Any, Any]):
        """The registry checks the PyPI description, so the version has to be there."""
        script = "\n".join(step.get("run", "") for step in registry["jobs"]["publish"]["steps"])
        assert "pypi.org/pypi/scenet/" in script


class TestReleaseWorkflowCallsIt:
    @pytest.fixture(scope="class")
    @classmethod
    def release(cls) -> dict[Any, Any]:
        return _load("release.yml")

    def test_it_is_opt_in(self, release: dict[Any, Any]):
        """OIDC login for an org namespace is unproven until it has worked once."""
        assert "vars.MCP_REGISTRY_PUBLISH == 'true'" in release["jobs"]["registry"]["if"]

    def test_it_runs_after_everything_else_and_blocks_nothing(self, release: dict[Any, Any]):
        job = release["jobs"]["registry"]
        assert set(job["needs"]) == {"publish", "github-release"}
        for name, other in release["jobs"].items():
            assert "registry" not in (other.get("needs") or []), name

    def test_it_calls_the_reusable_workflow_with_the_tag(self, release: dict[Any, Any]):
        job = release["jobs"]["registry"]
        assert job["uses"] == "./.github/workflows/registry.yml"
        assert job["with"]["tag"] == "${{ github.ref_name }}"

    def test_the_credential_is_granted_to_that_job_only(self, release: dict[Any, Any]):
        assert release["permissions"] == {"contents": "read"}
        job = release["jobs"]["registry"]
        assert job["permissions"]["id-token"] == "write"
