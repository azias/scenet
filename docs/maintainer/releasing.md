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

`main` is protected, so the version bump and changelog go through a pull request like
anything else:

```bash
git switch -c release/0.2.0
git commit -am "chore: release 0.2.0"
git push -u origin release/0.2.0
gh pr create --fill && gh pr checks --watch
gh pr merge --squash --delete-branch
```

Then tag the merged commit on `main`:

```bash
git switch main && git pull
git tag -a v0.2.0 -m "scenet 0.2.0"
git push origin v0.2.0
```

Pushing the tag is what starts everything. **Tag only a green `main`** — the release
workflow re-runs every gate anyway, but discovering a failure after the tag exists means
deleting a tag, and `v*` tags are protected against exactly that.

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

### Removing that gate

The approval is a **required reviewer** on the `pypi` GitHub Environment, not anything in
the workflow file. It can be removed, and the release then runs unattended from the tag:

```bash
gh api -X PUT repos/azias/scenet/environments/pypi   --input - <<'JSON'
{"wait_timer": 0, "reviewers": null, "deployment_branch_policy": null}
JSON
```

**What you give up.** PyPI never allows re-uploading a version — not after a delete, not
ever — so an accidental or mistaken tag burns that number permanently, and the click is
what makes a tag reversible right up to the last moment. What you keep is not nothing:
`verify` still runs format, lint, types and the full suite before anything is published,
the tag must match `project.version`, the CHANGELOG must have a section for it, and `v*`
tags are protected against deletion.

It is a real trade. Releases stop being synchronous, which matters when the person who
tagged is not around to approve; and the gate protects against a mistake that cannot be
undone. Decide once, deliberately, rather than discovering it mid-release.

## PyPI is opt-in

The `publish` job is skipped unless the repository variable `PYPI_TRUSTED_PUBLISHER`
is `true`:

```bash
gh variable set PYPI_TRUSTED_PUBLISHER --body true
```

That exists because a trusted publisher has to be registered through a web form on
pypi.org -- there is no API, deliberately, since it is the thing that grants publishing
rights. Until somebody has done that, the job cannot succeed, and gating it on an
explicit switch is better than every release failing on a step nobody enabled.

**A release still happens without it.** The GitHub Release is created either way, with
the sdist, the wheel and the `.vsix` attached, and the notes say to install from the
wheel URL rather than claiming a `pip install scenet` that would not work. The release
is only blocked if PyPI is enabled *and* fails -- announcing a version whose upload
broke halfway would be worse than not announcing it.

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

## The AI-generation disclosure is a release requirement

Every published surface must carry the statement that this project is deliberately
AI-generated. Not as a courtesy — as a condition of publishing. Anyone who finds the
package on PyPI, installs the extension, or opens the playground is entitled to know what
they are looking at before they decide to rely on it.

| Surface | Where it comes from |
|---|---|
| The PyPI project page | `README.md`, via `readme = "README.md"` |
| The GitHub landing page | `README.md` |
| The documentation site | `docs/index.md` |
| The playground | the header of `playground/index.html` |
| The VS Code extension | the `description` in `editor/package.json`, and `editor/README.md` |

`tests/test_disclosure.py` checks all of them, and checks that the README's disclosure is
above the fold and is a heading rather than a footnote. It is tested rather than trusted
because it is exactly the kind of thing that quietly disappears: somebody rewrites a
description, trims a README, restructures a page, and it goes with them. Nobody notices,
because nothing was watching.

**Adding a new published surface means adding it to that test.** A new marketplace
listing, a new landing page, a package on another index — each is a place a stranger can
arrive without having read anything else.

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
