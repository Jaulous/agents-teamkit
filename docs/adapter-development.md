# Adapter Development

An adapter makes a TeamKit team run on one host platform. Core stays unaware of
any host; everything host-specific lives under `teamkit/adapters/<platform>/`.

## Responsibilities

| Concern | WorkBuddy reference | Notes |
|---|---|---|
| Identity mapping | `paths.build_roster` | expert id <-> host agent id <-> native member name; written to the package so runtime and export agree |
| Prompt generation | `prompts.py` | inject the platform protocol; embed the coordinator profile in the lead; compile the graph into explicit steps; strip legacy protocol sections from profiles |
| Packaging | `package.py` | vendor the `teamkit` package (it carries its own YAML) and a launcher; validate every reference before publishing |
| Installation | `installer.py` | transactional swap, official validation when available, backups instead of deletes |
| Native observation | `native.py` `sync_run(store)` | read host records, write ledgers idempotently, correlate replies, record `protocol.violation` events |
| Diagnostics | `installer.doctor` | environment and package health; read-only |

Register the adapter in `teamkit/adapters/__init__.py` (`_ADAPTERS`). The CLI
calls `sync_bound_run(store)` before state-reading commands; it resolves the
adapter from `state.host.platform`.

## Host Binding

`runs.host_binding_from_env()` captures the binding at `run init` from
`TEAMKIT_HOST`, `TEAMKIT_HOST_PACKAGE`, the host session id and the working
directory. A launcher should export `TEAMKIT_HOST` and set `TEAMKIT_RUNS_DIR`
to a host-owned location outside the installed package.

## `sync_run(store)` Contract

- Called with the run lock held; must not take the lock itself.
- Must be idempotent: derive a stable key for every native record and keep the
  set of seen keys (and any read cursors) in `store.native_index_path`.
- Messages use the core envelope with `source: <platform>.native` and a
  `native` object for host details; ids come from `fsutil.stable_id`.
- Use `runs.correlate_reply` when appending messages so replies close requests.
- Only mark a native dispatch `required` when it names its node.
- Attribute records to runs through the `[TeamKit run=... node=...]` header;
  fall back to the run time window only when no sibling run overlaps, otherwise
  count the record as `unattributed`.
- Never raise for missing or malformed host data; return a report with `ok`
  and `reason`.
- Never write host files.

## Testing

Build synthetic host records in a temporary config directory (see
`tests/test_workbuddy_native.py`) and replay real recorded runs locally before
release. Keep the official host validator in the loop when it is installed.

## Candidate Next Adapters

WorkBuddy's agent runtime documents the same Agent Teams model as Claude Code
(team config, per-member inboxes, session transcripts), so a `claude-code`
adapter could likely reuse `native.py` with different roots and package format;
verify the on-disk layout of the target version first, as was done for
WorkBuddy in [workbuddy-bridge.md](workbuddy-bridge.md). Hosts without a native member channel can use the command-mediated
transport (`teamkit msg send/reply`) and need only prompts and packaging.
