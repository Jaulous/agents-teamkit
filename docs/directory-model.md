# TeamKit 目录模型

TeamKit 将工具自身与用户创建的专家团分开管理：

- 工具目录由 `TEAMKIT_HOME` 指定，默认为 `~/.teamkit/`。未显式指定输出路径时，WorkBuddy 导出包写入 `$TEAMKIT_HOME/build/workbuddy/`。
- 专家团目录是 `team.yaml` 所在目录，由用户管理。
- 运行数据通过单一 `run_base(run_id)` 解析：`workspace.run_root`（显式）优先，其次是 `TEAMKIT_RUNS_DIR/<run_id>`，最后是 `<team-root>/runs/<run_id>`。所有 state、topic、messages、events、contexts、artifacts、锁和台账都从同一 base 派生。

`TEAMKIT_RUNS_DIR` 是平台 adapter 的注入钩子，作用域为单个团队。多团队共存时，注入值应包含团队标识（例如 `~/.workbuddy/teamkit-runs/<team-id>`）。不要依赖 run id 碰撞隔离：普通 `run init` 会报告已初始化，但 `--force` 会覆盖。

使用 `teamkit home --team <team.yaml> --run <run-id>` 可查看工具目录、团队目录、运行目录、团队级批处理目录和解析来源。
