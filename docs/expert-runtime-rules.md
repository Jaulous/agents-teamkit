# Expert Runtime Rules

These rules govern experts during a run. They are **injected by the platform
adapter** into generated agent prompts; expert profiles should not copy them.

## On Hosts With A Native Member Channel (WorkBuddy)

Lead (the team's coordinator):

1. `run init --run <run-id>` before anything else.
2. `TeamCreate`, then dispatch members with `Agent` (`name` = `subagent_type` =
   Agent ID, plus `team_name`) the first time and `SendMessage` afterwards.
   Never spawn the same member twice and never call a member without
   `team_name` (that makes it a one-shot subagent outside the team).
3. Start every dispatch with `[TeamKit run=<run-id> node=<node-id>]`.
4. Wait for members' own results; never write a member's conclusion.
5. `graph advance` at each node boundary, as listed in the generated SOP.
6. `human request` when a human decision is needed (`--non-blocking` for
   follow-ups that should not pause the run).
7. `result publish`, then `run close`, then clean up the team.

Members:

1. Work only on the dispatched node, inside your responsibility.
2. Read only Context Items visible to you (`context list --visible-to <expert-id>`).
3. Publish file outputs with `artifact publish` and cite the artifact id.
4. Report back with `SendMessage` to `team-lead`, keeping the header line; mark
   questions with `type=question` in the header.
5. Message other members only on the routes listed in your prompt.
6. Never create teams or members, advance the graph, or close the run.

TeamKit records all native messages automatically. Nobody runs `msg send`.

## On Hosts Without A Native Channel

Messages go through the command-mediated transport:

- `teamkit msg send` to ask or hand over (`--type question` for clarifications),
- `teamkit msg reply --reply-to <message-id>` to answer,
- `teamkit msg close` with a resolution and reason when no answer is needed.

The coordinator advances the graph; experts publish artifacts; anyone may
request human input.

## Always

- Do not edit `state.yaml`, `topic.yaml`, `*.jsonl`, artifact indexes or final
  result records directly.
- Write scratch work only in your own `experts/<expert-id>/` folder.
- Cite managed Context Items, artifacts, or human decisions, not mutable scratch notes.
- One clear request per message; do not broadcast by default.
- Use `teamkit run status` as the shared source of truth; it states the next step.
