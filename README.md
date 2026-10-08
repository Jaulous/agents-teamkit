# Agents TeamKit

Agents TeamKit is a lightweight toolkit for designing, validating, packaging, and running repeatable multi-agent teams for business workflows.

It gives business users a simple team model: experts, responsibilities, collaboration flow, managed context, and expected output. TeamKit turns that model into a deterministic execution plan and run workspace. Platform adapters can then package the same team for a concrete runtime such as WorkBuddy without leaking platform details into the core model.

> Project status: v0.4.0. On WorkBuddy, generated teams use the platform's native Agent Teams tools for all communication and TeamKit observes them: native messages, member lifecycle and protocol violations are synced into the run ledger automatically, and `teamkit run audit` reports whether a run followed the protocol. Runtime packages need only Python 3.9+ (no pip, no network).

## Why TeamKit

Most multi-agent setups collapse into long prompts, ad hoc files, and unclear handoffs. TeamKit keeps the team definition inspectable and versionable:

- `team.yaml` describes the business team and process graph.
- `experts/*.md` defines each expert's role, inputs, outputs, and collaboration rules.
- `references/*` and Context Items control what information each expert can see.
- `teamkit` commands validate teams, compile plans, initialize runs, advance the graph, publish artifacts, store final results, and audit runs.
- Adapters package the same TeamKit team into a target runtime and observe the runtime's native collaboration, so agents never double-book messages.

## Install

Use the source checkout directly:

```sh
git clone https://github.com/Jaulous/agents-teamkit.git
cd agents-teamkit
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

TeamKit has no required dependencies: it uses an installed PyYAML when present
and a vendored pure-Python copy otherwise. Python 3.9+.

Or run the local entrypoint without installing:

```sh
bin/teamkit --help
```

## Quick Start

Validate and compile the included risk review team:

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
bin/teamkit team compile \
  --team examples/risk-review-team/team.yaml \
  --out examples/risk-review-team/build/execution-plan.json
```

Initialize a deterministic run workspace:

```sh
bin/teamkit run init --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit run status --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit graph next --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit home --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit run audit --team examples/risk-review-team/team.yaml --run demo-001
```

Try the example in detail:

- [Risk review example](examples/risk-review-team/README.md)
- [Team YAML spec](docs/team-yaml-spec.md)
- [Command reference](docs/teamkit-commands.md)

## Core Concepts

TeamKit keeps three layers separate:

- **User model**: team, experts, process flow, managed context visibility, output.
- **Core model**: Team, Graph, Topic, Context Item, Message, Artifact, Run, Audit.
- **Adapter model**: WorkBuddy package mapping and native sync today, other runtimes later ([adapter development](docs/adapter-development.md)).

The user model should stay business-readable. Runtime constraints belong behind adapters.

## Repository Layout

```text
bin/teamkit                    local CLI entrypoint
teamkit/                       core: team, validation, graph, runs, contexts, batch, audit, cli
teamkit/adapters/workbuddy/    WorkBuddy roster, prompts, packaging, installer, native sync
teamkit/_vendor/               pure-Python PyYAML for dependency-free runtime packages
schemas/team.schema.json       JSON Schema for team definitions
examples/risk-review-team/     complete example team
skills/                        Team builder, prompt optimizer, and team optimizer skills
docs/                          architecture, specs, commands, adapter notes
scripts/install-workbuddy.sh   optional WorkBuddy adapter installer
tests/                         CLI and adapter tests
```

Start with [docs/README.md](docs/README.md) for the documentation map.

## WorkBuddy Adapter

WorkBuddy is the first adapter and packaging target. It is optional: TeamKit Core remains platform-independent.

Install the TeamKit Workbench package into WorkBuddy:

```sh
/bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@v0.4.0/scripts/install-workbuddy.sh)"
```

Or export packages from a local checkout:

```sh
bin/teamkit workbuddy doctor
bin/teamkit workbuddy export-init --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/agents-teamkit-workbench --force

bin/teamkit workbuddy export --team examples/risk-review-team/team.yaml --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/risk-review --force
```

Inside WorkBuddy, a generated team's lead creates the native team, dispatches members with `Agent`/`SendMessage` following an SOP compiled from the graph, and runs only `run init`, `graph advance`, `result publish` and `run close`. Everything else is synced from WorkBuddy's own records; `run audit` flags unauthorized member-to-member routes, members called as subagents, duplicate spawns and nodes advanced without their owner's result.

See [docs/workbuddy-adapter.md](docs/workbuddy-adapter.md) for the full flow, installation and troubleshooting.
See [docs/directory-model.md](docs/directory-model.md) for tool home, team roots, and run data placement.
To update an existing WorkBuddy installation, rerun the same installer; re-export and reinstall generated team packages with `--force`. Previous versions are moved to `~/.workbuddy/teamkit-backups/`, and run data is never touched.

## Development

Run the test suite:

```sh
python3 -m unittest discover -s tests
```

Useful smoke commands:

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
bin/teamkit workbuddy export-init --out build/workbuddy --force
bin/teamkit workbuddy export --team examples/risk-review-team/team.yaml --out build/workbuddy --force
```

## Roadmap

- Keep `team.yaml` stable, business-facing, and platform-independent.
- Improve team creation and profile optimization skills.
- Deepen the cross-platform team optimizer skill (more platform annexes, richer anti-pattern coverage).
- Add richer run review and profile feedback loops.
- Add adapters for other agent-team hosts (Claude Code agent teams first), reusing the native-sync contract.
- Add a visual Team Studio once the file and command protocol stabilizes.

## Publishing Checklist

This project is licensed under the [MIT License](LICENSE). The copyright notice preserves attribution to the original author while allowing broad use, modification, distribution, sublicensing, and commercial use.

Before making this repository public, confirm the public GitHub location in:

- install commands in this README
- `scripts/install-workbuddy.sh`
- `docs/workbuddy-adapter.md`
- `pyproject.toml` project URLs

## Contributing

Issues and pull requests are welcome once the repository is public. See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, testing, and contribution guidelines.
