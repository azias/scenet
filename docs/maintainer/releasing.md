# Releasing

A release is a **git tag**. Everything else follows from it automatically.

That is not a Scenet invention: a GitHub Release is by definition metadata attached to a
tag, and the Python Packaging Authority's own publishing guide triggers on exactly this.
The tag is the single source of truth.

## Cutting a release

Four commands.

```bash
uv version --bump minor
```

`major`, `minor` or `patch`. This edits `project.version` in `pyproject.toml` and nothing
else. Check what it will do first with `--dry-run`.

Then write the changelog section. `CHANGELOG.md` follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); rename the `## [Unreleased]`
heading to `## [0.2.0] - 2026-08-23` and start a fresh `Unreleased` above it.

**Write it for people.** These become the release notes verbatim. A list of commit
subjects is not release notes — it is a list of commit subjects.

```bash
git commit -am "chore: release 0.2.0"
git tag v0.2.0
git push origin main v0.2.0
```

Pushing the tag is what starts everything.

## What happens next

```
push tag v0.2.0
      │
      ├─ verify    tag == project.version?
      │            CHANGELOG has a [0.2.0] section?
      │            format, lint, types, full test suite
      │
      ├─ build     uv build → sdist + wheel
      │            install the wheel in a clean environment and exercise it
      │
      ├─ extension npm ci → tsc → vsce package → scenet.vsix
      │
      ├─ publish   ⏸ waits for you to approve the `pypi` environment
      │            → pypi.org, via Trusted Publishing, with attestations
      │
      └─ release   → GitHub Release, notes from CHANGELOG,
                     sdist + wheel + vsix attached
```

**Everything that can fail runs before anything is published.** PyPI never allows
re-uploading a version — not after a delete, not ever — so a half-finished release burns
that number permanently. The `verify` job exists to make that impossible.

You will get an email when the run reaches `publish`. Open it, click **Review
deployments**, tick `pypi`, **Approve and deploy**. That click is the last gate between a
tag and PyPI.

## Rehearsing first

Before the *first* real release, or any release you are nervous about, run the **TestPyPI
rehearsal** workflow from the Actions tab. It publishes to `test.pypi.org` — a throwaway
instance of the same software, periodically wiped — and then installs the result back in a
clean environment to prove the artifact works.

TestPyPI also refuses duplicate versions, so pass a `dev1`, `dev2`… suffix when you
re-rehearse the same version.

## If something goes wrong

**The tag does not match `project.version`.** `verify` fails before anything is published.
Delete the tag, fix, re-tag:

```bash
git tag -d v0.2.0 && git push origin :refs/tags/v0.2.0
```

**Published to PyPI, then found a bug.** You cannot replace it. Yank the release on PyPI —
which hides it from new installs while leaving it available to anyone who pinned it — and
release a patch version. Yanking is the recovery mechanism; deleting is not.

**The GitHub Release step failed after PyPI succeeded.** The package is out. Re-run just
that job from the Actions tab; it is idempotent apart from the release already existing.

## Versioning

[Semantic versioning](https://semver.org/spec/v2.0.0.html), applied to two things:

- **The Python API** — everything in `scenet.__all__`. Names outside it are internal and
  may change in a minor release.
- **The language** — a construct that stops compiling is a major change. New optional keys
  are minor.

`format_version` inside a Panel Core document is separate, and bumped only when the shape
of that document changes incompatibly.

While the version is below `1.0.0`, minor versions may break things. That is what being
below 1.0 means, and the status is [alpha](../explanation/status.md) for a reason.

## What is not automated, deliberately

Nothing decides on its own that a release should happen. There is no bot reading commit
messages and opening a release pull request.

That is a choice. Conventional-commit automation trades a small amount of typing for a
strict format on every commit message forever, and for a project of this size the
arithmetic does not work out. Deciding that a release is worth making is a judgement, and
it is a cheap one to make by hand.
