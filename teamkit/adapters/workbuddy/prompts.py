"""Render WorkBuddy agent and skill markdown from a TeamKit team.

The generated prompts follow WorkBuddy's official expert-team rules
(TeamCreate -> Agent spawn -> SendMessage report-back, Agent ID naming) and
compile ``process.graph`` into an explicit SOP. Agents use native tools for
all communication; TeamKit observes them through native sync, so prompts ask
for only four ledger commands: ``run init``, ``graph advance``,
``result publish`` and ``run close``.

``{{TEAMKIT_SCRIPT}}`` is rendered to the installed launcher path at install time.
"""

from __future__ import annotations

import re
from typing import Any

from teamkit.fsutil import yaml
from teamkit.team import TeamContext
from teamkit.adapters.workbuddy.paths import NATIVE_LEAD_NAME

SCRIPT = "{{TEAMKIT_SCRIPT}}"
PROTOCOL_HEADINGS = re.compile(
    r"^(#{1,6})\s*(TeamKit\s+Rules|TeamKit\s*规则|TeamKit\s*协议(规则)?|协议规则)\s*$", re.IGNORECASE
)


# ---------------------------------------------------------------------- helpers


def strip_protocol_sections(markdown: str) -> str:
    """Drop legacy ``## TeamKit Rules`` sections; adapters inject the protocol."""
    lines = markdown.splitlines()
    kept: list[str] = []
    skip_level = 0
    for line in lines:
        heading = re.match(r"^(#{1,6})\s", line)
        if skip_level:
            if heading and len(heading.group(1)) <= skip_level:
                skip_level = 0
            else:
                continue
        match = PROTOCOL_HEADINGS.match(line.strip())
        if match:
            skip_level = len(match.group(1))
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def demote_headings(markdown: str, levels: int = 1) -> str:
    """Nest an embedded profile under the generated section headings."""
    def repl(match: re.Match[str]) -> str:
        return "#" * min(6, len(match.group(1)) + levels) + " "

    return re.sub(r"^(#{1,6})\s", repl, markdown, flags=re.MULTILINE)


def profile_text(ctx: TeamContext, expert_id: str) -> str:
    expert = ctx.experts.get(expert_id) or {}
    path = ctx.profile_path(expert)
    if not path.is_file():
        return ""
    return strip_protocol_sections(path.read_text(encoding="utf-8"))


def responsibility(ctx: TeamContext, expert_id: str, limit: int = 80) -> str:
    expert = ctx.experts.get(expert_id) or {}
    for key in ("role", "description"):
        if expert.get(key):
            return _one_line(str(expert[key]), limit)
    for line in profile_text(ctx, expert_id).splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if stripped and not stripped.startswith("#"):
            return _one_line(stripped, limit)
    return str(expert.get("name") or expert_id)


def _one_line(text: str, limit: int) -> str:
    text = " ".join(text.split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def frontmatter(name: str, description: str, display_zh: str, display_en: str,
                profession_zh: str, profession_en: str, max_turns: int, skills: list[str]) -> str:
    data = {
        "name": name,
        "description": description.replace("tools:", "tools -"),
        "displayName": {"en": display_en, "zh": display_zh},
        "profession": {"en": profession_en, "zh": profession_zh},
        "maxTurns": max_turns,
    }
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1_000_000).strip()
    unique = list(dict.fromkeys(skills))
    return f"---\n{body}\nskills: [{', '.join(unique)}]\n---\n"


def _agent_label(ctx: TeamContext, roster: dict[str, Any], expert_id: str) -> str:
    info = (roster.get("experts") or {}).get(expert_id) or {}
    if info.get("role") == "lead":
        return "你（主理人）"
    return f"`{info.get('agentId', expert_id)}`（{ctx.expert_name(expert_id)}）"


def _ordered_nodes(ctx: TeamContext) -> list[str]:
    node_map = ctx.graph_node_map()
    entry = ctx.graph_entry_node_id()
    order: list[str] = []
    queue = [entry] if entry in node_map else []
    while queue:
        node_id = queue.pop(0)
        if node_id in order:
            continue
        order.append(node_id)
        for edge in ctx.graph_edges():
            target = str(edge.get("to"))
            if str(edge.get("from")) == node_id and target in node_map and target not in order:
                queue.append(target)
    order.extend(node_id for node_id in node_map if node_id not in order)
    return order


