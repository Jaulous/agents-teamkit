# WorkBuddy Adapter

The first WorkBuddy Adapter is a package-level adapter.

It does not replace WorkBuddy native messaging. It packages two things:

- `Agents TeamKit 工作台`: the WorkBuddy Skill carrier for creating, managing, validating, exporting, and improving user-owned teams.
- Generated Team packages: WorkBuddy Team expert packages compiled from a TeamKit `team.yaml`.

Both use bundled TeamKit command wrappers to keep Graph, Topic, Context Items, Message, human input, artifacts, and final result state deterministic.

## One-Command Install

For end users who only want to install `Agents TeamKit 工作台` into their own WorkBuddy:

```sh
/bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@v0.3.0/scripts/install-workbuddy.sh)"
```

The installer downloads this repository, uses a temporary Python runtime for installation, exports `Agents TeamKit 工作台`, installs a package-local runtime under the WorkBuddy plugin directory, and registers the package in WorkBuddy's user expert marketplace. `TEAMKIT_HOME` is the tool-owned directory, separate from team definitions and run data; generated wrappers inject a per-team `TEAMKIT_RUNS_DIR`.

Advanced options:

```sh
TEAMKIT_REF=main /bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@main/scripts/install-workbuddy.sh)"
TEAMKIT_WORKBUDDY_CONFIG_DIR=/path/to/.workbuddy /bin/bash scripts/install-workbuddy.sh
TEAMKIT_SOURCE_DIR=/path/to/agents-teamkit /bin/bash scripts/install-workbuddy.sh
```

## Local Detection

```sh
bin/teamkit workbuddy detect --json
```

This reports:

- WorkBuddy app path
- app version
- registered deep link schemes
- bundled `codebuddy` CLI path
- user expert marketplace path

On this machine, WorkBuddy was detected at `/Applications/WorkBuddy.app` with `workbuddy://` deep links and the bundled `codebuddy` CLI.

## Export Agents TeamKit 工作台

```sh
bin/teamkit workbuddy export-init \
  --out build/workbuddy \
  --force
```

This creates the WorkBuddy entry package:

```text
build/workbuddy/agents-teamkit-workbench/
  .codebuddy-plugin/plugin.json
  agents/
  skills/agent-team-builder/
  skills/agent-prompt-optimizer/
  skills/agents-teamkit-workbench-runtime/
  docs/
  schemas/
  vendor/teamkit/
```

Install it with:

```sh
bin/teamkit workbuddy install \
  --package build/workbuddy/agents-teamkit-workbench \
  --force
```

In WorkBuddy, open `Agents TeamKit 工作台` and start with:

```text
帮我创建一个新的多 Agent 团队。
```

## Export A Team

```sh
bin/teamkit workbuddy export \
  --team examples/risk-review-team/team.yaml \
  --out build/workbuddy \
  --force
```

This creates a WorkBuddy Team package:

```text
build/workbuddy/risk-review/
  .codebuddy-plugin/plugin.json
  settings.json
  agents/
  skills/teamkit-runtime/
  teamkit-workspace/
  vendor/teamkit/
```

The generated package contains:

- a WorkBuddy Team lead agent
- one WorkBuddy member agent per TeamKit expert, except the configured coordinator becomes the lead
- a `teamkit-runtime` skill
- a wrapper script at `skills/teamkit-runtime/scripts/teamkit.py`
- a copy of the TeamKit team workspace
- a vendored TeamKit CLI

## Install Locally

```sh
bin/teamkit workbuddy install \
  --package build/workbuddy/risk-review \
  --force
```

This installs the package under:

```text
~/.workbuddy/plugins/marketplaces/my-experts/plugins/risk-review
```

It also registers the package in:

```text
~/.workbuddy/plugins/marketplaces/my-experts/.codebuddy-plugin/marketplace.json
```

After installation, restart WorkBuddy if the expert does not appear immediately in the expert center.

To remove an old or generated package:

```sh
bin/teamkit workbuddy uninstall \
  --package old-package-name \
  --force
```

## Validate With WorkBuddy

Use WorkBuddy's bundled expert validator:

```sh
python3 /Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/expert-manager/scripts/validate_expert.py \
  ~/.workbuddy/plugins/marketplaces/my-experts/plugins/risk-review
```

## Try A Task Run

In WorkBuddy, open the installed `风控审核团队` expert team and start with:

```text
请使用这个 Agent 团队处理一个任务，并先帮我初始化运行空间。run id 用 task-001。
```

The lead should use the bundled runtime skill and commands such as:

```sh
{{TEAMKIT_SCRIPT}} team validate
{{TEAMKIT_SCRIPT}} run init --run task-001
{{TEAMKIT_SCRIPT}} run status --run task-001
{{TEAMKIT_SCRIPT}} context list --run task-001
{{TEAMKIT_SCRIPT}} graph next --run task-001
```

## Current Adapter Boundary

Implemented now:

- WorkBuddy app detection
- Agents TeamKit 工作台 export and installation
- TeamKit team export to WorkBuddy Team package
- local WorkBuddy expert installation and marketplace registration
- bundled TeamKit command wrapper for deterministic run state

Deferred until WorkBuddy native APIs are confirmed:

- mapping `teamkit msg send` to WorkBuddy official agent messages
- mirroring WorkBuddy native messages back into `messages.jsonl`
- opening or starting WorkBuddy sessions through deep links
