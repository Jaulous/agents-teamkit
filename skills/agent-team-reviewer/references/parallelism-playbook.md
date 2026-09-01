# TeamKit v0.3 并行语义小抄

审查 v0.3 团队时以本页为准，不要用 v0.1 的“每次运行只有一个节点”心智模型。v0.3 默认仍是单节点推进；只有显式的 `relation: parallel` 才进入并行语义。

## 真实语义

1. join 的唯一判定是：目标节点的 parallel 入边数大于 1。节点上的 `join: all` 是给人和编辑器看的标注；缺少它不是运行缺陷。
2. fork 只在“无参 advance、choice 出边为空、parallel 出边至少 2 条”时发生。单条 parallel 边只是恒等变换，不 fork。
3. 同一源节点混排 parallel 与 choice 是建模死区：parallel 支路没有可激活的隐式命令，运行期 advance 会要求选择非 parallel 边。
4. join 的 waiting 前置是全图静态 parallel 前置集合；不可达或不可能同轮完成的前置会让 join 永久等待。
5. `max_visits` 只认边级；访问次数按目标节点跨轮累计。节点级 `max_visits` 会被忽略，Core 会给机械 warning。
6. `default_response` 缺省按 optional；只有显式 `required` 的消息会阻塞推进。
7. `relation` 是自由文本；只有精确字符串 `parallel` 才参与 fork。拼写成 `Parallel` 会按 choice 处理，属于信息提醒而非新增 Core 校验。
8. 多个 active 节点时，`graph next` 返回 `activeNodes`；advance 需要 `--node` 指定来源。`result publish` 会拒绝 unfinished 节点数大于 1 的运行。

## 好的形态：成员节点 fork，再由 join 收束

```yaml
process:
  graph:
    entry: intake
    nodes:
      - id: intake
        expert: coordinator
        task: 整理材料并启动独立核验
      - id: evidence_check
        expert: evidence
        task: 核验事实证据
      - id: policy_check
        expert: policy
        task: 判断适用规则
      - id: decision
        expert: coordinator
        join: all
        task: 汇总事实与规则，形成结论
    edges:
      - from: intake
        to: evidence_check
        relation: parallel
      - from: intake
        to: policy_check
        relation: parallel
      - from: evidence_check
        to: decision
        relation: parallel
      - from: policy_check
        to: decision
        relation: parallel
```

这里的 parallel 边成对出现，两个成员节点各自工作，decision 负责收束。`join: all` 帮人读懂意图，但引擎真正依赖的是 decision 的两条 parallel 入边。

## 坏的形态：单条 parallel 边

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
```

它只有一条 parallel 出边，不会 fork；请改用普通边，或补上业务上确实独立的第二个成员分支。

## 坏的形态：混排 parallel 与 choice

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
  - from: intake
    to: manual_review
    when: 发现高风险
```

同一源节点既有 parallel 又有 choice。要么两条都是“同时做”并都标记 parallel，再由 join 收束；要么两条是二选一，就移除 parallel 并保留条件。不要期待引擎自动理解“先并行、再按条件选”。

## 坏的形态：required 全开

```yaml
communication:
  allow_expert_requests: true
  default_response: required
  rules:
    - from: intake
      to: evidence
      response: required
    - from: evidence
      to: policy
      response: required
```

缺省 required 会把普通派发也变成必须回信的等待点。更稳妥的默认是 `optional`，只给交接、汇总、报告或裁决门节点显式 `required`。

## 检查时记住

- `current_node` 仍保留为第一个 active 节点，只为兼容旧读取方；并行状态看 `active_nodes`/`activeNodes`。
- 图边是默认的步骤间许可；不要把每条图边机械复制成 communication rule。
- 本页只描述 Core 已实现的机械语义；“是否值得并行”必须回到专家画像和业务依赖中确认。
