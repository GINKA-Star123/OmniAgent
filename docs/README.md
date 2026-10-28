# 项目文档导航

当前文档按“配置与运维、质量评测、版本规划、历史学习”划分。日常按任务选择入口，不需要通读所有版本记录；业务行为以当前源码为准，历史代码示例不直接覆盖现有实现。

## 日常入口

| 目标 | 文档 |
| --- | --- |
| 项目启动与能力概览 | [项目 README](../README.md) |
| 环境变量、Provider 与默认值 | [配置参考](config-reference.md) |
| 请求追踪、阶段耗时与错误 | [API 可观测性](api-observability.md) |
| Redis 执行状态与部署门禁 | [执行状态与门禁](operations/v1.2-execution-state-and-gates.md) |
| 仓库治理与检查工具 | [仓库约定](repo-governance.md) |
| 开始质量评测 | [评测导航](quality/README.md)，再按[总流程](quality/project-evaluation-workflow.md)执行 |

## V1.2 规划与批次

| 文档 | 定位 |
| --- | --- |
| [十批实施计划](v1.2/v1.2-ten-batch-implementation-plan.md) | 批次目标、依赖与完成标准的主入口 |
| [第五至第十批修订说明](v1.2/v1.2-batches-05-10-revised-roadmap.md) | 后续规划的依据与详细边界；目前不据此自动推进代码 |
| [范围与基线](v1.2/v1.2-scope-and-baseline.md) | 立项时快照，不代表当前实时测试数量或缺陷数 |
| [第三批回顾](v1.2/v1.2-three-batch-readme.md) | 容器化、基础知识与当时验收记录 |
| [第四批专项评测](v1.2/v1.2-agent-evaluation.md) | 已存在的小型专项 CLI；四层评测另见 quality |
| [第四批代码交付原稿](v1.2/v1.2-batch-04-code-delivery.md) | 历史学习资料，不作为当前源码覆盖模板 |

## 历史材料

- [评测历史](quality/evaluation-history.md)：旧失败、A/B 指标、修复与报告位置；当前下一步不在此维护。
- [V1.0 smoke](v1.0/v1-final-smoke.md)、[V1.0 发布清单](v1.0/v1-release-checklist.md)：版本收尾记录，包含当时前端步骤，不属于本轮后端评测。

不为已经删除的旧路线/补丁文档创建空壳转发页。新增操作统一更新对应指南，运行结果归入历史或原始报告；不要把同一状态复制到多个导航页面。密钥、私有环境文件、原始回答与 Judge 调试材料不写入公开文档。