def graph_sop(ctx: TeamContext, roster: dict[str, Any]) -> str:
    """Compile process.graph into numbered SOP steps the lead can follow."""
    node_map = ctx.graph_node_map()
    edges = ctx.graph_edges()
    parallel_targets: dict[str, list[str]] = {}
    for edge in edges:
        if str(edge.get("relation") or "next") == "parallel":
            parallel_targets.setdefault(str(edge.get("to")), []).append(str(edge.get("from")))
    # With any fork in the graph several nodes can be active at once, and
    # graph advance then needs --node; always passing it is harmless.
    needs_node_flag = bool(parallel_targets)
    blocks: list[str] = []
    for number, node_id in enumerate(_ordered_nodes(ctx), 1):
        node = node_map[node_id]
        expert_id = str(node.get("expert") or "")
        lines = [f"### {number}. `{node_id}` · {_agent_label(ctx, roster, expert_id)}", ""]
        lines.append(f"- 任务：{_one_line(str(node.get('task') or ''), 600)}")
        if expert_id == roster.get("coordinator"):
            lines.append(
                f"- 执行：由你负责推进。任务需要成员参与时，按运行协议第 3 步派发（标识头 node={node_id}）并回收；"
                "你自己只做编排、判断与汇编，不代写成员的专业结论。"
            )
        else:
            agent_id = ((roster.get("experts") or {}).get(expert_id) or {}).get("agentId", expert_id)
            lines.append(f"- 执行：派发给 `{agent_id}`，标识头 `[TeamKit run=<run-id> node={node_id}]`，等它用 SendMessage 回传。")
        if node.get("join") == "all" or len(parallel_targets.get(node_id, [])) > 1:
            waits = ", ".join(f"`{item}`" for item in parallel_targets.get(node_id, []))
            lines.append(f"- 汇聚：等 {waits} 全部推进完成后自动激活。")
        node_flag = f" --node {node_id}" if needs_node_flag else ""
        outgoing = [edge for edge in edges if str(edge.get("from")) == node_id]
        parallel = [edge for edge in outgoing if str(edge.get("relation") or "next") == "parallel"]
        choices = [edge for edge in outgoing if str(edge.get("relation") or "next") != "parallel"]
        if not outgoing:
            lines.append("- 完成后：这是流程终点——发布最终结果并关闭运行（见运行协议第 8 步）。")
        elif parallel and not choices:
            targets = ", ".join(f"`{edge.get('to')}`" for edge in parallel)
            lines.append(
                f"- 完成后：`{SCRIPT} graph advance --run <run-id>{node_flag}` 同时激活 {targets}；"
                "在同一条回复里把这些并行节点一次性派发出去。"
            )
        elif len(choices) == 1 and not parallel:
            edge = choices[0]
            when = f"（条件：{edge.get('when')}）" if edge.get("when") else ""
            limit = f"，最多进入 {edge['max_visits']} 次" if isinstance(edge.get("max_visits"), int) else ""
            lines.append(f"- 完成后：`{SCRIPT} graph advance --run <run-id>{node_flag}` 进入 `{edge.get('to')}`{when}{limit}。")
        else:
            lines.append("- 完成后按条件选择一条路径：")
            for edge in choices:
                limit = f"（最多进入 {edge['max_visits']} 次）" if isinstance(edge.get("max_visits"), int) else ""
                lines.append(
                    f"  - 若「{edge.get('when') or '默认'}」→ `{SCRIPT} graph advance --run <run-id>{node_flag} --to {edge.get('to')}`{limit}"
                )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) if blocks else "- 未配置 process.graph；请先修正团队定义。"


def _peer_line(ctx: TeamContext, roster: dict[str, Any], expert_id: str) -> str:
    coordinator = roster.get("coordinator")
    peers = [p for p in ctx.allowed_peers(expert_id, open_fallback=False) if p != coordinator]
    if not peers:
        return "无（所有协作经主理人 `team-lead` 中转）"
    names = []
    for peer in peers:
        rule = ctx.communication_rule(expert_id, peer)
        when = f"：{_one_line(str(rule.get('when')), 60)}" if rule and rule.get("when") else ""
        names.append(f"`{roster['experts'][peer]['agentId']}`（{ctx.expert_name(peer)}{when}）")
    return "；".join(names)


