# Agents TeamKit

Agents TeamKit is a lightweight toolkit for designing, validating, packaging, and running repeatable multi-agent teams for business workflows.

It gives business users a simple team model: experts, responsibilities, collaboration flow, managed context, and expected output. TeamKit turns that model into a deterministic execution plan and run workspace. Platform adapters can then package the same team for a concrete runtime such as WorkBuddy without leaking platform details into the core model.

> Project status: v0.3.4. The core file format, directory model, graph execution, parallel fork/join, batch ledger, WorkBuddy package adapter, and generated-agent communication guidance are implemented. Physical message delivery remains host-native.

## Why TeamKit

Most multi-agent setups collapse into long prompts, ad hoc files, and unclear handoffs. TeamKit keeps the team definition inspectable and versionable:

- `team.yaml` describes the business team and process graph.
- `experts/*.md` defines each expert's role, inputs, outputs, and collaboration rules.
- `references/*` and Context Items control what information each expert can see.
- `teamkit` commands validate teams, compile plans, initialize runs, record messages, publish artifacts, and store final results.
- Adapters package the same TeamKit team into a target runtime.

## Install

Use the source checkout directly:

```sh
git clone https://github.com/Jaulous/agents-teamkit.git
cd agents-teamkit
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

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
```

Try the example in detail:

- [Risk review example](examples/risk-review-team/README.md)
- [Team YAML spec](docs/team-yaml-spec.md)
- [Command reference](docs/teamkit-commands.md)

## Core Concepts

TeamKit keeps three layers separate:

- **User model**: team, experts, process flow, managed context visibility, output.
- **Core model**: Team, Graph, Topic, Context Item, Message, Artifact, Run.
- **Adapter model**: WorkBuddy package mapping today, other runtime mappings later.

The user model should stay business-readable. Runtime constraints belong behind adapters.

## Repository Layout

```text
bin/teamkit                    local CLI entrypoint
teamkit/                       Python command implementation
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
/bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@v0.3.4/scripts/install-workbuddy.sh)"
```

Or export packages from a local checkout:

```sh
bin/teamkit workbuddy detect --json
bin/teamkit workbuddy export-init --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/agents-teamkit-workbench --force

bin/teamkit workbuddy export --team examples/risk-review-team/team.yaml --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/risk-review --force
```

See [docs/workbuddy-adapter.md](docs/workbuddy-adapter.md) for the adapter boundary and local installation details.
See [docs/directory-model.md](docs/directory-model.md) for tool home, team roots, and run data placement.
To update an existing WorkBuddy installation, rerun the same installer; generated team packages must be re-exported and reinstalled with `--force`. See the adapter guide for legacy run-data precautions.

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
- Build deeper runtime adapters only after official platform APIs are confirmed.
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
