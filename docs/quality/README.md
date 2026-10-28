# AIagent 评测现状与文档入口

更新日期：2026-10-28。本页是当前状态的唯一维护入口；命令见[评测总流程](project-evaluation-workflow.md)，历史证据见[历史记录](evaluation-history.md)。

## 一句话结论

**评测底座已搭建，RAG、Chat、Memory 有真实 regression 通过证据；Persona、Vision 的标注和 Judge 可靠性尚未闭环，当前未批准发布基线。**

V1.1 后端已完成，**V1.2 第四批也已按用户确认完成**，前端仍不纳入范围。当前暂不推进第五批，先完成独立的评测审定与校准工作；评测基线尚未获准，不表示第四批开发尚未完成。heldout 留给用户最终验收，不以回归调参结果替代。

## 已完成与仍待确认

| 项目 | 已有证据 | 边界或遗留问题 |
| --- | --- | --- |
| 四层评测 | 组件、轨迹、任务评测，以及独立 load/telemetry 入口；冻结集、条件摘要、预算、报告与安全诊断已落地 | 工具存在不代表负载、容量或发布验收已执行 |
| RAG 索引 | Windows 已构建并迁移 WSL：3364 向量、4096 维，迁移时离线校验 fresh | 历史成功不代表当前缓存实时新鲜；不要为查结果重复收费重建 |
| 检索与生成 | v6 API 检索 470/470，Provider RAG 与 fixed-RAG 各 157/157，Chat 27/27 | 路径不同，不能合算独立样本；Chat 未捕获实际注入证据时 faithfulness=null |
| Memory | v6 regression 6/6，包含生命周期和 cleanup | 3 个来源组；不扩大为图记忆、可选 NLP/BM25 或 heldout 验收 |
| Persona | v6 guard 开启 24/27，关闭 27/27；v7 原失败项 2/3 通过 | Persona-17 的末轮/轨迹范围已作候选裁决，尚待用户确认；不是关闭 guard 的因果依据 |
| Vision | v6 自动 39/45；v7/v8 做了失败定向与误判对照 | 存在错标、覆盖不足、非法原文引用与语义误判；自动通过不等于人工接受 |
| Judge | 当前代码 judge-v8；报告协议 agent-eval-four-layers-v2；可选视觉双通道共用预算 | 同模型评审存在偏差；格式修复仍可能改变语义判断，未实现强制冻结初次判断 |
| 原生稳定性 | v6 fixed-RAG 单进程完整结束 | 旧 SIGSEGV 未稳定复现，不能宣称根因已修复 |
| 环境依赖 | 隔离 API、Redis/Qdrant 有历史运行证据 | Qdrant 版本兼容警告及 spaCy/fastembed 可选能力仍需单独处理；进程是否仍在须现场核验 |

### 不混淆三个快照

- **最近完整回归：v6。** 11 个分项均有完整报告，但并非全部质量通过。
- **当前代码：v8。** v7/v8 仅运行原失败项及已知误判对照，未执行新的完整回归。
- **审定候选：未接受。** 标注和评审范围发生变化，不能与原 r3 分数直接比较为模型进步。

v6 的其余完整分项为 offline 822/822、RAG challenge 20/21（1 条 Judge 异常）、Runtime 3/3。完整结果与报告 ID 见[历史记录](evaluation-history.md#judge-v6-regression-复跑)，定向结果见[失败定向记录](evaluation-history.md#失败定向修复与回归)。不把不同协议、重跑、同源变体拼成一个新通过率。

## 本次审定做到哪里

[标注与口径审定](evaluation-adjudication-20261028.md)已完成 6 组图像和 Persona-17 的代理复核，产出[独立候选](../../data/evaluation/project-20261028-adjudicated-regression-v1/README.md)及 24 条校准参照。

- 候选共 19 例：18 条 Vision、1 条 Persona；12 张图，20 个文件。它不是完整 r4。
- 原 r3 的 535 个文件未修改；Windows/WSL 候选逐字节一致。
- 清单仍为 baseline_eligible=false、human_accepted=false、semantic_judge_calibrated=false。
- 24 条参照只通过结构与引用核对，**没有真实 Judge 语义校准结果**。
- 前次免费验证两端同范围各 264 passed、3 条既有警告，不相加；不是本次文档整理重新执行的测试。

裁决包括红伞/蘑菇错标、外衣/内搭/饰边、花朵与花盆、构图与文字布局，以及 Persona 事实覆盖范围。逐例理由、差异和接受条件只在审定文档维护，不在操作手册重复。

## 下一步顺序

1. 用户审阅候选 gold、Persona-17 的 trajectory 范围，以及校准参照，确认接受与否；不要覆盖 r3。
2. 确认评审口径后，在固定预算内校准 Judge，优先使用异模型并人工抽审；强制防语义升级实现前，校准显式设置 --judge-max-repairs 0。
3. 校准通过后，再安排新版本的受控 smoke 与相关 regression，保存新条件、原报告和独立结果。
4. 数据、评审与业务条件冻结后，由用户执行 heldout；发布和容量验收另行安排。

这些是待批准的后续步骤，本次整理没有调用 Provider/Judge、重启服务或执行 heldout。

## 阅读顺序

| 顺序 | 文档 | 用途 |
| --- | --- | --- |
| 1 | 本页 | 先明确现状和停止点 |
| 2 | [标注与口径审定](evaluation-adjudication-20261028.md) | 当前需审阅的裁决、候选、风险与进入条件 |
| 3 | [当前实现与 Judge 协议](project-evaluation-implementation.md) | 理解实际调用、评分、预算和错误码 |
| 4 | [评测总流程](project-evaluation-workflow.md) | 获准执行后使用的 WSL 唯一操作入口 |
| 按需 | [Windows 手册](project-evaluation-windows-runbook.md) | PowerShell 变体，不混用两端 venv、PID 或基线 |
| 按需 | [r3 数据集说明](../../data/evaluation/project-20261026-r3/DATASET_CARD.md)及[文件索引](../../data/evaluation/project-20261026-r3/README.md) | 核对来源、split、gold 和外发边界 |
| 按需 | [四层体系设计](aiagent-evaluation-system.md) | 设计目标与指标，不代表全部已验收 |
| 按需 | [历史记录](evaluation-history.md) | 查原失败、运行 ID、修复、费用边界和索引备份 |

## 文档保留边界

日期执行页已合并进历史记录并移除，不保留空壳转发页。仍有效的审定文件、机器可读裁决/校准参照、视觉 [v1](project-eval-visual-annotations.json)/[v2](project-eval-visual-annotations-v2.json)依赖、冻结集与原始报告均保留。

[RAG 专项指南](rag-eval.md)和[V1.2 第四批质量工具](../v1.2/v1.2-agent-evaluation.md)对应独立 CLI，不与四层主评测混为同一基线。V1.2 后续代码交付原稿属于待实施参考，不是完成证明；历史版本学习资料不因日期旧而删除。
