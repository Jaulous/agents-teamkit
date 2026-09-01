# Risk Review Team Example

This example defines a Chinese-language merchant onboarding risk review team.

It demonstrates:

- five expert profiles with clear responsibility boundaries
- a graph-based review process
- managed Context Items with team-wide and expert-specific visibility
- runtime placeholders for data fetched from business systems
- a final markdown risk review report contract

## Files

```text
team.yaml              team definition
experts/*.md           expert role profiles
references/*.md        review SOP and risk rules
runs/.gitkeep          placeholder for generated run workspaces
```

Generated `build/` and `runs/*` outputs are ignored by git.

## Validate

From the repository root:

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
```

## Compile

```sh
bin/teamkit team compile \
  --team examples/risk-review-team/team.yaml \
  --out examples/risk-review-team/build/execution-plan.json
```

## Start A Run

```sh
bin/teamkit run init --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit topic status --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit graph next --team examples/risk-review-team/team.yaml --run demo-001
```

The run workspace is created under `examples/risk-review-team/runs/demo-001/`.

## Export To WorkBuddy

```sh
bin/teamkit workbuddy export \
  --team examples/risk-review-team/team.yaml \
  --out build/workbuddy \
  --force
```

The generated package is written to `build/workbuddy/risk-review/`.
