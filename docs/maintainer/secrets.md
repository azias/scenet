# Credentials

**This repository holds no secrets.** Not "the secrets are well protected" — there are
none to protect. That is worth explaining, because it is a deliberate design and it is not
what most Python projects do.

## Publishing to PyPI without a token

The traditional arrangement is a long-lived `PYPI_API_TOKEN` in the repository's secrets.
It works, and it has an unpleasant property: it is a credential that can publish any
version of your package, from anywhere, forever, and it sits in a store that anyone with
write access to the repository can read through a workflow.

Scenet uses **Trusted Publishing** instead. PyPI is told, once, through its web interface:

> The workflow `release.yml`, in the repository `azias/scenet`, running in the environment
> `pypi`, may publish the project `scenet`.

At publish time GitHub mints a short-lived OpenID Connect token asserting exactly that
identity. PyPI verifies it and issues a publishing token valid for that single run.

So there is no token to create, store, rotate, or leak. A stolen repository secret cannot
publish, because there is no repository secret. A workflow on a fork cannot publish,
because the identity would not match.

## The `pypi` environment

`release.yml` publishes from a GitHub Environment named `pypi` with a **required
reviewer**. The run pauses there until a human clicks approve.

This is the difference between "a tag publishes to PyPI" and "a tag *proposes* publishing
to PyPI". An accidental tag push — the wrong branch, a typo, a stale local tag pushed by
`--tags` — reaches the gate and stops.

`id-token: write` is granted **on the publishing job alone**, never at workflow level.
That permission is the credential; every other job in the file would otherwise be able to
mint one.

## What credentials do exist

| Credential | Where it lives | Lifetime |
|---|---|---|
| `GITHUB_TOKEN` | Minted per workflow run by GitHub | The run |
| PyPI publishing token | Exchanged from an OIDC token at publish time | Minutes |

Both are ephemeral and neither is stored anywhere.

The workflows declare `permissions: contents: read` at the top level, so `GITHUB_TOKEN`
starts with the minimum and jobs that need more say so themselves. Only
`github-release` asks for `contents: write`.

Every `actions/checkout` sets `persist-credentials: false`, so the checkout token is not
left behind in `.git/config` for a later step — or a compromised dependency's build script
— to find.

## Actions are pinned to commit SHAs

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

A tag is a mutable pointer. Whoever controls an action's repository can move `v7` to
different code, and every workflow referencing `v7` runs it on the next push — with
whatever permissions that job holds. This is the standard supply-chain attack on GitHub
Actions, and it has happened to real, popular actions.

A commit SHA cannot be moved. The `# v7.0.1` comment keeps the file readable, and
Dependabot understands the convention well enough to update both the SHA and the comment
together.

## If a secret ever becomes necessary

It has not so far. If it does — publishing the extension to a marketplace would be the
likely reason — the rules are:

**Never put it in a file.** Workflow YAML travels with every fork. A `.env` in `.gitignore`
is one `git add -f` away from being public, and public forever.

**Set it from stdin**, so it is not in your shell history:

```bash
gh secret set OVSX_PAT --env release < token.txt && rm token.txt
```

**Scope it to an environment**, not the repository, so only the job that needs it can read
it.

**Prefer OIDC** wherever the receiving service supports it. The reason there is nothing to
protect here is that PyPI supports it.

## If something does leak

Rotate first, investigate second. Revoke the credential at the source — PyPI, Azure,
wherever it was issued — before working out how it got out. A revoked token cannot be
misused while you read logs.

Removing it from git history does **not** un-leak it. Anything pushed to a public
repository should be assumed to have been indexed within minutes.
