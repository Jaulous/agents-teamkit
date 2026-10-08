# Contributing

Thanks for helping improve Agents TeamKit.

## Local Setup

TeamKit has no required dependencies and supports Python 3.9+. It uses an
installed PyYAML when present and the vendored pure-Python copy in
`teamkit/_vendor/` otherwise.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Test

```sh
python3 -m unittest discover -s tests
```

CI runs the suite on Python 3.9 and 3.13 on Linux and macOS without PyYAML,
so the vendored path is always exercised. When WorkBuddy is installed locally,
the export and install tests also run WorkBuddy's official expert validator.

Avoid Python 3.10+ only syntax and APIs at runtime (`match`, runtime `X | Y`
unions, `Path.write_text(newline=...)`): generated packages may run on the
macOS system Python 3.9.

## Smoke Checks

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
bin/teamkit run init --team examples/risk-review-team/team.yaml --run smoke-001
bin/teamkit run status --team examples/risk-review-team/team.yaml --run smoke-001
bin/teamkit run audit --team examples/risk-review-team/team.yaml --run smoke-001
bin/teamkit workbuddy doctor
```

Generated `build/` and `runs/*` files must not be committed.

## Design Rules

- Keep TeamKit Core platform-independent; host behavior lives under
  `teamkit/adapters/<platform>/` (see [docs/adapter-development.md](docs/adapter-development.md)).
- Keep `team.yaml` business-readable; host settings go in adapter manifests
  such as `workbuddy.yaml`.
- Expert profiles hold business content only; adapters inject the protocol.
- Every ledger write goes through `teamkit` commands or adapter sync, under the
  run lock. Never delete run data; archive or back up instead.
- Do not add tool, MCP, API, or host-platform package fields to the core team
  schema unless the core model explicitly adopts them.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>)!: <imperative summary, lower case, no period>

<body: what changed and why, wrapped at 72 columns>

BREAKING CHANGE: <what users must do>   (when the commit breaks compatibility)
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`.
Common scopes: `workbuddy`, `install`, `skills`, `core`, `release`. Mark
breaking changes with `!` and a `BREAKING CHANGE:` footer. Keep one logical
change per commit, and make every commit pass the test suite.

## Releases

1. Update the version in `pyproject.toml` and `teamkit/__init__.py`.
2. Move `CHANGELOG.md` entries under the new version with today's date and add
   its compare link at the bottom.
3. Point install URLs at the new tag: `scripts/install-workbuddy.sh`
   (`TEAMKIT_REF` default), `README.md`, and `docs/workbuddy-adapter.md`.
4. Commit as `chore(release): vX.Y.Z`.
5. Create an annotated tag `vX.Y.Z` with the message `Agents TeamKit vX.Y.Z`
   and push the branch and the tag.
6. Publish a GitHub release for the tag titled `Agents TeamKit vX.Y.Z` whose
   notes are the changelog section.

Published tags are never moved. A fix ships as a new patch version.

## Pull Requests

Please include:

- a short description of the user-facing change
- tests or smoke-command output for behavior changes
- documentation and changelog updates when commands, schema, or adapter
  behavior change
