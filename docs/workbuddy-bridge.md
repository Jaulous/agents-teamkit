# WorkBuddy Bridge

The WorkBuddy Bridge maps the kit's team definition into WorkBuddy-native capabilities.

## Design Rule

Prefer WorkBuddy official mechanisms for agent teams, messaging, task lists, skills, and artifacts. The kit defines the business protocol; WorkBuddy should execute the native protocol.

## Confirmed Local Facts

On the current macOS machine:

- WorkBuddy desktop app exists at `/Applications/WorkBuddy.app`
- bundle identifier is `com.workbuddy.workbuddy`
- app version is `5.3.5`
- deep link scheme includes `workbuddy://`
- bundled CLI exists at `/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy`
- user expert packages are installed under `~/.workbuddy/plugins/marketplaces/my-experts/plugins`

The first adapter therefore exports TeamKit teams into WorkBuddy Team expert packages and registers them in the local expert marketplace.

## Responsibilities

### Compile Experts

Transform each expert into WorkBuddy-native configuration:

- name
- role/profile prompt
- visible Context Item expectations
- communication instructions

### Compile Process

Map `process.graph` to WorkBuddy tasks and official messages when those APIs are available.

### Compile Context Visibility

Expose declared Context Items to the generated team package and keep per-run Context Item snapshots available through TeamKit commands.

If a user or agent adds a task-specific file during a run, the Adapter should call or preserve the effect of `teamkit context add` so agents read a managed copy rather than arbitrary user-machine paths.

### Respect Tool Access Boundary

TeamKit does not assign WorkBuddy Skills, MCPs, or API tools to agents. WorkBuddy and the user's agent configuration own what an agent can execute.

If an existing WorkBuddy Skill or internal API wrapper produces information that should become part of a run, record it as a Context Item or publish it as an artifact. The business user should not see API schemas or tool registries.

### Start Run

Create a run workspace, pass the task brief and managed context references into WorkBuddy, and start execution according to the process mode.

The platform-independent entry point is:

```sh
teamkit team compile --team team.yaml --out build/execution-plan.json
teamkit run init --team team.yaml --run run-001
```

The Adapter consumes the execution plan and maps it to native WorkBuddy objects.

### Mirror Work

If WorkBuddy exposes messages and events, mirror them into the run workspace:

- `messages.jsonl`
- `events.jsonl`
- `context-items.jsonl`
- `artifacts/*`

If WorkBuddy cannot expose a specific event, ask agents to report structured summaries as part of their output.

### Enhance TeamKit Commands

TeamKit commands are the stable contract. The Adapter can enhance them by syncing with WorkBuddy native capabilities:

- `teamkit msg send` -> official WorkBuddy agent message
- `teamkit context add` -> WorkBuddy file/artifact attachment when available
- `teamkit human request` -> native human input/approval task when available
- `teamkit artifact publish` -> native WorkBuddy artifact attachment when available

## Message Mapping

Internal logical message:

```yaml
from: intake
to: policy
subject: 判断适用规则
intent: rule_check
response: required
runId: run-001
topicId: run-001
nodeId: evidence_check
artifactRefs:
  - artifacts/expert-results/fact-summary.md
```

Maps to WorkBuddy official communication with:

- sender
- recipient
- subject
- body
- priority
- thread or run identifier when supported

If metadata is not supported, include a short structured header in the message body.

## Bridge Questions To Confirm

These are implementation facts, not product design choices:

- Can a skill or extension create/configure WorkBuddy Agent Teams?
- Can expert prompts/roles be set programmatically?
- Can WorkBuddy official messages carry thread/run identifiers?
- Can messages carry attachments or artifact references?
- Can the extension query or subscribe to agent messages and task status?
- Can a WorkBuddy page extension read/write the team definition files?

Once confirmed, the bridge can be implemented directly against the actual WorkBuddy APIs.
