# Changelog

All notable changes to Agents TeamKit are documented here.

## [0.3.0] - 2026-09-01

This release completes the v0.2 directory and installation governance work and
the v0.3 protocol and performance evolution.

### Added

- `TEAMKIT_HOME` and `teamkit home` for tool-home and run-location diagnostics.
- `TEAMKIT_RUNS_DIR` adapter hook with consistent run-base resolution for state,
  messages, contexts, artifacts, locks, and ledgers.
- WorkBuddy wrapper injection and install-time rendering of absolute TeamKit
  command paths.
- Aggregated `run status` graph information and active-node views.
- Explicit parallel fork/join graph execution with `relation: parallel`,
  `join: all`, and active-node tracking.
- Batch ledger commands: `batch init`, `next`, `update`, `status`, and `recover`.
- Communication modes and optional default responses, while preserving explicit
  required responses where a workflow needs them.
- Directory, adapter, protocol, contribution, and example documentation.

### Changed

- WorkBuddy export metadata now derives its version from the TeamKit runtime.
- New WorkBuddy packages no longer create an unused package-local `runs/`
  directory.
- Input-file resolution now prefers the run workspace, then the team root, and
  finally the current directory.
- Node and edge validation warnings are forward-compatible and mechanical;
  business workflow advice remains in the team-builder layer.

### Breaking changes

- Without `--out`, `workbuddy export` and `workbuddy export-init` now write to
  `$TEAMKIT_HOME/build/workbuddy` instead of a path relative to the current
  directory. Use `--out build/workbuddy` or `TEAMKIT_HOME=.` to retain the old
  location.
- WorkBuddy run data defaults to the adapter-managed
  `~/.workbuddy/teamkit-runs/<team-id>/` location rather than the installed
  plugin directory. Existing run data in a package directory should be backed
  up before reinstalling or uninstalling that legacy package.
- Relative input resolution has a new precedence: run workspace, team root,
  then current directory.

## [0.1.3]

- Baseline TeamKit release before the v0.2/v0.3 iteration work.
