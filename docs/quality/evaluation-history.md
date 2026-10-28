# 评测历史记录

更新日期：2026-10-28。本文只保存历史证据与限制，不提供旧修复代码或过时复跑命令。当前操作以[总流程](project-evaluation-workflow.md)为准，协议以[实现说明](project-evaluation-implementation.md#judge-protocol)为准。原始失败报告、调试材料和索引备份均未删除或回写。

当前状态与下一步统一见[现状入口](README.md)，本页不重复维护当前结论。以下按时间保留原条件和当时结论；旧文中的待确认项应结合后续审定阅读，不作为今天的执行指令。

时间与运行 ID 使用 UTC；以下同源数据、测试范围和两端复查大量重叠，不能相加为独立验证数量。历史测试通过不代表当前代码已完成真实模型、heldout 或发布验收。

## 1. 报告位置约定

现有 WSL 工作区：`/root/aiagent-eval/20261026T091836Z-i4Fyhq`。

- `$REPORTS`：`$WORKSPACE/data/cache/reports/project-eval-20261026T091836Z-i4Fyhq`。
- 历史真实运行所在轮次：`$REPORTS/round-20261027T073748Z-472`。
- 下表运行目录后拼接运行 ID 与 `report.json`；其他专项根路径会明确标注。
- 这些路径是历史定位，不证明进程或容器仍运行；不要沿用记录中的 PID 做停止操作。

<a id="offline-repair-history"></a>

## 2. 初次离线断言修复（2026-10-26）

| 原运行 | 通过/总数 | 失败 |
| --- | ---: | --- |
| smoke | 19/24 | 5 条 RAG hit@3 |
| dev | 150/201 | 51 条 RAG hit@3 |
| regression | 640/822 | 177 条 RAG、5 条 Memory 否定偏好 |
| refusal | 3/3 | 无 |

根因是中文短名称与混合文字切词缺失、显式别称被通用信号压过，以及否定偏好被高文本相似度误去重。修复补充二/三字片段、明确别称与 ASCII 边界、否定差异保护；索引分词版本升至 `bm25-zh-ngram-v5`。没有修改冻结 gold、split、hit@3 门槛或 CLI 语义。去重保护不是完整冲突合并算法。

相关范围当时 164 passed、3 条依赖警告，9 个改动 Python 文件 Ruff 通过；后续 Judge v2 扩展范围 203 passed。两者不能相加。`trustcall` 旧 Send 导入警告来自依赖，不是断言失败原因。

| $REPORTS 子目录 | 最终运行 ID | 结果 |
| --- | --- | ---: |
| offline-smoke-fix | 20261026T141020Z-149060ca | 24/24 |
| offline-dev-fix | 20261026T140921Z-62083649 | 201/201 |
| offline-regression-fix | 20261026T140926Z-812251f9 | 822/822 |
| offline-refusal-fix | 20261026T141024Z-9dbdeb50 | 3/3 |
| offline-smoke-judge-v2 | 20261026T144330Z-8459ea6a | 24/24 |
| offline-dev-judge-v2 | 20261026T144334Z-7b257b91 | 201/201 |
| offline-regression-judge-v2 | 20261026T144340Z-93d986be | 822/822 |
| offline-refusal-judge-v2 | 20261026T144348Z-e338efac | 3/3 |

四份最终 `*-fix` 报告的源码摘要为：
`ea57993aa8b5e93b75c8f0656659cd702241cafa7a4e7a0a85cb33b1bcb104b4`。
中途仍有 11 条别名失败的报告也保留，不随意取同目录首份报告。以上离线评测无 Judge 请求。

录入修复亦已落地：`urrlib.parse → urllib.parse`、`capture:: → capture:`、`z * z / * total → z * z / total`，移除集成测试尾部 Markdown 围栏，并仅对有 label 的图片用例比较类型。这些不是待再次手写的补丁。

<a id="provider-rag-history"></a>

## 3. Provider RAG 与索引重建（2026-10-27）

旧协议 9 条 Provider smoke：1 通过、4 质量失败、4 Judge 异常；不能倒推出未保存的原回答或判词。Judge 协议修复后，用户 RAG 首组：

- 原报告：`$REPORTS/round-20261027T073748Z-472/provider-rag-smoke-v2/20261027T074250Z-1fc26cb3/report.json`。
- 2/3，失败 `rag-eaea046817f7-0-answer`，仅 fact_accuracy=0.5；3 Judge 请求、0 修复，Judge tokens 7094/2245，不含被测生成成本。
- 月日正确但额外说明 2012 年；原文支持该说明，独立 gold 只核验月日，因此 supported 与 unverifiable 可以同时成立。
- 生成改为所问字段的最小充分答案，提示词摘要进入条件；未知声明仍计入分母，不改 gold 或阈值。229 项相关离线通过不等于新真实 3/3。

索引构建定位了两类独立问题：WSL 曾出现原生段错误及连接超时；Windows 探针实际证实当前模型 32 条响应的 index=0～7 各重复四次。2 条与 8 条探针可正常返回；保留严格索引对齐校验，将批大小设为 8，不按未知顺序重编号或补零。不能据此断言所有供应商模型都有同一限制。

| 项目 | 历史完成记录 |
| --- | --- |
| Windows 构建 | 421 批，256 文件、3364 分块/向量、4096 维；2026-10-27T09:26:21Z 完成 |
| 成功日志 | Windows `data/cache/rag-windows-20261027T091045Z/rebuild-batch8.log` |
| Windows 旧缓存 | `data/cache/knowledge-backup-20261027T092621Z-2838b644` |
| WSL 导入 | 2026-10-27T09:27:06Z，离线 verify 退出 0、freshness=fresh |
| WSL 旧缓存 | `data/cache/knowledge-backup-20261027T092706Z-846dc433` |
| WSL 封装与日志 | `data/cache/.rag-incoming-LaQn3g`；`data/cache/rag-transfer-20261027T092621Z.log` |
| 迁移后查询 | 一次真实 query embedding，top-3 洛天依.md、洛天二.md、拉链天依.md；不是排序/回答质量基线 |
| 测试范围 | 重建诊断曾为 189 项，再扩展 210 项；最终迁移相关两端各 119 项，范围不相加 |

失败 32 条首批、2/32/8 条合成探针、成功的全库 embedding 及 WSL 查询均可能收费，未查询账单。失败日志 `rebuild.log`、更早 SIGSEGV/ValueError/ConnectTimeout 日志、暂存和备份仍保留。当前不因检索策略修订再次收费重建。

旧 WSL SIGSEGV 备份为 `knowledge-backup-20261027T081014Z-3553e191`，当时只有 split_docs、没有完整 FAISS。内核地址对应 CPython 的 `call_one_instrument`，没有 Python fault 栈，不能认定根因为 FAISS；相同环境 3364 块/4096 维离线构建未复现。之后的单请求 ConnectTimeout 与更早未记录详情的 ValueError 不能直接视为同一原因。

## 4. API 检索、Chat 与 Memory 演进

以下目录均相对于上述历史真实轮次。

| 目录 / 运行 ID | 原始结果 | 原因与后续 |
| --- | --- | --- |
| api-rag-smoke / 20261027T100036Z-519b7916 | 2/3 | 猫尾++生日被活动扩展干扰；保留原查询、合并词法视图、单次向量请求与字段保护 |
| chat-rag-smoke / 20261027T125421Z-476b08f2 | 0/3 | 小冰生日漏召回，另两条生日正确但额外扩写；Judge 正常 |
| memory-api-smoke / 20261027T125527Z-329e942d | 3/4 | 编辑后旧 hint 等活动元数据残留，snapshot 条件超时；cleanup 已删除 1 条 |
| runtime-graph / 20261027T125728Z-f0095191 | 3/3 | 轨迹/Persona 门禁通过，但一条 faithfulness=0、一条 fact_accuracy=0，不是 HTTP Chat 或全事实验收 |
| chat-rag-smoke-fix / 20261027T131608Z-afc56ffb | 0/3 | 三条生日均正确、无冲突，但新增版本断言均 unverifiable，fact_accuracy=0.5 |
| memory-api-smoke-fix / 20261027T131746Z-2166fac3 | 4/4 | 3 条禁用、1 条完整生命周期；学习、编辑、置顶、跨会话、删除及 cleanup 通过 |
| chat-rag-smoke-extractive-v2 / 20261027T133317Z-75f6305a | 1/3 | 三条生日正确、抽取均命中；欧阳夜语/小冰来源标签被判 unverifiable |

Memory 修复只刷新安全新正文与活动提示元数据，不删除审计或 Mem0 history；原响应未留存且已 cleanup，不能逐字还原当时响应。抽取回答仅限受支持的单对象生日字段，依据真实注入片段及 chunk-id，不读取评测 gold；不代表 DeepSeek 自由生成质量提高。Chat 未捕获可对齐的实际注入证据，faithfulness 仍为 null。

Judge v3 只对 gold 明确来源的精确标题与同名 .md 做受限等价校准，保留原判词、raw 指标和 claim 分母，不补造 support。归档：
`$WORKSPACE/data/cache/reports/judge-source-fix-20261027/archived-chat-regrade-v3/regrade.json`。

| 对象 | 原 fact_accuracy | 校准后 | 校准数 |
| --- | ---: | ---: | ---: |
| 欧阳夜语 | 0.5 | 1.0 | 1 |
| 小冰 | 0.5 | 1.0 | 1 |
| 元筱 | 1.0 | 1.0 | 0 |

免费回放语义门槛 3/3、零新外部请求，**不是新 API 3/3**。未重执行 HTTP、cleanup、非语义断言或时延，不能作为普通基线。来源校准测试两端各 189 项通过；曾有一次标准库 random.py 的 `SystemError: unknown opcode 204`，随后单例和完整复查通过，根因未确认，不能宣称修好了 Python 运行时。

## 5. 通用资料字段召回

原真实 API 回归：
`$REPORTS/round-20261027T073748Z-472/api-rag-regression/20261027T135716Z-272368a3/report.json`。

| 指标 | 原结果 |
| --- | ---: |
| 通过 / 总数 | 403/470 |
| Hit@1 / Hit@3 | 79.57% / 85.74% |
| Hit@5 / Hit@10 | 88.51% / 96.17% |
| 执行异常 / Judge 请求 | 0 / 0 |

67 条全部为 hit@3 未达标，49 条在第 4～10 位、18 条前十未命中。每条一个目标文档，Precision@10 上限为 0.1，不可解释成只有约 9.6% 请求正确。

`profile_fields.py` 将生日保护扩展至声源、年龄、身高、团体、发色、瞳色、发布日等明确字段，使用真实源文件对象和正文非空字段补回候选，保留真实 rank，不额外计 RRF。长名称和直接对象优先，单字名只支持明确问法；歌曲/活动/创作不触发。不改 tokenizer、FAISS、gold 或阈值，不扩展生日抽取器。

- 两端相同扩展范围各 294 passed、3 条依赖警告，Ruff 通过；不是全项目测试。
- 完整 3364 分块、470 条 regression：纯词法修改前 371/470、修改后 470/470；模拟固定干扰向量亦 470/470。与原真实混合检索 403/470 不是同条件比较。
- 代码同步并核验 SHA256；API 保留原环境重启，/live 200，原轮次 PID 文件更新。任何 PID 只在操作当时有效。
- 当时修复后的真实 API 回归尚待执行；用户后续实测已确认通过，见下节。heldout、生成质量与正式发布基线不能由此推断通过。

### 5.1 真实检索通过，Provider 生成回归分流

用户后续提供的两份真实报告均位于上述历史轮次：

| 目录 / 运行 ID | 结果 | 实际范围 |
| --- | --- | --- |
| api-rag-regression-profile-fields / 20261027T143310Z-cef82a02 | 470/470，Hit@1/3/5/10 均为 1，无执行异常、零 Judge 请求 | 真实 API 文档检索；服务端远程 query embedding 可能计费 |
| provider-rag-regression / 20261027T143534Z-772f0f6b | 60 passed、93 failed、4 judge_error，共 157 条；退出码 2 | 小语料 BM25 + 真实生成 + Judge v3，不是同一条 API 混合检索路径 |

Provider 报告中的 93 条合法质量失败全部包含 fact_accuracy 未达标，其中 8 条还包含 faithfulness 未达标。153 条完成评审的平均 gold_coverage=1、fact_accuracy≈0.6939、faithfulness≈0.9760、fact_unverifiable_rate≈0.3028；这些均为适用例上的均值，不是请求通过率，不能据 gold 覆盖宣称所有事实都正确。

另四条 Judge 错误均为 response_truncated，两次 finish_reason=length 后仍失败；整轮共 185 次 Judge 请求、28 次协议修复、32 次截断响应（含修复前后）。已知 Judge prompt/completion tokens 为 470349/535871，不含被测生成成本，不由此估算账单。原诊断未记录 reasoning_tokens，不能确认截断由思考 token 消耗造成。

本次未开启 --debug-local，运行目录只有报告、失败清单和摘要，原回答/判词不可恢复。因此不能把 93 条失败全部归因为额外版本说明或来源误扣，也不能重评分旧摘要为通过。

后续工具修订新增精确 --case-id 筛选、每次安全数字诊断与显式 DeepSeek 非思考请求选项；生成提示词强调版本约束不是版本列举任务，判词要求紧凑连续引文。没有修改 gold、阈值、评分分母或原始报告。新增/修订提示词与请求参数属于新条件，真实改善待六条诊断及后续独立回归确认；执行入口见[总流程](project-evaluation-workflow.md#provider-regression-diagnostics)。

本轮最终 Windows / WSL 同范围各 282 项通过（31.85 / 21.27 秒），覆盖 Judge 协议、安全诊断、精确筛选、合法低分不重试、RAG 生成/召回、Memory 回归及 HTTP contract；两端 Ruff 均通过。它们大量重叠，不合计为 564 个独立用例。

WSL 首次验证曾有 1 项 HTTP contract 超时：偏好接口的测试触发完整 Runtime 冷装配，连带加载无关本地检索模型。现改为注入真实 CoreRuntime、MemoryRunner 与临时偏好存储，仅替换模型和删除后端等外部边界；仍走真实路由、持久化与 cleanup 断言，不放宽超时或跳过测试。Windows 一次中间验证还遇到主机页面文件不足导致 MemoryError，资源恢复后最终复跑通过。上述均不是原 Provider 质量失败的已证实原因。

免费离线四组报告已核对：24/24、201/201、822/822、3/3，Judge 请求均为 0。本轮报告位于 Windows 的 `F:/aiagent/data/cache/reports/provider-regression-fix-20261027/`，并未复制冒充 WSL 运行；本轮未执行真实 Provider/Judge、embedding 或索引重建，未重启 API。

## 6. 离线运行索引

各行均按 smoke / dev / regression / refusal 排列，结果依次为 24/24、201/201、822/822、3/3，Judge 请求均为 0。路径相对于 `$WORKSPACE/data/cache/reports/`：

| 专项根目录 | 四个运行 ID |
| --- | --- |
| query-recall-fix-20261027 | 20261027T101609Z-478cbecc；20261027T101612Z-a503fc3d；20261027T101615Z-6f2627c0；20261027T101620Z-bf6e18fb |
| chat-memory-fix-20261027 | 20261027T131015Z-d7dee39d；20261027T131018Z-04e483a7；20261027T131021Z-22e5b7f6；20261027T131027Z-dee34d88 |
| extractive-fact-fix-20261027 | 20261027T132901Z-252ee46c；20261027T132904Z-e3dc212d；20261027T132908Z-a924299d；20261027T132915Z-a49a137b |
| judge-source-fix-20261027 | 20261027T134704Z-2fb4cb12；20261027T134708Z-b972fbd9；20261027T134712Z-4695326d；20261027T134718Z-2462e4ec |
| profile-field-fix-20261027 | 20261027T140904Z-894c3a7a；20261027T140942Z-c8aa80d6；20261027T140946Z-1072b600；20261027T140954Z-541fb66b |

Windows 专项根 `F:/aiagent/data/cache/reports/provider-regression-fix-20261027/` 的四个运行 ID（同样按 smoke / dev / regression / refusal）：20261027T154107Z-c16129a9、20261027T154141Z-9ba18a90、20261027T154206Z-47d22a6a、20261027T154310Z-b8cd0652。

相关 pytest 范围亦不同：查询修复 WSL 212 项；Chat/Memory Windows 166、WSL 扩展 199；抽取 Windows 71、WSL 扩展 238；来源校准两端各 189；资料字段两端各 294。不相加、不替代模型质量结论。

## 7. 旧 RAG A/B 实验（2026-10-19）

此实验联合修改角色元数据与 tokenizer，不是单变量对照。120 条查询中任务通过 15/120 → 18/120；114 条正例粗召回 72→101、final 命中 57→96、top1 34→73，但 6 条负例仍全部错误注入。chunk 用例实际为 13 条，4→13 通过，旧说明的“12条”不采用。

| 指标 | before | after |
| --- | ---: | ---: |
| retrieval_recall / retrieval_mrr | 0.631579 / 0.437194 | 0.885965 / 0.762949 |
| rerank_recall / rerank_mrr | 0.500000 / 0.380409 | 0.842105 / 0.728801 |
| injection_accuracy / prompt_pass_rate | 0.466667 / 0.341667 | 0.750000 / 0.383333 |
| end_to_end_pass_rate | 0.125000 | 0.150000 |

改善5条：smoke_ident_04、smoke_color_01、core_color_02、core_song_04、hard_song_11；回退2条：hard_rel_01、hard_rel_06，缺少另一实体来源。原阈值为-1，ok:true不是质量达标，也不是真实容量测试。

完整分 suite/category/stage 和失败码保留在原始 JSON，不在导航重复展开：
`data/cache/knowledge-backup-20261027T092621Z-2838b644/reports/rag_eval_v2/` 下的 `rag_eval_ab_before_report.json`、`rag_eval_ab_after_report.json`、`rag_eval_ab_after_failures.jsonl`。结论仅适用于当时实现，召回改善不能直接等同任务成功。

## 8. Regression 早期执行与加固（2026-10-28）

本节合并原日期执行页的有效证据。最终范围按用户要求收敛为 regression 和已开始的对照；heldout、release-suite、负载均未执行。旧运行不回写，不拼接不同协议为当前基线。

### 环境与报告索引

- 源工作区 F:/aiagent；WSL sp3-build，副本 /root/aiagent-eval/20261026T091836Z-i4Fyhq；冻结集 project-20261026-r3。
- 原 campaign 根为 $REPORTS/goal-20261028T072909Z；安全副本为 [project-eval-20261028-regression 索引](../../data/cache/reports/project-eval-20261028-regression/regression-campaign-index.json)，包含31份完成报告及不完整运行清单。31份含诊断/重跑，不是31组独立样本。
- 同目录 regression-review.json 记录最终分项、来源组数与未验收边界；fixed-rag-interrupted-coverage.json 记录中断分段覆盖。
- 当时使用 deepseek-flash、https://api.deepseek.com；SUT 与 Judge 同模型，同模型相关偏差仍在。Judge thinking=disabled、max_output_tokens=4096、max_repairs=1。真实带图请求与 Judge smoke 已完成，不是只做文本模拟。
- 隔离 API 为127.0.0.1:18080（单worker）；Redis为127.0.0.1:16379，Qdrant为127.0.0.1:16333；prefix为aiagent:eval:goal-20261028t072909z，collection为aiagent_eval_goal_20261028t072909z。preferences位于data/runtime/preferences-goal-20261028t072909z.json。
- 容器名为aiagent-eval-redis-goal-20261028t072909z、aiagent-eval-qdrant-goal-20261028t072909z；镜像分别为redis/redis-stack-server@sha256:798ab84d9f266936b034ab11c4d04a2b8e4b441884c5aa7d17ac951eefdf742a及qdrant/qdrant@sha256:419d72603f5346ee22ffc4606bdb7beb52fcb63077766fab678e6622ba247366。
- LLM当时temperature=0、max_tokens=600、timeout=90秒。Qdrant client1.17.1/server1.14.1有兼容警告，spaCy/fastembed可选能力未启用。服务/PID均是当时快照，不能据此认定当前运行或直接停止进程。

### v3 至 v5b：结果演进

下列运行相对上述原 campaign 根，完整条件和各运行路径以归档索引为准。

| 阶段 | 原结果及有效边界 |
| --- | --- |
| 六条Provider诊断 | 6/6，provider-rag-diagnostic/20261028T072910Z-2214e83d；不是完整回归 |
| v3 Provider RAG | 147/157，10条失败均为纯引用标记误拆，Judge异常/修复为0 |
| v4 引用协议 | 两端各117项免费通过；真实诊断10/10，Provider/fixed各157/157；保留claim分母，不删低分 |
| v4 challenge | dev5/5、regression21/21、adversarial18/18；不同split不合算泛化证据 |
| v4 Chat / Memory | Chat16/27（11条无关事实扩写）；Memory6/6含cleanup |
| v4 Persona / Vision | Persona on26/27、off25/27；Vision23/45（16judge_error、6failed） |
| v5b Provider RAG | 157/157，provider-rag-regression-final-v5b/20261028T082054Z-03d0b265 |
| v5b fixed-RAG | 原127条journal中断，补跑30/30；不得当作一次157/157完整报告 |
| v5b challenge | 21/21，rag-challenge-regression-final-v5b/20261028T083214Z-6bc41f0b |
| v5b Persona | on/off各26/27，均仅persona-yzl-17覆盖失败 |
| v5b Chat | 27/27，16条受限抽取、11条模型生成；chat-rag-regression-final-v5b/20261028T083716Z-b8e97aad |
| v5b Memory | 6/6含cleanup、3来源组；memory-api-regression-final-v5b/20261028T084239Z-718d77fc |
| v5b Vision | 自动42/45，15原图组；vision-api-regression-final-v5b/20261028T084456Z-14903002；未人工接受 |
| v5b API检索 | 470/470，api-rag-regression-final-v5b/20261028T085708Z-e535d85e |
| v5b offline / Runtime | 822/822、3/3；offline-regression-final-v5b/20261028T085908Z-eb862e66、runtime-graph-regression-final-v5b/20261028T085913Z-eda18617 |
| rerank消融 | on583/583、off578/583，下降0.858个百分点；不是生产缺陷 |

10组完整最终报告的源码摘要为 `1d4ba497b2a8a7d47df3b096ffd797e202dba8751b0af93f1ea9dc42e9464a61`；当时CLI摘要不含integrations，索引另记其逐文件SHA。归档时241源码文件两端一致，但不代表配置、测试和原生库全部一致。该归档已知Judge1069次、其中修复25次，tokens2204062/153517；不含中断、SUT、embedding等全部费用。

### 原生中断与覆盖限制

原运行 `provider-rag-fixed-regression-final-v5b/20261028T082714Z-9650b693` 在127条安全journal后SIGSEGV（-11），无report.json；独立补跑 `provider-rag-fixed-regression-remainder-v5b/20261028T083909Z-3c1c3a10` 为30/30。覆盖清单核对157唯一ID，不是原运行完成报告或完整费用证明。

栈落于strict_llm → Settings → pydantic-settings dotenv → _annotation_is_complex，只说明崩溃位置。Python3.12.15/Clang23.1.3，Pydantic2.13.2、pydantic-settings2.16.0、pydantic-core2.46.2、NumPy2.4.4、httpx0.28.1；核对时可用内存约5.3GB，未见OOM证据，无可用core文件。另进程连续构造Settings500次通过，原生故障未稳定复现，不宣称根因修复。无总报告的Persona异常运行和停止的final-v5也保留，不计完整通过。

### 已落地加固与免费验证

- v4→v5分开文字支持、图片支持和独立gold；兼容图片请求text/prompt。v5b是生成引用条件修订，不是Judge版本号升级。
- 生产字段问答共享事实边界及紧凑消息，不读取gold、不扩大生日抽取器；抽取与自由生成分开归因。
- AudioPlayer延迟到实际播放时打开设备，避免禁用播放仍访问声卡；不等于Voice验收。
- v6将覆盖ID绑定到truth=correct的claim，增加显式fact_scope、overrides摘要；每个CLI运行懒创建/复用Settings与LLMService并释放客户端，首例前保存run.json，源码摘要增加integrations。run.json complete=false是计划，不替代最终report。
- 通用Vision提示词增加构图、位置关系；局部问题不扩写，看不清不猜。结构校验和提示词不能保证语义正确。
- v5b免费范围两端各393 passed；v6加固范围两端各431 passed、3既有警告，定向Ruff通过；范围重叠，不相加、非全项目验收。较早全量评测目录Ruff还记录过4条既有格式问题，不当作当前重新检查结果。
- 加固离线regression822/822，零Judge调用，报告为 `data/cache/reports/project-eval-20261028-hardening-final/offline-regression/20261028T092353Z-c8591d59`。

当时视觉红伞/蘑菇错标、服装覆盖与Persona-17范围均留待审定；后续裁决见[审定说明](evaluation-adjudication-20261028.md)，不回写当时分数。v5b d915正常/小图漏上半身构图是另一类覆盖不足，不将所有失败归因于错标。

<a id="judge-v6-regression-复跑"></a>

## 9. Judge v6 Regression 复跑

用户后续明确要求执行 regression。本轮仅选择 regression split，沿用冻结 r3，不运行 heldout、release-suite 或负载测试；不修改代码、数据或门槛后在同轮静默重试。

执行目录：`data/cache/reports/project-eval-20261028-regression-v6/`，SUT identity 为 `goal-20261028-api-v4-coverage-v6`。运行前核对 Windows/WSL 的 241 个源码文件、535 个冻结数据文件一致，隔离 API `/ready` 返回 200，无其他活跃评测。

计划覆盖 11 个分项，按分项串行执行并检查报告。470 个语义评测实例的 Judge 总预算上限为 940 次，包含初始请求和最多一次协议修复；不包含 SUT 生成和 embedding 费用，不将同源变体与对照相加为独立样本。Persona 保持默认末轮事实口径，不启用 trajectory overrides。

当前状态：**11 个分项全部执行完毕，全部产生完整报告，但不是全部质量通过；未批准基线。** 历史 v5 和前次免费验证报告均保留，不覆盖或改写。此次执行中未修改业务代码、冻结数据或评分门槛，没有因质量失败追加重跑。

| 分项 | 通过 / 总数 | 其余状态 | 报告目录（相对本轮根目录） |
| --- | --- | --- | --- |
| 离线策略与 BM25 | 822/822 | 无 | `offline/20261028T104427Z-6a728471/` |
| 真实 API 检索 | 470/470 | 无 | `api-retrieval/20261028T104443Z-7daf576b/` |
| RAG challenge | 20/21 | 1 条 Judge 异常 | `rag-challenge/20261028T104706Z-4ebd434c/` |
| Persona guard 开启 | 24/27 | 3 条质量失败 | `persona-on/20261028T104828Z-d48d24eb/` |
| Persona guard 关闭 | 27/27 | 无 | `persona-off/20261028T105041Z-9993de6f/` |
| Provider RAG | 157/157 | 无 | `provider-rag/20261028T105246Z-c40c302e/` |
| fixed-RAG | 157/157 | 无；本次单进程完整结束 | `fixed-rag/20261028T105926Z-3c682ada/` |
| 真实 Chat RAG | 27/27 | 无 | `chat-rag/20261028T110556Z-f52d51bc/` |
| 真实 Memory | 6/6 | 无；含清理断言，3 个来源组 | `memory/20261028T111252Z-0a625a41/` |
| 真实 Vision | 39/45 | 4 条质量失败、2 条 Judge 异常；15 个原图组 | `vision/20261028T111537Z-4d4efd16/` |
| Runtime Graph | 3/3 | 无 | `runtime/20261028T112827Z-47c4715f/` |

### 本轮失败与审阅限制

1. `unknown-a38fa92903b0`：初始及一次修复判词均为 `evidence_quote_invalid`。证据 ID 存在，但引文不是证据中的连续原文；记为 Judge 异常，不作为业务质量分。没有额外重跑。
2. Persona guard 开启组：`persona-yzl-07` 行为目标覆盖率 0.5；`persona-yzl-16` 风格分 0.6，未满足原门槛；`persona-yzl-17` 仍为默认末轮事实覆盖不足，总覆盖率 0.5。关闭组本次 27/27。一次运行、同模型 Judge 且非配对复用相同原始生成，不能将差异直接解释为 guard 的因果收益或退化，也不能默认关闭生产保护。
3. Vision Judge 异常：`vision-d02825d4d14e-small`、`vision-d02825d4d14e-wrong-hint`，均为 `coverage_claim_not_correct`，一次协议修复后仍自相矛盾。保留为无有效语义评分的异常，不静默改为低分或通过。
4. Vision 质量失败：`vision-bc255bfc654b-small`、`vision-4b8819e05393-small` 同时未满足 gold 覆盖与图片支持度门槛；`vision-6b128c7ea06b-wrong-hint`、`vision-5a93ca83c3b4-wrong-hint` 未满足 gold 覆盖门槛。这是报告分类，不自动证明所有 gold 均正确，尤其最后一条仍受已知错标影响。
5. 再次抽审已知错标的 `vision-5a93ca83c3b4-normal/small`：二者自动通过，v6 绑定也合法，但将红伞、树木、浅发人物的声明绑定到要求“巨大红褐色蘑菇及附近人物”的复合 gold，仍未真正蕴含目标。normal 还有将未被独立 gold 证实的扩展细节判为 truth=correct 的风险。**v6 只能拦截结构矛盾，不能保证语义蕴含或防止 Judge 把图片支持当作 gold 正确性。39/45 只是自动评分，不是人工接受的视觉事实基线。** 原判词不改写，后续应先审定并另建标注版本、校准独立 Judge，再进行新实验。
6. fixed-RAG 本次 157 条单进程完整结束，157 次 Judge 请求、无修复，未再次出现 SIGSEGV；这是一次运行证据，不证明历史原生中断根因已修复，不覆盖原中断记录。

### 归档与执行收尾

Windows 安全副本：[本轮报告索引](../../data/cache/reports/project-eval-20261028-regression-v6/regression-campaign-index.json)。与 WSL 同相对路径，包含 `campaign-plan.json`、依赖版本、每份报告路径/SHA、分组数、失败 ID 与已知 Judge 用量；各分项同时保留 `run.json`、`report.json`、`summary.md`、`results.jsonl`、`failures.jsonl`。

11 份完整报告均为 Judge v6，`code.source_sha256` 均为 `9ba69fe260dc9d69e0ef3a871f18dfa2f24d1c05df017c15bc30072c2b71a175`，其范围包含 integrations。运行前后源码和冻结数据逐文件摘要均核对一致。v5/v6 协议及不同输入 overrides 不作同条件基线比较；不将各分项、对照、同源图片变体或重跑合并成独立样本通过率。

本轮实际 Judge 请求 **473 次，其中协议修复 3 次**，低于计划上限 940 次；已知 Judge 输入/输出 token 为 **1070439 / 68081**。这不包含 SUT 生成、embedding 和服务内部模型调用的完整成本，费用以供应商账单为准。

未复制 `.judge-debug`、控制台/API 日志或密钥配置；私有审阅材料仍留在 WSL，所有失败和历史报告保留。最终核对无活跃评测进程，API `/ready` 返回 200，保留既有隔离 API 和依赖供用户审阅。heldout、release-suite、负载与容量测试均未执行。

<a id="失败定向修复与回归"></a>

## 10. 失败定向修复与回归

本节对应后续要求“根据分析报告修复并回归”，执行范围以用户最新的“只执行对应失败的回归”为准。没有重跑完整 regression、heldout、release-suite 或压测，没有修改冻结 r3、gold、split、门槛或历史报告。

### 修改内容与边界

| 文件 | 修改 | 不代表什么 |
| --- | --- | --- |
| aiagent/persona/persona_guard.py | 移除对长回复机械追加“阿绫把重点先给你放在这里”的逻辑，保留既有身份禁语与重复前缀处理 | 不默认关闭 guard，不强迫每轮复述关系设定 |
| aiagent/persona/persona_prompts.py | 通用行动指导：目标明确且请求小步骤时，先给一项低负担可执行动作；不机械复述无关背景 | 不写入评测用例台词，不读 gold |
| aiagent/services/vision_service.py | 检查发型整体轮廓，区分外套/内搭/饰边与背景色；整体描述兼顾可见文字布局；主观氛围不混入事实 summary | 提示词约束不能保证模型准确，未增加硬编码答案 |
| aiagent/evaluation/semantic.py | v7 显式双通道分离图片支持度与文字 gold；v8 独立校验 gold 到 claim 的真值与 claim 到目标的完整覆盖，保留原始真值和分母 | 结构校验不是语义证明，不能修正错标；新旧协议不直接比较为质量提升 |
| aiagent/evaluation/contracts.py、cli.py | 安全诊断增加 channel；双通道默认关闭，启用条件、提示词摘要与预算记入 identity；两通道共用预算 | 没有让普通文本每例默认增加一次请求，也不扩大为业务总费用预算 |
| tests/unit/test_evaluation_targeted_repairs.py 等 | 增加通道隔离、预算/有限修复、保持图片矛盾、覆盖蕴含正反对照和绕过防护测试 | 离线模拟响应不代表真实 Judge 一定遵守提示词 |

v8 的覆盖评定必须逐一给出完整 gold_text、关系与原文绑定：答案更具体而 gold 较粗时，允许“覆盖成立但具体 claim 仍不可核验”；部分对象相似、位置/属性缺失则不能完整覆盖。普通合并模式继续要求正确 claim 绑定，不能由 payload 自行开启独立规则。实现与错误码统一见[协议说明](project-evaluation-implementation.md#judge-protocol)。

### 实际执行范围

v7 只选择上节 v6 的 10 条原失败，外加 2 条已确认误判通过的 Vision 对照：`vision-5a93ca83c3b4-normal/small`。二者用于防止错误覆盖继续被当作成功，不是新增的原失败，也不与原失败混算修复率。

v8 仅选择 v7 仍失败的 7 条 Vision，其中含这 2 条对照；未重复已通过的 RAG、Persona 或 `vision-d02825d4d14e-wrong-hint`。Persona-17 的评测范围问题保留，不再追加请求。两阶段是不同源码/协议快照，不能拼成一次完整回归。

| 阶段 | 自动结果 | 报告目录（相对各阶段根） |
| --- | --- | --- |
| v7 RAG 原失败 | 1/1；无协议修复 | rag-challenge/20261028T114633Z-85a6297b/ |
| v7 Persona 原失败 | 2/3；07、16 通过，17 仍失败 | persona-on/20261028T114650Z-d23bc821/ |
| v7 Vision 原失败及误判对照 | 1/8；其余为质量失败，无 Judge 异常 | vision/20261028T114752Z-e9207589/ |
| v8 剩余 Vision | 1/7 自动通过、5 条质量失败、1 条 Judge 异常；自动通过项仍有语义疑点 | vision/20261028T120255Z-295cc33e/ |

### 逐项结论与未解决事项

| 用例 | 最新定向结果 | 解释与保留 |
| --- | --- | --- |
| unknown-a38fa92903b0 | v7 passed | 引文协议异常未再出现，gold_coverage=1；faithfulness=0，不能据此声称引用证据质量全面通过 |
| persona-yzl-07 | v7 passed | 行为目标满足，未再用反问替代用户已请求的小步骤 |
| persona-yzl-16 | v7 passed | style_score=0.9，未再机械添加固定尾语；单例新生成不是 guard 因果实验 |
| persona-yzl-17 | v7 failed | gold_coverage=0.5；末轮安慰与事实关系复述的目标范围仍待审，不硬塞朋友关系台词 |
| vision-d02825d4d14e-wrong-hint | v7 passed | 无 coverage_claim_not_correct 异常；v8 未重复运行，不扩大为当前所有视觉问题已修复 |
| vision-bc255bfc654b-small | v8 failed | visual_unsupported_rate=0，coverage=0.5；琵琶被覆盖，银白长发与 gold“浅灰长发”的属性匹配仍有争议；一次绑定协议修复后保留失败 |
| vision-d02825d4d14e-small | v8 failed | visual_unsupported_rate=0，coverage=0；文字评审将“树木”与“绿树”、“花盆与绿植”与“有花”判为部分覆盖，不能自动证明全是生成错误，需人工核对回答与目标粒度 |
| vision-6b128c7ea06b-wrong-hint | v8 judge_error | 看图 Judge 拆分并列否定句时补写原文不存在的“没有钢琴”等引用；一次修复后仍 claim_quote_not_in_answer。严格拒绝，不自动拼接、归一化或当作质量低分 |
| vision-4b8819e05393-small | v8 自动 passed，未接受 | 第一次文字判词将服装判为 partial，却错误填入覆盖绑定；协议修复后改判 entailed。回答仅“白红相间上衣”不足以严格证明“红色为主”，且原图服装 gold 本身有疑点。保留原报告，不把自动通过当作修复成功 |
| vision-5a93ca83c3b4-wrong-hint | v8 failed | 描述红伞，gold 仍要求巨大蘑菇，coverage=0，visual_unsupported_rate=0；不让业务迎合错标 |
| vision-5a93ca83c3b4-normal/small | v7/v8 均 failed | 两条原误判通过对照转为 coverage=0；仍保留分母及原报告，不把它们解释为业务质量退化 |

v8 的 6 份有效视觉判词均为 visual_unsupported_rate=0，但它们是有偏的失败子集、不同生成及同模型评审；另有一条根本没有有效评分，不能据此宣称“视觉准确率 100%”。粗 gold 下大量 unverifiable 表示未被独立标注证实，并不自动等于图片幻觉。协议修复仍可能改变模型的语义判断，上述服装样本说明双通道和结构化评定仍不能替代人工复核或独立 Judge。

### 验证与归档

- v7 Windows/WSL 同一扩展范围均为 446 passed；v8 业务/评测逻辑修改后，两端同一评测、HTTP 与视觉策略范围均为 243 passed，各有 3 条现存弃用警告。不同范围大量重叠，不相加，也不是全项目或完整离线 regression。
- 本次修改 Python 文件定向 Ruff 通过。每次真实执行前核对两端 241 个源码文件、535 个冻结数据文件一致，并在归档时重新核对，未改动冻结数据。
- v7 的 SUT identity 为 goal-20261028-api-v5-targeted-v7；v8 为 goal-20261028-api-v5-targeted-v8。受控重启仅针对本轮隔离 API，端口、Redis prefix、Qdrant collection 不变；API PID 在 v8 准备时为 7577，仅是当时快照。
- 实际 Judge 请求合计 **36 次，其中协议修复 3 次**，未超过本轮上限 40 次；v7 为 20 次/0 修复，v8 为 16 次/3 修复。已知 Judge 输入/输出 token 合计 **81800 / 20561**，不含 SUT 生成、embedding 或全部供应商费用。
- 两阶段原始报告及 run.json、results.jsonl、failures.jsonl、plan/index 均保留；Windows 只回存安全报告，不复制 .judge-debug、控制台/API 日志或密钥。
- 归档后的 diff 检查移除了 persona_guard.py 的一个多余末尾空行，仅格式变化，补跑定向离线测试 28 项通过。已归档源码摘要代表当时执行快照，不回写为格式清理后的摘要，也未为此重新调用真实模型。

安全副本索引：

- [v7 定向回归](../../data/cache/reports/project-eval-20261028-targeted-v7/regression-campaign-index.json)。
- [v8 最后一次定向回归](../../data/cache/reports/project-eval-20261028-targeted-v8/regression-campaign-index.json)。

本次执行到此结束，不追加第三轮、不使用剩余预算追求通过率。先审定 Persona 事实范围、视觉标注与覆盖粒度、Judge 引用和蕴含可靠性；若修订标注或评审口径，另建版本与独立实验。最近完整回归仍是 v6，当前代码没有完成新全量回归或 heldout，未批准发布基线。

<a id="标注与口径审定执行"></a>

## 11. 标注与口径审定执行

用户随后要求先审定。此次只核对来源、直接复核6组normal/small的12张上传资产、只读审计历史判词、构建独立候选并进行免费测试；没有真实Provider/Judge请求、服务重启、索引重建、新业务回归或heldout样本审阅。

| 产物 | 证据与边界 |
| --- | --- |
| [审定说明](evaluation-adjudication-20261028.md)与[机器可读计划](evaluation-adjudication-20261028.json) | 裁决、目标粒度、Persona轨迹范围和接受条件，不在本页重复新gold表 |
| [候选清单](../../data/evaluation/project-20261028-adjudicated-regression-v1/manifest.json) | 18Vision+1Persona，12图、20文件；不是完整r4；baseline_eligible/human_accepted/semantic_judge_calibrated均为false |
| [24条校准参照](judge-calibration-20261028.json) | 仅结构/引用对照验证，无真实Judge校准成绩 |
| [安全审计摘要](../../data/cache/reports/project-eval-20261028-adjudication-audit.json) | 16份v8诊断，2份非法引用、2处关系变化，其中1处partial升级entailed；原判词不回写 |
| 构建/测试 | 新增21项防护测试；两端同一评测/HTTP/视觉策略范围各264 passed、3既有警告，定向Ruff通过；非全项目测试 |

原r3的535文件摘要未变；原输入、图片字节、threshold保留，目标粒度/事实范围变化单独记录。两端候选20文件逐字节一致；私有原判词未外拷，HTTP契约为进程内模拟而非已部署API实测。原失败、自动通过和费用记录均原样保留，不将审定后分数追溯修改为通过。

## 12. 整理与保留边界

2026-10-28将重复日期执行页合并至第8～11节后删除，并把实时状态集中至[现状入口](README.md)。本次整理仅保留评测目录的文档改动；V1.2第四批按用户确认已经完成，不把评测基线待审写成第四批尚未开发。旧Judge补丁页和RAG A/B源码长文此前已被实现说明与本页替代，不恢复空壳转发页。

数据与报告不是过时操作文档：冻结集、候选、失败日志、索引备份、原始判词安全边界均保留。审定文档仍被候选与构建器引用；视觉v2仍依赖v1；专项CLI和版本学习/待实施交付资料也保留。后续执行统一使用[总流程](project-evaluation-workflow.md)，不要按本页历史身份或PID操作服务。
