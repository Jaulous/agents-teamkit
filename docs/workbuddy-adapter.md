# WorkBuddy Adapter

The WorkBuddy adapter turns a TeamKit team into a WorkBuddy **expert team**
(专家团) and keeps the run ledger in step with what the team actually does.

It ships two kinds of packages:

- **Agents TeamKit 工作台** (Workbench): the entry package for designing,
  validating, exporting, installing and auditing user-owned teams.
- **Generated team packages**: one per `team.yaml`.

## How A Generated Team Works

```text
user prompt
  -> lead agent (the team's coordinator)      run init --run <id>
  -> TeamCreate(team_name=<package>)
  -> Agent(name=subagent_type=<Agent ID>, team_name=...)   first dispatch of a member
  -> SendMessage(recipient=<Agent ID>)                       later dispatches
  <- SendMessage(recipient=team-lead)                        member report-back
  -> graph advance --run <id> [--to <node>]                  at each node boundary
  -> result publish / run close                              at the end
```

Every dispatch and report starts with `[TeamKit run=<run-id> node=<node-id>]`.
TeamKit reads WorkBuddy's own records on every `run status`, `graph next`,
`graph advance`, `msg list`, `run audit` and `run close`, so the ledger contains
the real collaboration without any agent calling `msg send`.

### What the generated prompts contain

The lead (`<package>-team-lead`) prompt follows WorkBuddy's official expert-team
specification and adds:

- the coordinator's own profile (its business duties);
- a member roster with Agent IDs and one-line responsibilities (`experts[].role`);
- an SOP compiled from `process.graph`: one step per node, who executes it, and
  the exact `graph advance` command for every outgoing edge, including branch
  conditions, `max_visits` limits, parallel forks and joins;
- the run protocol (eight steps) and the red lines (no ghost-writing, no
  duplicate spawns, no subagent shortcuts, run close before team cleanup);
- allowed member-to-member routes, human-input conditions and the final deliverable.

Each member prompt contains its own profile, the Context Items visible to it,
the report-back contract, its allowed peers, and what it must not do.

Profiles keep business content only; legacy `## TeamKit Rules` sections are
stripped on export because the adapter injects the protocol.

### Identity mapping (roster)

`teamkit-workspace/roster.json` is the single source of truth:

| TeamKit expert | WorkBuddy Agent ID | Native member name |
|---|---|---|
| coordinator (`process.coordinator`) | `<package>-team-lead` | `team-lead` |
| any other expert `x` | `<package>-x` | `<package>-x` (spawn name = Agent ID) |

Sync resolves members by their `agentType`, so a run stays readable even if a
lead spawned members under other names (it is flagged as
`noncanonical_member_name`).

## Native Sync

Sources, all read-only:

| Source | Location | Provides |
|---|---|---|
| team config | `~/.workbuddy/teams/<team>/config.json` | lead session, members, spawn prompts (dispatches) |
| member inboxes | `~/.workbuddy/teams/<team>/inboxes/<member>.json` | messages delivered to members |
| lead transcript | `~/.workbuddy/projects/<cwd>/<lead-session>.jsonl` | messages delivered to the lead (WorkBuddy prunes the lead inbox), platform notifications, and `Agent` calls made without `team_name` |
| task list | `~/.workbuddy/tasks/<team>/*.json` | task status transitions |

**Binding.** `run init` records the host session (`CODEBUDDY_SESSION_ID`) and
working directory. Sync binds the run to the native team whose
`leadSessionId` matches, falling back to the same working directory and package
within a 15-minute window. `run bind --native-team <name>` or `run init
--native-team <name>` set it explicitly.

**Recorded events.** `member.spawned`, `member.completed`, `member.failed`,
`member.reactivated`, `member.respawned`, `native.task`, and
`protocol.violation` with one of:

| Violation | Meaning | Audit |
|---|---|---|
| `unauthorized_route` | a member messaged another member outside the allowed routes | FAIL |
| `subagent_dispatch` | the lead called a member with `Agent` but without `name`/`team_name`; it ran as a one-shot subagent that cannot receive follow-ups or use `SendMessage` | FAIL |
| `unknown_member` | a member was spawned with a `subagent_type` that is not one of this team's agents | FAIL |
| `duplicate_member` | an agent was spawned again while an earlier copy was healthy (respawning after a failure is not a violation) | WARN |
| `noncanonical_member_name` | spawn name differs from the Agent ID | WARN |

Run `teamkit workbuddy sync --run <id>` to sync on demand and
`teamkit workbuddy teams` to list native teams.

## Audit

```sh
<launcher> run audit --run <run-id>          # inside WorkBuddy
bin/teamkit --team <installed>/teamkit-workspace/team.yaml run audit --run <run-id>
```

Checks: ledger integrity, host binding, attribution, violations, member results
behind every member-owned node that advanced, results that ran ahead of the
graph, open required messages, forced advances, graph progress, open human input,
final result. Verdicts: `PASS`, `PASS_WITH_WARNINGS`, `FAIL`, `UNVERIFIED`.

