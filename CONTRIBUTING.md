# Contributing

Thanks for helping improve Agents TeamKit.

## Local Setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

## Test

```sh
python3 -m unittest discover -s tests
```

## Smoke Checks

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
bin/teamkit team compile \
  --team examples/risk-review-team/team.yaml \
  --out examples/risk-review-team/build/execution-plan.json
bin/teamkit run init --team examples/risk-review-team/team.yaml --run smoke-001
bin/teamkit graph next --team examples/risk-review-team/team.yaml --run smoke-001
```

Generated `build/` and `runs/*` files should not be committed.

## Design Rules

- Keep TeamKit Core platform-independent.
- Keep `team.yaml` business-readable.
- Put runtime-specific behavior behind adapters.
- Use `teamkit` commands for deterministic writes to run state.
- Do not add tool, MCP, API, or host-platform package fields to the core team schema unless the core model explicitly adopts them.

## Pull Requests

Please include:

- a short description of the user-facing change
- tests or smoke-command output for behavior changes
- documentation updates when commands, schema, or adapter behavior changes
