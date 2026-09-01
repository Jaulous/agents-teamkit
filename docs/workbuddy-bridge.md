# WorkBuddy Bridge

The WorkBuddy Bridge maps the kit's team definition into WorkBuddy-native capabilities.

## Design Rule

Prefer WorkBuddy official mechanisms for agent teams, messaging, task lists, skills, and artifacts. The kit defines the business protocol; generated WorkBuddy agents use native tools for actions the core cannot perform.

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

Map `process.graph` to WorkBuddy tasks. Message commands remain logical ledger
operations; generated agents use the native `SendMessage` tool for physical delivery.

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

The package-level adapter consumes the execution plan and packages the team for
WorkBuddy. It does not turn TeamKit message commands into platform API calls.

### Ledger and Native Work

TeamKit remains the source of truth for logical run records:

- `messages.jsonl`
- `events.jsonl`
- `context-items.jsonl`
- `artifacts/*`

The sender agent uses WorkBuddy's native `SendMessage` tool for physical delivery,
including the TeamKit message ID. TeamKit does not mirror native messages back into
the logical ledger. If a native event is not visible to TeamKit, the agent can
record a structured summary through the normal command or artifact flow.

### Message Delivery Boundary

TeamKit commands are the stable contract. They record protocol state only:

- `teamkit msg send/reply/close` -> append the logical message/event ledgers
- the sender member -> calls WorkBuddy `SendMessage` with the subject, body,
  references, and TeamKit message ID
- `teamkit context add`, `human request`, and `artifact publish` -> remain
  TeamKit ledger/artifact operations; any native presentation is platform-owned

## Message Delivery Envelope

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

The sender member passes the following information to WorkBuddy `SendMessage`:

- subject and body
- artifact/evidence references
- TeamKit message ID, run ID, and recipient context when useful

If the native tool does not preserve metadata fields, include a short structured
header in the message body. This is an agent-level delivery convention, not a
TeamKit-to-API mapping.

## Platform Verification Boundary

These are implementation facts, not product design choices. The package does not
assume they are available until a live WorkBuddy check confirms them:

- whether a WorkBuddy team session can deliver member-to-member messages with
  `SendMessage` and wake the recipient session
- whether native messages preserve arbitrary run/message identifiers
- whether native messages carry attachments or artifact references
- whether an extension can observe native message/task status
- whether a page extension can read/write team definition files

The v0.2 plan keeps member-to-member delivery as a manual hard gate until this is
tested in a live WorkBuddy session; see `docs/plans/v0.2-iteration-plan.md:283`.

Once confirmed, the bridge can be implemented directly against the actual WorkBuddy APIs.