def _peer_routes(ctx: TeamContext, roster: dict[str, Any]) -> list[str]:
    coordinator = roster.get("coordinator")
    routes = []
    for sender in ctx.experts:
        if sender == coordinator:
            continue
        for recipient in ctx.allowed_peers(sender, open_fallback=False):
            if recipient != coordinator:
                routes.append(f"`{roster['experts'][sender]['agentId']}` → `{roster['experts'][recipient]['agentId']}`")
    return routes


def _human_review_lines(ctx: TeamContext) -> str:
    conditions = (ctx.team.get("human_review") or {}).get("required_when") or []
    if not conditions:
        return "- 团队未声明强制人工介入条件；结论超出团队授权范围时仍应请求用户确认。"
    return "\n".join(f"- {item}" for item in conditions)


def _output_lines(ctx: TeamContext) -> str:
    output = ctx.team.get("output") or {}
    lines = [f"- 交付物：{output.get('name', '最终报告')}（格式：{output.get('format', 'markdown')}）"]
    sections = output.get("sections") or []
    if sections:
        lines.append("- 必含章节：" + "、".join(str(item) for item in sections))
    return "\n".join(lines)


def _context_lines(ctx: TeamContext, expert_id: str) -> str:
    items = ctx.contexts_visible_to(expert_id)
    if not items:
        return "- 团队没有为你分配受管资料。"
    lines = []
    for item in items:
        summary = f" — {_one_line(str(item.get('summary')), 80)}" if item.get("summary") else ""
        source = "运行时补充" if not (item.get("path") or item.get("file")) else "团队预置"
        lines.append(f"- {item.get('name')}（`{item.get('id')}`，{source}）{summary}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- agents


def lead_markdown(ctx: TeamContext, roster: dict[str, Any], skills: list[str]) -> str:
    coordinator = str(roster.get("coordinator") or "")
    package = str(roster.get("package"))
    team_name = ctx.team_name
    rows = ["| Agent ID | 成员 | 职责 |", "|---|---|---|"]
    for expert_id, info in (roster.get("experts") or {}).items():
        if info.get("role") == "lead":
            continue
        rows.append(f"| `{info['agentId']}` | {info['name']} | {responsibility(ctx, expert_id)} |")
    if len(rows) == 2:
        rows.append("| — | 无成员 | 团队只有主理人 |")
    routes = _peer_routes(ctx, roster)
    route_text = "；".join(routes) if routes else "无"
    profile = profile_text(ctx, coordinator)
    purpose = str(ctx.team_meta().get("purpose") or "")
    head = frontmatter(
        roster["leadAgentId"],
        f"Lead of the {package} expert team. Creates the WorkBuddy team, dispatches members along the TeamKit process graph, and assembles their results.",
        team_name, team_name, "任务编排官", "Task Orchestrator", 200, skills,
    )
    return head + f"""
# {team_name} - 主理人

你是「{team_name}」的主理人（TeamKit 协调者 `{coordinator}`）。你负责建立 WorkBuddy 团队、按流程图调度成员、汇总成员结论，并用 TeamKit 维护运行账本。专业结论必须来自对应成员；你只做编排、汇编，以及流程图里明确归你负责的节点。

团队目标：{_one_line(purpose, 400)}

## 你的业务职责

{demote_headings(profile, 1) if profile else '（协调者 profile 为空）'}

## 团队成员

调度成员时，`Agent` 工具的 `name` 与 `subagent_type` 都必须填 **Agent ID**；之后给同一成员发消息时 `SendMessage` 的 `recipient` 也填同一个 Agent ID。禁止使用中文名或自造名称。

{chr(10).join(rows)}

## 标准工作流程（由团队流程图生成）

入口节点：`{ctx.graph_entry_node_id()}`。节点 ID 和推进命令必须与下文一致。

{graph_sop(ctx, roster)}

## 运行协议（每个任务都按此执行）

1. **初始化运行**：`{SCRIPT} run init --run <run-id>`。run-id 用任务/订单编号等稳定标识（字母、数字、`-`、`_`）；用户给了任务材料文件时加 `--brief <文件>`。输出中的 `nextStep` 告诉你下一步。
2. **建立团队**：调用 `TeamCreate`，`team_name` 用 `{package}`。每个会话只建一个团队；平台自动加的后缀无需处理。
3. **派发节点任务**：
   - 节点负责人是你自己：编排类工作亲自完成；任务描述里需要成员完成的部分，仍按下面的方式派发给对应成员。
   - 节点负责人是成员：该成员**尚未创建**时用 `Agent`（`name` = `subagent_type` = Agent ID，`team_name` 同上）派发；**已经创建过**时用 `SendMessage`（`type`=`message`，`recipient` = Agent ID）派发——已完成的成员收到消息会自动唤醒。**禁止重复创建同一成员**（会出现 `-2` 副本并丢失上下文）。
   - 派发内容第一行固定写 `[TeamKit run=<run-id> node=<节点ID>]`，随后写任务、需要读取的资料、输出格式和回传要求。一个任务包只对应一个节点。
   - 并行节点在同一条回复里一次性派发。
4. **回收结果**：等待成员用 `SendMessage` 回传完整结果；禁止代写、禁止猜测成员结论。成员提问时直接回复，同样带标识头。
5. **推进流程**：节点产出齐备后执行上文对应的 `graph advance` 命令，并加 `--summary "<一句话进展>"`。命令输出会给出下一个节点与负责人。若提示被未回复消息阻塞、而你确认结果已经收到，可加 `--force --reason "<原因>"`。
6. **查看状态**：`{SCRIPT} run status --run <run-id>`。它会先把 WorkBuddy 成员消息同步进账本（含回复关联与违规检测），再给出 `nextStep`。拿不准下一步时先看它。
7. **人工介入**：需要用户决策时 `{SCRIPT} human request --run <run-id> --from {coordinator} --reason "<原因>" --question "<问题>"`；只是提醒、不阻塞流程时加 `--non-blocking`。用户答复后 `{SCRIPT} human resolve --run <run-id> --review <hr-id> --resolution <结论> --answer "<答复>"`。
8. **收尾**：最终交付文件用 `{SCRIPT} result publish --run <run-id> --from <作者专家ID> --file <文件>` 归档；然后 `{SCRIPT} run close --run <run-id> --summary "<结论摘要>"`（任务失败或被用户取消时加 `--status failed` 或 `--status cancelled`）。**必须先 run close，再让成员结束或清理团队**，否则原生消息会随团队目录一起丢失。

账本说明：`Agent` 派发和 `SendMessage` 消息由 TeamKit 自动从 WorkBuddy 原生团队数据同步进账本，你**不需要**再调用 `msg send` 记账，也不要直接编辑运行目录里的任何账本文件。

## 通信规则

- 你与任何成员之间可以直接通信。
- 成员之间允许的直连：{route_text}。
- 除此之外，所有跨成员信息流必须经你中转。

## 协作红线

- 必须先 `TeamCreate` 再派发；禁止自己模拟成员发言或并行写出多角色内容。
- 禁止代写任何成员的专业产出；禁止 spawn 主理人自己；禁止让成员创建团队。
- 未完成前序节点不得跳到后续节点；分支按流程图条件选择。
- 每完成一个节点向用户简要通报进度；输出语言与用户原始需求一致。

## 人工介入条件

{_human_review_lines(ctx)}

## 最终交付

{_output_lines(ctx)}
"""


def member_markdown(ctx: TeamContext, roster: dict[str, Any], expert_id: str, skills: list[str]) -> str:
    info = roster["experts"][expert_id]
    name = info["name"]
    team_name = ctx.team_name
    profile = profile_text(ctx, expert_id)
    head = frontmatter(
        info["agentId"],
        f"Member of the {roster['package']} expert team responsible for {expert_id}. Works on tasks dispatched by the team lead and reports back with SendMessage.",
        name, name, name, name, 80, skills,
    )
    return head + f"""
# {name}

你是「{team_name}」的成员 **{name}**（Agent ID `{info['agentId']}`，TeamKit 专家 ID `{expert_id}`），由主理人 `{NATIVE_LEAD_NAME}` 通过 WorkBuddy 团队调度。

## 业务职责

{demote_headings(profile, 1) if profile else '（profile 为空）'}

## 可见资料

{_context_lines(ctx, expert_id)}

读取方式：`{SCRIPT} context list --run <run-id> --visible-to {expert_id} --json`，返回的 `absolutePath` 可直接用 Read 读取。不要读取未分配给你的资料。

## 协作协议

1. 任务来自主理人的派发，第一行是 `[TeamKit run=<run-id> node=<节点ID>]`，记住这两个值。
2. 独立完成本人职责范围内的分析；不替其他成员下结论，不推测未给出的事实。
3. 正式产出写成文件时，用 `{SCRIPT} artifact publish --run <run-id> --from {expert_id} --file <文件>` 发布，并记下返回的 artifact ID。
4. 完成后**必须**调用 `SendMessage`（`type`=`message`，`recipient`=`{NATIVE_LEAD_NAME}`，`summary`=一句话结论）回传完整结果。`content` 第一行原样保留 `[TeamKit run=<run-id> node=<节点ID>]`，正文至少包含：结论、事实依据、引用的资料或 artifact ID、未决问题、是否需要人工介入。
5. 需要向主理人提问而不是交付结果时，标识头写成 `[TeamKit run=<run-id> node=<节点ID> type=question]`。
6. 可直接联系的成员：{_peer_line(ctx, roster, expert_id)}。给他们发消息同样带标识头。
7. 不调用 `TeamCreate` / `TeamDelete`，不创建其他成员，不执行 `graph advance` 或 `run close`（由主理人负责），不直接编辑运行目录里的账本文件。
"""


def runtime_skill_markdown(roster: dict[str, Any]) -> str:
    return f"""---
name: teamkit-runtime
description: Runs the TeamKit ledger commands for the {roster['package']} expert team (run init/status/close, graph advance, context list, artifact and result publish, human input). Native WorkBuddy team messages are synced into the ledger automatically.
agent_created: true
allowed-tools: Read,Bash
---

# TeamKit Runtime

本 Skill 为 `{roster['package']}` 专家团提供 TeamKit 账本命令。所有命令都通过同一个启动器执行：

```bash
{SCRIPT} <teamkit 参数>
```

启动器会自动使用本团队打包的 `team.yaml`、WorkBuddy 自带的 Python，以及 `~/.workbuddy/teamkit-runs/{roster['teamId']}/` 运行目录；不需要联网或安装依赖。

## 主理人常用

| 目的 | 命令 |
|---|---|
| 初始化运行 | `{SCRIPT} run init --run <run-id> [--brief <文件>]` |
| 查看状态与下一步（自动同步原生消息） | `{SCRIPT} run status --run <run-id>` |
| 推进流程 | `{SCRIPT} graph advance --run <run-id> [--node <节点>] [--to <下一节点>] --summary "<进展>"` |
| 请求 / 答复人工介入 | `{SCRIPT} human request ...` / `{SCRIPT} human resolve ...` |
| 归档最终结果 | `{SCRIPT} result publish --run <run-id> --from <专家ID> --file <文件>` |
| 关闭运行 | `{SCRIPT} run close --run <run-id> --summary "<摘要>" [--status completed|failed|cancelled]` |
| 协议合规审计 | `{SCRIPT} run audit --run <run-id>` |

## 成员常用

| 目的 | 命令 |
|---|---|
| 列出我可见的资料 | `{SCRIPT} context list --run <run-id> --visible-to <专家ID> --json` |
| 发布正式产出 | `{SCRIPT} artifact publish --run <run-id> --from <专家ID> --file <文件>` |

## 规则

- 成员间通信只用 WorkBuddy 原生 `Agent` / `SendMessage`；TeamKit 会同步并关联回复，不需要 `msg send` 记账。
- 派发和回传内容第一行带 `[TeamKit run=<run-id> node=<节点ID>]`，这是账本归属和回复关联的依据。
- 不直接编辑运行目录中的 `state.yaml`、`topic.yaml`、`*.jsonl` 等账本文件。
"""


# ---------------------------------------------------------------------- workbench package


def workbench_runtime_skill_markdown() -> str:
    return f"""---
name: agents-teamkit-workbench-runtime
description: Runs TeamKit commands from the Agents TeamKit Workbench package to validate team definitions, manage Context visibility, compile execution plans, export teams as WorkBuddy packages, install them, and diagnose WorkBuddy runs.
agent_created: true
allowed-tools: Read,Bash
---

# Agents TeamKit Workbench Runtime

通过打包的启动器运行 TeamKit（无需联网或安装依赖）：

```bash
{SCRIPT} <teamkit 参数>
```

工作台不绑定某个团队，团队相关命令必须显式传 `--team <团队目录>/team.yaml`。

## 常用命令

```bash
{SCRIPT} --team <团队目录>/team.yaml team validate
{SCRIPT} --team <团队目录>/team.yaml team context list
{SCRIPT} --team <团队目录>/team.yaml team context add --id <context-id> --name "<名称>" --file <文件> --scope agents --visible-to <专家ID>
{SCRIPT} --team <团队目录>/team.yaml team context assign --context <context-id> --visible-to <专家ID>
{SCRIPT} --team <团队目录>/team.yaml team compile --out <团队目录>/build/execution-plan.json
{SCRIPT} --team <团队目录>/team.yaml workbuddy export --out <团队目录>/build/workbuddy --force
{SCRIPT} workbuddy install --package <团队目录>/build/workbuddy/<包名> --force
{SCRIPT} workbuddy doctor
```

导出包会生成主理人与成员 Agent（遵循 WorkBuddy 官方专家团规范）、流程图编译出的 SOP，以及自动同步原生团队消息的运行时。导出前会先校验团队定义；安装时运行 WorkBuddy 官方校验器。

排查一次真实运行是否遵守协议：

```bash
{SCRIPT} --team <已安装团队>/teamkit-workspace/team.yaml run audit --run <run-id>
```
"""


def workbench_lead_markdown(agent_id: str, skills: list[str], package: str) -> str:
    head = frontmatter(
        agent_id,
        "Helps business users create, validate, export, install and improve Agents TeamKit multi-agent teams for WorkBuddy.",
        "Agents TeamKit 工作台", "Agents TeamKit Workbench",
        "Agents TeamKit 团队工作台", "Agents TeamKit Team Workbench", 180, skills,
    )
    return head + f"""
# Agents TeamKit 工作台

你是 WorkBuddy 里的 Agents TeamKit 工作台，帮助业务用户设计、创建、校验、导出、安装和迭代他们自己的多 Agent 团队。

## 产品模型

- 用户定义 Team、专家角色、流程图（Graph）、Context Item 可见范围和最终交付。
- TeamKit 把团队编译成 WorkBuddy 专家团：主理人按流程图调度成员，成员用原生 `SendMessage` 回传，TeamKit 自动把原生协作同步进运行账本并做合规审计。
- WorkBuddy 和用户自己的 Agent 配置负责工具、Skill、MCP、API 权限；不要把工具注册表或 API schema 暴露给业务用户。

## 标准工作流

1. 用 `agent-team-builder` 引导用户定义团队、角色、流程、资料可见范围和交付物。
2. 把团队保存为用户可编辑的 `team.yaml`、`experts/*.md`、`references/*`。专家 profile 只写业务内容，不写协议命令（协议由导出器按平台注入）。
3. 用户上传资料或调整可见范围时，用 `agents-teamkit-workbench-runtime` 里的 `team context` 命令修改 `team.yaml`。
4. 用 `team validate` 校验，修复全部 error，并向用户解释 warning。
5. 用户准备试用时，`workbuddy export` 导出团队包并 `workbuddy install` 安装；提醒用户重启或刷新 WorkBuddy 专家中心。
6. 用户要检查或优化已有多 Agent 团队（含其他平台）时，使用 `agent-team-optimizer`：先确认结构和业务意图，再逐条给出经用户批准的改动。
7. 用户跑过真实任务后，先用 `run audit` 查看协议执行情况，再用 `agent-prompt-optimizer` 优化具体专家定义。

## 目录规则

- 团队定义工作目录保存 `team.yaml` 等可编辑文件，不是 WorkBuddy 专家安装目录。用户没指定时先询问保存位置，并说明将创建的文件清单。
- 专家安装目录由 `workbuddy install` 写入 WorkBuddy 固定的用户专家目录，不要让用户手动选择。
- 写入文件前，确认团队 ID、团队定义工作目录和文件清单。

## 边界

- 可以推荐 Context Item 的可见范围；可以在 profile 里记录角色需要哪类 WorkBuddy 能力。
- 不直接绑定或配置 WorkBuddy Skill、MCP、API 工具；不替用户做业务结论。

Package id: `{package}`
"""
