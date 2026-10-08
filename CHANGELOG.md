# Changelog

All notable changes to Agents TeamKit are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: a minor bump may break).

## [Unreleased]

This feature release repositions the team review skill as a platform-agnostic
optimizer and renames it.

### Changed

- `agent-team-reviewer` is renamed to `agent-team-optimizer` and rewritten in
  English at principle altitude: it now reviews and optimizes existing
  multi-agent teams on any platform (TeamKit, WorkBuddy, Claude Code subagents,
  Codex, custom orchestrators), covering communication topology, scheduling
  efficiency, role/node structure, architecture fit, and standardization
  hygiene — always preserving business functionality and applying changes only
  per explicit user approval.
- The workbench lead agent's standard workflow now routes "review or optimize
  an existing team" requests to `agent-team-optimizer` (the skill was bundled
  but unreferenced before).

### Added

- `references/review-rubric.md`: universal five-cluster, 27-dimension rubric
  with a minimum viable scan, severity calibration, and cross-platform worked
  examples.
- `references/change-consent-protocol.md`: protected invariants, convention-vs-
  clutter classification with uncertainty classifying upward, risk-tiered
  consent (Tier 0 read-only through Tier 3 convention-touching with named
  approval), change-plan template, and closure checklist. Directly prevents
  recurrence of the silently-dissolved-shared-spec incident.
- `references/annex-teamkit.md`: the former parallelism playbook plus the
  mechanical TeamKit review checks and version gate, loaded only for
  TeamKit v0.3 definitions as an evidence upgrade.

### Builder revision (`agent-team-builder`)

- Fixed the version-field treadmill: the definition guide now pins
  `version: 0.3`, the team YAML spec example moved from `0.1` to `0.3`, the
  example team follows, and the optimizer annex version gate is now
  feature-aware (parallel semantics present) instead of trusting the field
  value, which the validator never checks.
- Removed the "unless the definition intentionally accepts" escape hatch on
  mixed parallel/choice edges — the engine provides no command path that can
  activate the parallel branch in that shape; it is now a flat prohibition.
- Regenerated the expert-profile TeamKit Rules template against the current
  command surface: `msg reply --reply-to`, `msg close`, `msg list`, `run
  status`, `result publish` (archiving only), and `run close` — the previous
  template could not finish a run.
- Added a shape-verification gate before presenting the draft (output-section
  producers, exception landing spots, paired parallel edges both ways,
  edge-level `max_visits`, context consumers, coordinator overload), a
  present-before-write ordering with an explicit adjustment loop, and a
  validate-and-close step (`teamkit team validate` was never run by the skill
  that generates the file).
- Added parallel GOOD/BAD shape examples, the data-independence question, a
  Good Shape Defaults section mirroring the optimizer rubric, the directory
  model (`runs/` dropped from the recommended layout, `teamkit home`
  referenced), and `team context remove`.
- `docs/expert-runtime-rules.md` now carries the v0.3.3 delivery boundary
  (ledger recording vs physical delivery via the host-native tool, reply-to
  correlation) and `msg list`; the builder guide and generated profiles
  inherit it.
- Frontmatter triggers on both builder and optimizer now disambiguate the
  shared "existing team" case: a request that names the change goes to
  builder; a request for assessment or proposals goes to the optimizer.
- Corrected the annex claim that `result publish` refuses multi-node runs;
  since v0.3.2 it performs no run-state checks.

### Migration

- Installed Workbench packages keep the old `agent-team-reviewer` skill until
  re-exported and reinstalled: rerun `workbuddy export-init` / `workbuddy
  install --force`. Marketplace entries may show a stale duplicate before that.

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

Not tagged or released on its own: these changes were committed together with
0.3.2 and first shipped in the v0.3.2 release.

This version adds design-time team review capabilities and aligns the
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

## [0.1.3] - 2026-08-04

### Changed

- The one-command installer no longer creates a persistent `~/.teamkit`
  directory; it builds in a temporary directory and installs the Python runtime
  inside the WorkBuddy plugin at `.agents-teamkit-runtime/venv`.
- Generated WorkBuddy wrappers use the package-local runtime, so deleting the
  plugin removes the runtime too.

## [0.1.2] - 2026-08-04

### Changed

- Shortened the workbench's Chinese display description so the generated
  package validates without warnings.
- Install URLs point at `v0.1.2`.

## [0.1.1] - 2026-08-04

### Changed (Breaking)

- Rebranded from Agent TeamKit / `workbuddy-agent-team-kit` to Agents TeamKit:
  the Python distribution is `agents-teamkit`, the installer is
  `scripts/install-workbuddy.sh`, and the WorkBuddy entry package is
  `agents-teamkit-workbench`. `teamkit` remains the command name.

## [0.1.0] - 2026-08-04

Initial release (as TeamKit Workbench).

### Added

- `team.yaml` team model with experts, graph process, managed Context Items,
  human review conditions and output definition, plus a JSON schema.
- `teamkit` command layer for validation, compilation, run workspaces, Topic and
  graph navigation, messages, artifacts, human input and final results.
- WorkBuddy package export and install, including the TeamKit 工作台 package.
- `agent-team-builder` and `agent-prompt-optimizer` skills.
- Risk review example team and architecture, protocol and adapter docs.
- One-command installer served through jsDelivr.

[Unreleased]: https://github.com/Jaulous/agents-teamkit/compare/v0.3.4...HEAD
[0.3.4]: https://github.com/Jaulous/agents-teamkit/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/Jaulous/agents-teamkit/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/Jaulous/agents-teamkit/compare/v0.3.0...v0.3.2
[0.3.1]: https://github.com/Jaulous/agents-teamkit/compare/v0.3.0...v0.3.2
[0.3.0]: https://github.com/Jaulous/agents-teamkit/compare/v0.1.3...v0.3.0
[0.1.3]: https://github.com/Jaulous/agents-teamkit/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Jaulous/agents-teamkit/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Jaulous/agents-teamkit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Jaulous/agents-teamkit/releases/tag/v0.1.0
