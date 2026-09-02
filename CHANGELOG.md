# Changelog

All notable changes to Agents TeamKit are documented here.

## [0.3.4] - 2026-09-02

This maintenance release fixes the WorkBuddy Workbench package skill export.

### Fixed

- Workbench exports now discover and bundle every repository Skill containing a
  `SKILL.md`, including `agent-team-reviewer`.
- The generated lead agent, WorkBuddy `plugin.json`, and copied Skill
  directories now use the same discovered Skill list.
- Regression coverage now compares the exported Workbench Skill manifest with
  the repository Skill set so newly added Skills cannot silently be omitted.

There are no breaking changes in this release.

## [0.3.3] - 2026-09-01

This feature release clarifies the boundary between logical message accounting
and physical delivery in generated WorkBuddy agents.

### Added

- Generated lead/member agents and the TeamKit runtime skill now include a
  communication guidance block explaining ledger recording, `SendMessage`, and
  `msg reply --reply-to` correlation.
- Regression tests verify the guidance is present and contains no legacy
  scheduling language or unsafe f-string braces.

### Changed

- Communication, command, architecture, WorkBuddy bridge, and adapter docs now
  describe host-native delivery instead of a future command-to-API adapter.
- The WorkBuddy installer and public links now default to `v0.3.3`.
- TeamKit Core message commands and stdout behavior are unchanged.

There are no breaking changes in this release.

## [0.3.2] - 2026-09-01

This release separates task closure from final-output archiving so the runtime
does not decide whether a business task is complete.

### Added

- `teamkit run close` for explicit task closure without file, message, human
  input, or graph-completion checks.
- Generated WorkBuddy command lists now include `run close`.

### Changed (Breaking)

- `result publish` is now pure archiving: it stores content-addressed files in
  `artifacts/final/<hash>.<ext>`, records `final_result`, and never closes a
  run or resolves a Topic. It no longer checks open messages, human input, or
  unfinished branches, and its `--force` option is removed.
- The `workspace.final_report` override and fixed `final-report.md` path are
  removed. A prior “publish means close” flow must call `run close` explicitly.
- Batch recovery treats `state.status == completed` (set by `run close`) as the
  close signal. Core permits mechanical writes after close.

### Known issues / next iteration

- `output.name` remains a required protocol field even though runtime does not
  consume it.
- Expert `result.md`/`scratch.md` scaffolding and the unwritten `archived` Topic
  state remain for a later cleanup.

Core graph and parallel semantics are unchanged.

## [0.3.1] - 2026-09-01

This release adds design-time team review capabilities and aligns the
surrounding documentation with the v0.3 collaboration semantics.

### Added

- `agent-team-reviewer` skill for reviewing existing team definitions, with
  `team-review-rubric.md`, `parallelism-playbook.md`, and its interface shim.

### Changed

- Synchronized the Team Builder definition guide with v0.3 parallelism
  semantics.
- Converged the `team-yaml-spec.md` examples and `teamkit-commands.md`
  descriptions with the current protocol behavior.
- No core semantics were changed; core code remains untouched.

There are no breaking changes in this release.

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