## Install

### One command (Workbench)

```sh
/bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@v0.4.0/scripts/install-workbuddy.sh)"
```

The installer needs only Python 3.9+ (it prefers the Python bundled with
WorkBuddy) and no `pip`: TeamKit's single dependency, PyYAML, is vendored as
pure Python. Rerun the same command to upgrade.

### From a checkout

```sh
bin/teamkit workbuddy doctor
bin/teamkit workbuddy export-init --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/agents-teamkit-workbench --force

bin/teamkit workbuddy export --team examples/risk-review-team/team.yaml --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/risk-review --force
```

Install is transactional: the package is copied to a staging directory inside
the experts folder, checked by TeamKit's closure validation and by WorkBuddy's
official `validate_expert.py`, rendered (the `{{TEAMKIT_SCRIPT}}` placeholder
becomes the installed launcher path), and atomically swapped in. The previous
version moves to `~/.workbuddy/teamkit-backups/`. Without the official
validator (non-default install location, other OS) installation continues with
a warning; `--strict` makes it mandatory.

`workbuddy uninstall --package <name>` also moves the package to
`teamkit-backups/` and removes its marketplace entry. Run data in
`~/.workbuddy/teamkit-runs/<team-id>/` is never touched by install or uninstall.

Restart WorkBuddy or reopen the expert center if a package does not appear.

### Generated package layout

```text
<package>/
  .codebuddy-plugin/plugin.json
  settings.json                      {"agent": "<package>-team-lead"}
  agents/<package>-team-lead.md, agents/<package>-<expert>.md
  skills/teamkit-runtime/SKILL.md
  skills/teamkit-runtime/scripts/teamkit      POSIX launcher
  skills/<declared skills>/
  teamkit-workspace/team.yaml, roster.json, experts/, references/
  vendor/teamkit/                    TeamKit package incl. vendored PyYAML
  vendor/teamkit_entry.py, vendor/teamkit_entry.json
  avatars/                           optional
```

The launcher picks `TEAMKIT_PYTHON`, then WorkBuddy's bundled Python, then
`python3`/`python`, and sets `TEAMKIT_HOST=workbuddy`, the package name and
`TEAMKIT_RUNS_DIR=~/.workbuddy/teamkit-runs/<team-id>`.

## `workbuddy.yaml` (optional adapter manifest)

Kept beside `team.yaml`; Core never reads it.

```yaml
skills:
  - name: order-data
    path: skills/order-data
    agents: [field-verifier, logistics-auditor]   # omit = every agent
display:
  description_zh: "40-50 个汉字的卡片简介"
  description_en: "Card description"
  category: 11-SecurityCompliance            # WorkBuddy categoryId
  tags:                                       # exactly 3
    - {zh: 风控审核, en: Risk review}
    - {zh: 多专家协作, en: Multi-agent}
    - {zh: 可审计, en: Auditable}
  quick_prompts:                              # exactly 3; the first is the default prompt
    - {zh: "...", en: "..."}
    - {zh: "...", en: "..."}
    - {zh: "...", en: "..."}
```

## Platform Constraints Respected

- Expert packages may not contain `hooks/` or `commands/` and agent frontmatter
  may not declare `tools` (official validator). TeamKit therefore observes the
  platform through its persisted records instead of hooks.
- The lead file must be `<team>-team-lead.md`; Team `profession` equals
  `displayName`; exactly three tags and three quick prompts.
- One team per session; members cannot create teams; teams must be cleaned up
  by the lead (TeamKit tells the lead to `run close` first so nothing is lost).

## Upgrading From v0.3

1. Reinstall the Workbench with the one-command installer.
2. Re-export and reinstall each team package (`workbuddy export` + `workbuddy install --force`).
   Old packages keep working but use the legacy `teamkit.py` wrapper that
   creates a networked venv; `workbuddy doctor` lists them.
3. Existing runs stay where they were (`~/.workbuddy/teamkit-runs/<team-id>/`).
   Runs created before v0.4 have no host binding; bind one with
   `run bind --run <id> --native-team <team>` to sync and audit it.

## Troubleshooting

| Symptom | Check |
|---|---|
| `run status` shows `sync.reason: no native team matched` | the lead has not called `TeamCreate` yet, or ran `run init` in another session; use `run bind --native-team` |
| graph blocked by open messages that were answered | the reply lacked a header or went to another run; `run status` lists the ids; `graph advance --force --reason ...` |
| audit `subagent_dispatch` | the lead omitted `name`/`team_name` on `Agent`; re-export the package (v0.4 prompts state it explicitly) |
| audit `unauthorized_route` | members talked directly; add a `communication.rules` entry if the route is intended |
| launcher `needs Python 3.9+` | set `TEAMKIT_PYTHON` or install Python 3 |
| package missing after install | `workbuddy doctor`; restart WorkBuddy |
