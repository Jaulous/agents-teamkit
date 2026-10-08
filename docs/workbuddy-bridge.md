# WorkBuddy Platform Facts

Verified facts the WorkBuddy adapter relies on. Re-check them when WorkBuddy
releases a major version; `teamkit workbuddy doctor` reports the installed
version. Last verified against WorkBuddy 5.3.5 (macOS, agent CLI bundled in the
app) using the app's own documentation, its official expert validator, and
recorded production runs.

## Packaging

- User experts live in `$WORKBUDDY_CONFIG_DIR/plugins/marketplaces/my-experts/plugins/<name>`
  (default config dir `~/.workbuddy`) and are registered in that marketplace's
  `.codebuddy-plugin/marketplace.json`.
- The official validator is
  `WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/builtin-skills/expert-manager/scripts/validate_expert.py`.
  It requires the package to sit inside the experts directory, forbids `hooks/`,
  `commands/` and `.lsp.json`, forbids a `tools` field in agent frontmatter,
  requires `agentName` = lead markdown file name (not the bare `team-lead`),
  `settings.json` `agent` = `agentName`, Team `profession` = `displayName`,
  exactly 3 tags and 3 quick prompts, and warns when
  `displayDescription.zh` is not 40-50 characters.
- When a session selects an expert, WorkBuddy enables the expert plugin for
  that session (`/api/v1/plugins/switch`, `name@my-experts`) and turns on Agent
  Teams for `expertType: team` (`CODEBUDDY_CODE_EXPERIMENTAL_AGENT_TEAMS`).
- WorkBuddy ships a managed Python at
  `~/.workbuddy/binaries/python/envs/default/bin/python3`.

## Agent Teams Runtime

- `TeamCreate` creates `teams/<team>/config.json`; if the name exists the
  platform appends a suffix (`contract-order-audit` -> `contract-order-audit-56af`).
  One team per session; the creating session is the lead, named `team-lead`.
- `Agent` with `name` + `team_name` (+ `subagent_type`) spawns an in-process
  teammate recorded in `config.json` `members[]` with `name`, `agentType`,
  `prompt` and `joinedAt` (epoch ms). Reusing a name yields `<name>-2`.
- `Agent` **without** `team_name` runs a one-shot subagent: it returns its result
  to the caller, is not a team member, and cannot use `SendMessage` ("missing
  teamContext").
- `SendMessage` parameters: `type` (`message`, `broadcast`, `shutdown_request`,
  `shutdown_response`, `plan_approval_response`), `recipient`, `content`,
  `summary`, `request_id`, `approve`.
- Every delivered message is appended to `teams/<team>/inboxes/<recipient>.json`
  as `{from, text, summary, timestamp, color, read}`. The **lead inbox is
  pruned**; messages to the lead are reliably present in the lead session
  transcript as `<teammate-message teammate_id="..." summary="...">...</teammate-message>`
  user messages.
- Session transcripts: `~/.workbuddy/projects/<cwd with / replaced by ->/<session-id>.jsonl`
  with rows of type `message`, `function_call` (`name`, `arguments`, `callId`),
  and `function_call_result` (`callId`, `output`).
- Platform notifications arrive as `from: system` messages:
  `Teammate "x" completed successfully` / `failed` (with the error, for example
  HTTP 429 rate limits) and `Teammate "x" has been reactivated`.
- Completed members are reactivated automatically when they receive a message.
- The Bash tool exports `CODEBUDDY_SESSION_ID` (the lead's id equals the team's
  `leadSessionId`).
- Hooks exist for user/project settings and normal plugins, but expert packages
  may not ship them (see packaging), so TeamKit does not depend on hooks.

## Observed Failure Modes (production, Sept 2026)

| Run | What happened | How v0.4 handles it |
|---|---|---|
| 10-order audit | 30 member-to-member messages outside declared routes; 14 members spawned under expert ids instead of Agent IDs; members re-spawned after 429 failures; 4 required ledger messages never correlated, graph stuck | native sync records every message, flags routes and names, treats respawn-after-failure as legitimate, correlates replies automatically |
| 2-order audit | the lead created a team but called all 16 members as subagents; members could not report via `SendMessage`; the graph never advanced | `subagent_dispatch` violation, prompts require `name`/`team_name`, audit `graph_followed` warning |
| 9 single-order runs | `run init` then `run close` with no messages: the ledger never saw the work | runs bind to the host session; audit reports `UNVERIFIED` instead of passing |
| lead prompt | the coordinator's own profile was not included in the lead prompt | lead prompt embeds the coordinator profile |
