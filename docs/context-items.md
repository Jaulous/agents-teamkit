# Context Items

Context Item is the neutral TeamKit abstraction for information an agent team can see.

It is deliberately not a business-specific category. A Context Item may be a standard file, a policy document, a user-provided task file, a manual note, or a snapshot produced by an approved external capability. TeamKit Core only decides how the item is stored, referenced, and made visible to agents.

## Boundary

TeamKit Core owns:

- snapshotting files into a managed run directory
- recording `id`, `name`, `sourceType`, `path`, `sha256`, `scope`, and `visibleTo`
- linking Context Items to the run Topic
- giving agents a clear list of what they may read

TeamKit Core does not own:

- host-platform Skill, tool, or MCP assignment
- database/API query implementation
- tool permissions
- business-system authorization

Those belong to host-platform configuration, adapter behavior, or user-managed agent definitions.

## Declaration

Reusable team context can be declared in `team.yaml`:

```yaml
contexts:
  - id: operating_sop
    name: 业务处理 SOP
    path: references/operating-sop.md
    scope: team

  - id: legal_terms
    name: 法务条款说明
    path: references/legal-terms.md
    scope: agents
    visible_to:
      - legal_checker
      - coordinator

  - id: blacklist_hit
    name: 黑名单命中
    source: query_result
    scope: agents
    visible_to:
      - evidence
      - decision
```

`scope: team` means every agent can see the item. `scope: agents` means only the listed agents should see it.
Items without `path` are runtime placeholders. Fill them during a run with `teamkit context add`.

When editing reusable team context, prefer deterministic commands instead of hand-editing YAML or expert prompts:

```sh
teamkit team context add \
  --team team.yaml \
  --id website_sop \
  --name "网站审核 SOP" \
  --file uploads/website-sop.md \
  --scope agents \
  --visible-to website-auditor \
  --visible-to coordinator

teamkit team context assign \
  --team team.yaml \
  --context website_sop \
  --visible-to qa
```

Expert profiles may describe expected inputs, but `team.yaml` is the source of truth for default Context Item visibility.

## Runtime

When a run is initialized, declared Context Items are copied into:

```text
runs/{run_id}/contexts/{context_id}/content.ext
runs/{run_id}/contexts/{context_id}/manifest.json
runs/{run_id}/context-items.jsonl
```

The run Topic also receives `context_refs`, so collaboration around that run has a stable shared anchor.

Add an item during a run:

```sh
teamkit context add \
  --run task-001 \
  --file /absolute/path/to/file.pdf \
  --name "补充说明" \
  --scope agents \
  --visible-to coordinator \
  --visible-to qa
```

Add an external Skill/API result during a run:

```sh
teamkit context add \
  --run task-001 \
  --id blacklist_hit \
  --text '{"merchant":"merchant-123","blacklistHit":false}' \
  --source-type query_result \
  --by evidence \
  --summary "未命中黑名单。"
```

List visible context for one agent:

```sh
teamkit context list --run task-001 --visible-to qa
```

Agents should read only managed Context Item paths supplied through TeamKit, not arbitrary user-machine paths.
