# Expert Runtime Rules

These rules are injected into expert profiles or runtime context. They keep collaboration stable.

## Command-Mediated Actions

Use TeamKit commands for stable actions:

- Send messages with `teamkit msg send`.
- Reply to a specific message with `teamkit msg reply --reply-to <message-id>`.
- Close messages with `teamkit msg close`.
- Read the message ledger with `teamkit msg list` when you need full message context.
- Inspect the current coordination state with `teamkit run status`; it aggregates Topic, Graph actions, active nodes, next expert/task, messages, contexts, artifacts, and human reviews. `topic status` and `graph next` remain available when a focused view is needed.
- Inspect visible managed context with `teamkit context list`.
- Add managed context with `teamkit context add` only when the user, coordinator, or team definition authorizes it.
- Advance the graph with `teamkit graph advance` only when you are the coordinator or have been explicitly assigned that responsibility.
- Update other shared Topic fields with `teamkit topic update` only when you are the coordinator or have been explicitly assigned that responsibility.
- Publish artifacts with `teamkit artifact publish`.
- Record external Skill/API output with `teamkit context add` when it should become a managed Context Item for the run.
- Request or resolve human input with `teamkit human request` and `teamkit human resolve`.
- Archive a final output, when one exists, with `teamkit result publish`. Archiving does not close the run.
- Close a task run explicitly with `teamkit run close` when the business work is complete.

## Recording Versus Delivering

`teamkit msg send` and `msg reply` record the message in the run ledger; they do
not physically deliver it to the recipient. The sender is responsible for
physical delivery using the host platform's native member-communication tool
(on WorkBuddy, the `SendMessage` tool), passing the subject, body, references,
and the TeamKit message ID. If the native tool cannot carry metadata fields,
include a short structured header in the message body instead. Replies must
correlate through `msg reply --reply-to <original message id>`, not through
subject similarity or timing.

## Do Not Edit Ledgers Directly

Do not directly edit:

- `messages.jsonl`
- `events.jsonl`
- `context-items.jsonl`
- `human-review.jsonl`
- `state.yaml`
- `topic.yaml`
- artifact index files
- final-result archive records

## Workspace Discipline

- Write scratch work only in your own expert folder.
- Treat other experts' scratch files as read-only.
- Publish official outputs through TeamKit.
- Cite stable Context Item, artifact, or evidence references, not mutable scratch notes.

## Communication Discipline

- Ask one clear question or request per message.
- Use `teamkit msg reply --reply-to <message-id>` when answering a specific message.
- Do not infer reply linkage from similar subjects or timing.
- Do not broadcast by default.
- If no substantive reply is needed for a required message, close it with a reason — unresolved required messages block graph advancement.
- Do not maintain a private copy of the whole process. Use `teamkit run status`, `teamkit graph next`, and the shared ledgers as the coordination source.
