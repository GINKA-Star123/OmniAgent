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

## 同模型 Judge 文字校准诊断（2026-11-01）

用户允许 19 例候选作为独立诊断实验，暂不批准发布基线，随后明确继续使用当前模型作为 Judge。本轮先完成固定文字参照诊断；没有执行这 19 例，没有新的完整业务 regression，没有启动 API/容器或执行 heldout。WSL 原为停止状态，本轮启动 sp3-build，仅使用既有隔离副本。

### 运行条件与保留证据

Judge 为官方 DeepSeek 端点的 `deepseek-flash`，与 SUT 模型名相同；显式 `thinking=disabled`、temperature=0、max_tokens=4096、max_repairs=0、SDK 重试为 0。命名密钥仅在进程内从既有私有 profile 加载，没有在命令或本文写入真实值。参照为原有 24 条代理标注，不发送预期 relation/truth 标签，也不假称人工已审定。

下表为独立运行，不相加为新数据集，不与业务通过率混用。报告已从 WSL 留存至 Windows `data/cache/reports/`；`.judge-debug` 仅供本地复核，不提交。

| 实验 | 完全一致 | Judge 错误 | 实际请求 | 报告 |
| --- | --- | --- | --- | --- |
| 原 v8 gold 通道，24 条 | 14/24 | 0 | 24 | [text-v1](../../data/cache/reports/judge-calibration-20261101-text-v1/20261101T062005Z-86598fcb/report.json) |
| 扩展方向说明的 v9 提示词实验，24 条 | 12/24 | 1 | 24 | [text-v9](../../data/cache/reports/judge-calibration-20261101-text-v9/20261101T062146Z-ee2498db/report.json) |
| 精简提示词，6 条定向 | 0/6 | 6 | 6 | [compact-pilot](../../data/cache/reports/judge-calibration-20261101-compact-pilot/20261101T062406Z-845a27a0/report.json) |
| 精简提示词明确对象结构后，2 条 | 0/2 | 0 | 2 | [compact-shape-fix](../../data/cache/reports/judge-calibration-20261101-compact-shape-fix/20261101T062446Z-80a62b98/report.json) |
| 双向模式初次定向，4 条 | 0/4 | 4 | 4 | [bidirectional-pilot](../../data/cache/reports/judge-calibration-20261101-bidirectional-pilot/20261101T062719Z-c8c3b8b7/report.json) |
| 双向模式限制 claim 字段后，4 条 | 4/4 | 0 | 8 | [bidirectional-shape-fix](../../data/cache/reports/judge-calibration-20261101-bidirectional-shape-fix/20261101T062748Z-af3354d5/report.json) |
| 相同双向提示词，完整 24 条 | 20/24 | 0 | 48 | [bidirectional-full](../../data/cache/reports/judge-calibration-20261101-bidirectional-full/20261101T062805Z-435fa5ab/report.json) |

总计 116 次实际 Judge 请求、0 次修复请求；已知 prompt/completion tokens 合计 144801/14109，不由此估算账单。首次 shell 配置未正确传入 Judge 地址时在请求前失败，没有进入上表计费请求；其空输出目录不伪装成完成报告。

v9 实验恶化，不采纳为业务默认；实验源码保留在该报告目录的 `semantic-experiment.py`、`calibration-runner.py`。已恢复与原代码一致的 judge-v8 默认值；`compact`、`bidirectional` 仅通过新增校准脚本显式选择，不改变业务 CLI 默认评审条件。实验间提示词、请求次数不同，20/24 只表明此组已暴露参照的诊断改善，不证明泛化或业务质量提升。

### 剩余分歧

完整双向实测覆盖关系标签一致 21/24，真值标签一致 23/24，完全一致率 20/24（83.33%，名义 Wilson 95% 区间约 64.15%～93.32%）。参照是代理选取且语义相关的小样本，该区间不能解释为独立随机总体的可靠性保证。13 条非 entailed 参照中错误算覆盖为 0；17 条非 correct 参照中错误算正确为 0，不等于不存在其他错误。

| 参照 ID | 预期 → 观察 | 处置 |
| --- | --- | --- |
| partial-not-majority | truth: unverifiable → incorrect；覆盖均 partial | 将占主要色误当作排斥其他颜色；一方向 partial、反向 contradicted，不一致 |
| location-required | relation: partial → not_addressed；truth 一致 | 均不计覆盖，但位置与主体对应关系的类别边界仍有分歧 |
| planter-not-flowers | relation: partial → not_addressed；truth 一致 | 花盆/绿植与花朵的关系边界；未计覆盖，不为通过率改参照 |
| framing-not-answered | relation: partial → not_addressed；truth 一致 | 有人物不等于回答近景构图；两个关系均不计覆盖，仍保留分歧 |

随后新增双向矛盾关系一致性检测，遇到不对称返回 `semantic_consistency/contradiction_direction_mismatch`，不自动改标签或增加请求。该保护经离线模拟验证，**未重新发起真实请求，未把上述原报告重写为 20 passed/3 failed/1 error**。当前仍不能标记“文字 Judge 校准通过”，更不能据此声称真实看图、行为评审或 19 例业务诊断已通过。

### 免费验证与数据边界

- Windows 当前工作区 `tests/unit/test_evaluation_*.py` 加 `tests/api/test_evaluation_http_contract.py`：276 passed、3 条既有弃用警告。
- WSL 限定 Judge 协议/视觉通道/候选构建/定向修复/校准防护范围：118 passed、1 条既有弃用警告。与 Windows 范围不同，不相加。
- 新增校准脚本及测试通过 Ruff。两端均复核原 r3 的 535 文件摘要不变、候选清单列出产物摘要不变。哈希完整性检查不读取 heldout 的用例语义，也没有执行它们。
- `baseline_eligible`、`human_accepted`、`semantic_judge_calibrated` 均保持 false。没有修改标注、门槛、split 或原始失败报告，也未修改本轮工作区已有的 Memory/鉴权等并行开发内容。

下一步仍按用户决定使用同模型，先解决不对称矛盾与关系边界，并补像素/行为校准；之后执行已获准的 19 例独立诊断。暂不扩大为发布基线或 heldout 验收。

## 同模型 Judge 追加通道诊断（2026-11-01）

接上一节，继续使用官方 DeepSeek `deepseek-flash`；用户未要求换模型。以下为新独立实验，旧 24 条、原 r3、候选、标注、split、门槛及全部历史结果不覆盖。除表中首项为 disabled 外，均显式 thinking=enabled，max_repairs=0、SDK 不重试；文字预算4096，图片8192，Persona 预算见表。报告均已回存 Windows，私有 `.judge-debug` 未复制。

| 实验 | 结果 | 实际 Judge 请求 | 报告 |
| --- | --- | --- | --- |
| 边界说明 bidirectional-v2，旧4失败定向，disabled | 1 passed、1 failed、2 judge_error；未采纳为默认 | 7 | [boundary-pilot](../../data/cache/reports/judge-calibration-20261101-boundary-pilot/20261101T063706Z-f14a0bab/report.json) |
| 原 bidirectional + thinking enabled，旧4失败定向 | 1 passed、3 failed；truth 4/4、方向不一致0，3条关系边界仍有分歧 | 8 | [thinking-pilot](../../data/cache/reports/judge-calibration-20261101-thinking-pilot/20261101T063848Z-24c9e099/report.json) |
| Persona 固定合成三轮参照，4096 token | 5 passed、1 截断错误 | 6 | [persona-fixed](../../data/cache/reports/judge-calibration-20261101-persona-fixed/20261101T064356Z-36239070/report.json) |
| 仅 Persona 截断项，8192 token | 1/1，保留原失败；不拼成同条件6/6 | 1 | [truncation-check](../../data/cache/reports/judge-calibration-20261101-persona-truncation-check/20261101T064650Z-53d98282/report.json) |
| 红伞图片 normal/small 固定声明，原长结构提示词 | 3 passed、1 failed、2 schema错误 | 6 | [visual-pilot](../../data/cache/reports/judge-calibration-20261101-visual-pilot/20261101T064709Z-6ed3c51d/report.json) |
| 同6条，独立完整结构说明 | 5 passed、1 failed、0协议错误；small 蘑菇误判仍在 | 6 | [visual-shape-check](../../data/cache/reports/judge-calibration-20261101-visual-shape-check/20261101T064849Z-be91bad1/report.json) |
| 16条独立开发文字对照，原 bidirectional + thinking enabled | 10 passed、5 failed、1 schema错误 | 32 | [development-contrasts](../../data/cache/reports/judge-calibration-20261101-development-contrasts/20261101T064859Z-31ec5dca/report.json) |
| Persona-17 候选真实三轮业务诊断，8192 token | 1/1；事实覆盖1、行为满足1、Persona一致性1、风格0.93 | 1 | [persona-candidate](../../data/cache/reports/project-eval-20261101-persona-adjudicated-diagnostic/20261101T064940Z-c3ba77c7/report.json) |

本节新增 **67 次 Judge 请求、0 修复请求**，已知 prompt/completion tokens **71718/41389**；加上一节116次，累计183次、已知token216519/55498，仅是这两节实验用量，不包括旧业务回归或全部供应商账单。Persona 候选另有3轮 SUT 生成调用，不能当成包含在 Judge 预算内。首次 channel 的 runpy 模块类型解析错误发生在请求前，零调用，不伪造完成报告。

### 错误分析与实际修改

- Persona identity-denial 的4096 token全用于推理，finish_reason=length、最终判词为空。新增通道校准的显式输出预算参数（128～8192），不自动增加预算；8192单次复测成功。推理正文不记录，仅保留 reasoning_tokens 等统计。
- 图片原判词缺少 persona_violation/style_score 等字段。仅校准脚本改用完整结构的独立短说明，不放松 schema、不补默认正确值、不修改业务视觉提示词。错误声明在 small 图仍被认作 visible，两种提示词均出现，不能把格式修复当作视觉误判已解决。
- 16条文字开发对照中5条 partial→not_addressed 分歧分别涉及人物景别、海报方向、植物/花、椅子腿数、自行车子类。它们均不计覆盖，保留精确标签不一致。另1条 place-explicit-conflict 的反向判词把 evidence_quotes 输出成 [] 而不是 {}，严格拒绝；不尝试宽容转换或循环请求。
- 文字有效判词15条真值一致；原报告真值匹配15/16包含协议错误分母。错误覆盖/错误算正确计数为0仅针对获得可比较标签的判词，不代表异常项可靠，也不证明总体无误判。
- 固定Persona6条测事实范围、配置不算助手回答、安慰行为违反、跨轮身份矛盾及评审注入；不预设人工风格阈值。候选单例才调用SUT，scope=provider_component，faithfulness=null；没有部署API实测或新完整业务regression。

### 验证、完整性与停止点

Windows 评测单元/API contract **300 passed、2 deselected、3既有警告**；WSL Judge/视觉通道/候选/校准等子集 **169 passed、2 deselected、1既有警告**。两个排除项会加载原r3完整Persona或catalog，用来避免顺带读取heldout语义；其他用离线fixture验证，不是实际heldout执行。范围不同不相加，定向Ruff通过。

最终 JUnit：[Windows](../../data/cache/reports/judge-calibration-20261101-channel-verification/windows-evaluation-final.xml)、[WSL](../../data/cache/reports/judge-calibration-20261101-channel-verification/wsl-judge-final.xml)；整理前验证XML也保留。本节62个安全报告产物从WSL回存Windows并核验摘要；没有外拷原判词、日志、图片base64或密钥。后续参数边界整理只补跑免费测试，不重新调用模型或回写旧运行摘要。两端再次核验原r3每端535文件、候选每端19产物及其manifest，摘要一致、未接受状态不变；哈希检查不是heldout语义审阅。

本轮未启动业务API/容器、重建索引或修改并行Memory/鉴权开发。19候选仅完成Persona1例，Vision18例未运行；36图片参照只运行红伞组6条，其余30条未运行。继续沿用同模型不代表必须用其错误判词作发布依据，先明确人工像素复核与关系边界口径，停止同条件重复付费调用。未批准人工接受、发布基线或heldout执行。

## 首次判断修复保护与离线回归（2026-11-01）

本轮为上述诊断后的代码加固与免费回归，**没有新增真实SUT/Judge/embedding调用**，未启动API/容器、重建索引或访问部署服务。继续使用现有模型，未修改模型、gold、门槛、split、候选manifest或历史成绩。

### 证据与修复

1. Windows 离线截获实际 `_provider_verdict` 将要发送的12张候选图片消息，核对每张base64可严格解码、字节及SHA与资产一致、MIME正确、图片可解码。红伞normal为1536×838，小图为384×210，评测编码器无额外缩放。只证明客户端发送前载荷，不证明供应商内部视觉处理。[传输审计](../../data/cache/reports/judge-transport-audit-20261101/20261101T070007Z-c7ae8771/report.json)。
2. 用户局部人工确认红伞小图可辨认为伞，“是蘑菇”应判contradicted。对应图片摘要及范围见[审定记录](evaluation-adjudication-20261028.md#用户局部复核红伞小图)。这不是全部候选或发布验收，已有两轮模型误判保留。
3. 在 `semantic.Judge` 增加 `repair_policy=freeze-first-decisions-v1`，本地冻结可定位的首次判断。只有保持声明及truth/support/visual、行为、身份与风格、覆盖判断不变的结构修复才接受；gold通道按明确relation冻结，允许据此修正派生ID/绑定。变更判断为 `repair_semantics_changed`，不评分，也不继续重试。无法解析、截断、未知目标/非原文声明不建立保护摘要，直接保留原错误而非重新答一遍；合法低分仍不重试。
4. 对两组已归档v8真实修复对进行零网络回放。先核对4个原判词文件及payload摘要，再使用当前请求流程消费本地归档响应；appearance 的partial→contradicted、clothing 的partial→entailed均转为保护错误。未改写旧报告，也不是新生成或真实模型复跑。[历史回放](../../data/cache/reports/judge-repair-guard-history-20261101/20261101T070449Z-67df1f73/report.json)。

`tests/unit/test_evaluation_repair_guard.py`新增20项，包括合法绑定修复可通过、质量变化各维度拒绝、缺失判断/截断不另收费请求、gold关系变化与绑定修正对照、旧条件不混比及图片顺序/字节保持。首次免费兼容回归发现7项仍按旧宽松修复行为预期的测试；保留并收紧这些用例，不删除原反例，不将语义变更转为passed/failed来规避保护。

### 本轮实际 regression 与验证

| 运行 | 结果 | 证据 |
| --- | --- | --- |
| Windows 冻结离线 regression | 822/822；Judge请求0 | [report](../../data/cache/reports/judge-repair-guard-20261101/windows-offline-regression/20261101T070525Z-3d3be7f4/report.json) |
| WSL 冻结离线 regression | 822/822；Judge请求0 | [report](../../data/cache/reports/judge-repair-guard-20261101/wsl-offline-regression/20261101T070536Z-893d0bd4/report.json) |
| Windows 评测单元与进程内HTTP契约 | 320 passed、2 deselected、3既有警告 | [JUnit](../../data/cache/reports/judge-repair-guard-20261101/windows-evaluation.xml) |
| WSL Judge/校准/候选/保护定向子集 | 231 passed、2 deselected、1既有警告 | [JUnit](../../data/cache/reports/judge-repair-guard-20261101/wsl-judge.xml) |

离线822条均为组件层：583条offline_bm25、214条offline_policy、25条offline_policy_disabled_input，覆盖RAG、Memory与Vision策略，不含真实图片/Persona生成或部署API。两端源码/配置快照分别进入报告，不将其合成1644个独立样本，也不据此声称新完整业务回归通过。两条排除项仍为会加载原r3完整Persona/catalog的测试，避免读取heldout语义。定向Ruff、diff空白检查通过；旧完整业务回归仍为v6。

WSL仅同步本轮7个评测源码/测试文件，未同步或改写用户并行的Memory/鉴权开发；安全报告和JUnit归档至Windows，原判词不外拷。修复政策进入conditions，不能与旧缺少该字段的报告混作同条件发布基线。原r3与候选清单及图片保留，局部人工标签确认不改变baseline_eligible/human_accepted/semantic_judge_calibrated的false状态。

保护只解决格式修复漂移，不解决首次就出现的视觉/文字语义误判。Vision18候选仍未执行，不因这一保护或局部复核擅自扩大付费调用；heldout继续由用户最终验收。

## Vision 候选独立诊断与覆盖绑定派生（2026-11-01）

继续执行已获准的19例独立诊断，沿用DeepSeek同模型Judge。此前Persona单例已执行，本节对18条Vision候选各调用一次真实隔离API，6组图片、3种变体；不是原r3回归或发布基线，也不是18个独立来源。没有审阅或执行heldout。

### 真实执行与用量

| 分项 | 条件 | 结果 | Judge请求 | 报告 |
| --- | --- | --- | --- | --- |
| 红伞3条 | 原视觉提示词，thinking enabled，8192 token | 0 passed、1 failed、2 judge_error | 4 | [report](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/20261101T072217Z-9d26a094/report.json) |
| 红伞原两份失败回答的固定输入诊断 | 新连续原文规则，thinking enabled，仅视觉通道 | 2份引用均合法，不判断gold质量 | 2 | [report](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/quote-policy-fixed-answer-diagnostic/report.json) |
| 琵琶3条 | 新连续原文规则，thinking enabled，8192 token | 1 passed、1 failed、1 judge_error | 6 | [report](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/20261101T072835Z-c6366d77/report.json) |
| 其余12条 | 新连续原文规则，thinking disabled，8192 token | 5 passed、3 failed、4 judge_error | 24 | [report](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/20261101T073229Z-0f0d9e00/report.json) |

不同提示词、thinking及分组不混作同条件通过率，不与原r3或此前候选Persona单例相加做质量分数。固定输入两条并非重新生成或改写旧失败；其正确引用只证明这两次协议合法，不证明视觉和目标覆盖判断已校准。全部请求max_repairs=0、SDK不重试；合法质量失败、截断和协议异常均保留。

本节共 **36次Judge请求、0修复**，全部有usage，已知prompt/completion token **90107/62765**，达到预先固定上限，不再追加调用。业务部分34次、固定回答引文诊断2次。API访问日志记录18次`/vision/analyze`成功响应，SUT内部模型尝试/重试次数未测，不把Judge预算冒充整链路费用。

隔离依赖恢复既有评测Redis Stack/Qdrant，未使用WSL自带6379 Redis；新建本轮Redis prefix、Memory集合、上传和偏好路径。API只绑定127.0.0.1:18080；模型非mock，ASR/TTS仍mock且不在测试范围。RAG现有索引fresh、3364向量/4096维，无重建；CLIP使用冻结reference-gallery、本地缓存、CPU和离线加载。WSL业务源码仍为已归档v8快照加显式评测修改，不能冒充Windows并行Memory/鉴权代码的实测。

### 问题归因与实际修复

- 红伞normal四项目标全部覆盖，但额外“抬起右手”被判contradicted，visual_unsupported_rate=1/17；这是细节问题，不是再次要求模型迎合蘑菇错标。左右坐标口径及腿环判断仍需逐项复核，不把同模型单次判断当最终事实。
- 琵琶small未描述长发，目标覆盖2/3；wrong-hint回答出现短发描述，gold通道8192 token全用于thinking、最终判词为空。保留截断异常，不加token或重新生成追分。
- 初段两条视觉判词补写主语/否定词，严格校验返回claim_quote_not_in_answer。只改独立视觉提示词，使连续原文优先于拆分；无法独立截取时允许完整复合引用，但任何被反驳的细节仍不能判visible。其后15条业务视觉判词未再触发该引用错误，不能由不同图片/条件推导通用成功率。
- 关闭thinking后仍有真实文字误判：d028正常回答明确列出背景河道、建筑与树木，Judge却把对应三个目标评为partial。代理文字复核标记为疑似评审错误，原分数保持；食物位置等其他目标另审，不一概放宽。
- 最后12条中4份gold判词已明确给出entailed及原文绑定，却重复输出空covered_gold_ids/coverage_claims，触发coverage_assessment_bindings_mismatch。未启用重试、不自动修正旧判词。
- 真实运行之后新增**默认关闭**的`--judge-derive-gold-bindings`：使用紧凑GoldDecisions，只接收quote/truth与coverage_assessments，由代码派生覆盖列表。需要Provider、显式双通道和max_repairs=0，CLI拒绝--release；原默认模式仍严格拒绝上述旧格式矛盾。新identity和提示词摘要进入conditions。
- [四份历史结构回放](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/derived-gold-structure-replay.json)先核对来源摘要，再将原明确真值/关系/引文投影到新schema；4份均保真并通过原严格校验，不改变任何语义标签，不评分或重写旧报告。**没有真实模型使用新协议的证据**，也不宣称截断或语义误判已解决。

### 留档、防护与验证

新增请求前本地脱敏输入留档：先构造payload并保存`HASH-input.json`，再调用Judge。请求、解析或截断失败仍能复核SUT已生成回答；写入失败在请求前停止，公共报告不增加原文。记录原/存储摘要与payload_transformed，禁止自动回放或标成人工接受。未开启debug不留原文，现有Linux0700/0600和独占写入保持。

18条独立待复核材料仅保存在WSL本轮目录`.review/pending-review.json`，含来源报告/输入/观察/图片摘要与pending状态，既不是--manual输入，也不自动评分。自动结果、代理意见和用户人工确认分开；原红伞小图局部人工确认继续有效，不扩展到本轮其余判断。

最终免费验证：Windows评测单元/API契约 **360 passed、2 deselected、3既有警告**；WSL定向 **139 passed、1 deselected、1既有警告**，范围不同不相加。新增10条留档、8条视觉引用、22条派生模式测试，含坏引文、错误真值/目标/绑定、合法低分、重复JSON、CLI及release对照；定向Ruff通过。JUnit：[Windows](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/windows-final.xml)、[WSL](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/wsl-final.xml)。全工作区diff另有用户并行Memory文件的既有空白告警，本轮未改动这些文件；本轮文件定向diff检查通过。

两端再次核验原r3每端535文件、候选每端19产物及manifest不变，资格标志仍为false。清单中的providers_called=false/http_requests_sent=0是构建时快照，不回写为新执行事实。[安全运行索引](../../data/cache/reports/vision-candidate-diagnostic-20261101T072006Z/campaign-index.json)单列实际报告、条件与预算；只回存安全报告/源码快照/JUnit，不复制`.judge-debug`、`.review`、API日志或凭据。收尾时核对PID命令和本轮Redis prefix后停止自建API，并停止此次恢复的两个评测容器；未停止WSL自带Redis或其他项目，持久卷和所有数据保留。

19例获准诊断均已执行不等于通过、人工接受或发布；最近完整业务回归仍为v6。本轮不运行其余30条固定图像参照、不扩大免费测试为全项目证明、不执行heldout；新协议的真实固定回答验证和人工审阅仍待后续明确预算。

## 免费兼容审计与预算前置检查（2026-11-01）

本节是上节之后的免费验证，不追加真实Judge或SUT调用，不重复生成候选回答，不接触heldout。继续使用用户指定的同模型Judge；额外4次固定回答紧凑gold诊断尚未执行，等待单独确认预算，不将既有19例许可扩展为不限次请求。

### 预算漏洞与修复

模拟响应复现了双通道剩余预算为1时，旧检查仍先生成一次SUT回答、发送一次视觉评审，再因gold额度不足而失败。现在在observer前检查完整初始评审最低额度：文本单通道1次，显式视觉双通道的图像用例2次；不足即budget/request_budget_exhausted，生成与Judge请求均为0。默认预算和执行检查共用semantic.minimum_judge_requests；identity新增budget_policy=complete-initial-review-v1。

该策略只要求初始通道额度，不强制预留可选格式修复，也不保证请求成功或限制SUT内部费用。新增23项测试包含边界额度、两种gold模式、合法低分、文本单次请求及双通道真实风格/视觉判定不被gold占位覆盖。未改评分公式、gold、门槛、split或旧报告。

### 全部18例兼容审计

先验证原campaign索引和来源报告SHA，再读取本地已留档判词；没有网络或模型重放。[审计报告](../../data/cache/reports/derived-gold-compatibility-20261101/report.json)：

| 分类 | 数量 | 实际检查 |
| --- | --- | --- |
| 原有效判词 | 11 | claims与coverage_assessments保持原判断；新结构投影后，实际双通道合成全部指标与原报告逐项相同 |
| 冗余绑定字段矛盾 | 4 | 仅投影明确原判断并校验结构，不重新评分、不重写旧异常 |
| 原视觉引用错误 | 2 | 保留原失败，不补写引文 |
| 原gold截断 | 1 | 保留原失败，不补全判词或追加token |

调试时曾直接比较gold单通道全部指标，因固定style占位与旧模型输出不同而断言失败；正式审计按真实合成路径检查，gold占位不会替换视觉通道风格/行为/图片判断，11份有效结果完全一致。这个修正避免把错误比较口径当成评分回归。结构兼容不能证明新提示词会被模型遵守，也不能消除首次语义误判。

### 最新验证与范围

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Windows评测单元/进程内HTTP契约 | 383 passed、2 deselected、3既有警告 | [JUnit](../../data/cache/reports/derived-gold-compatibility-20261101/windows-final.xml) |
| WSL评测防护定向子集 | 162 passed、1 deselected、1既有警告 | [JUnit](../../data/cache/reports/derived-gold-compatibility-20261101/wsl-final.xml) |
| Windows离线regression | 822/822、Judge0 | [20261101T075156Z-4d98d067](../../data/cache/reports/derived-gold-compatibility-20261101/windows-offline-regression/20261101T075156Z-4d98d067/report.json) |
| WSL离线regression | 822/822、Judge0 | [20261101T075204Z-fa870a59](../../data/cache/reports/derived-gold-compatibility-20261101/wsl-offline-regression/20261101T075204Z-fa870a59/report.json) |

两端离线执行均阻断socket网络连接，仅选择原r3的regression：583条offline_bm25、214条offline_policy、25条offline_policy_disabled_input。不是1644个独立样本，不含真实图片/Persona生成或部署API；最近完整业务回归仍为v6。排除会加载完整r3 Persona/catalog的两项测试，WSL定向子集只涉及其中一项，避免读取heldout语义。测试范围不同不相加，也不宣称全项目测试通过。

核验两端4个本轮评测源码/测试文件SHA一致，只同步评测文件，不覆盖用户并行Memory/鉴权业务。13份白名单安全报告/JUnit在两端归档并核对摘要，不复制私有判词、待复核原文、API日志或env。两端原r3各535文件、候选各19产物和manifest摘要不变，资格仍为false；这是字节完整性检查，不是heldout语义审阅。评测文档同步，定向Ruff与本轮文件diff检查通过；全工作区其他文件的既有空白告警不在本轮处理范围。

下一步仍是独立复核已保存回答与像素，区分SUT细节错误和Judge误判；如获准，再固定回答、固定预算检验新紧凑gold协议。当前不运行heldout、release或额外付费请求，不因免费验证通过而将候选标成人工接受或发布基线。

## 候选18例像素与回答代理复核（2026-11-01）

直接查看候选的6组normal/small实际上传图，共12张；逐例核对18条原回答、视觉判词和gold关系。源report、input、observation和图片摘要与私有待复核清单全部匹配，18份输入均未变换；清单读取时SHA为`0dcb9b919e524c64af8afd13fc9ac6a8d0ec11757a9d7973c7516c62d4b02255`。私有清单、原回答和判词不外拷、不写回或转换成manual；原自动结果、gold和候选资格不变。

[逐项意见](evaluation-adjudication-20261028.md#候选18例原图与回答代理复核)集中在原审定文档，避免再建日期说明页。新增实质发现：红伞的抬手与腿环方向在Judge中采用不一致坐标；近景小图把羽状衣饰说成手和蓝色指甲却被自动判visible；白发目标和海报多行文本也有蕴含判分分歧。琵琶小图的长发虽在像素中可见，却未在回答中提到，不能由代理替SUT补答。以上除既有红伞/蘑菇用户确认外均是代理意见，不冒充人工标签或重新评分。

定向免费回归：Windows视觉引用、视觉通道、派生gold和通道校准4个测试文件，**61 passed、1条既有依赖弃用警告**，运行前阻断socket连接；[JUnit](../../data/cache/reports/vision-candidate-agent-review-20261101/windows-review-regression.xml)。是现有测试的定向复跑，不是新增61个用例，不与此前383项相加。没有新业务模型实测，不重跑无代码变化的822条离线集；最近两端离线仍各822/822，最近完整业务回归仍v6。

本节0次Judge、0次SUT，不运行其余30条固定图片参照、release或heldout。近景小图局部人工复核已询问但尚无答复；4次固定gold真实诊断仍待单独确认预算。只能在这些边界明确后验证实际协议/视觉可靠性，不能靠无关代码改动或重复免费测试冒充质量闭环。

### 后续用户确认：近景衣饰而非手与指甲

2026-11-01 用户回复：“是衣饰，不支持手和蓝色指甲的说法”。[完整局部记录](evaluation-adjudication-20261028.md#用户局部复核近景小图衣饰)绑定`vision-d91513554e01-small@1`及实际上传图片摘要；图像SHA已核验。该条从代理疑点转为用户确认的局部业务错认与Judge漏检。上文“尚无答复”保留为当时快照，以本节为后续状态。

只更新3份评测文档并同步WSL；原passed报告、判词、分数、gold、候选资格和私有待复核清单不变。不重跑模型或测试，不将已有测试计数当作本次新增验证；本次0次Judge、0次SUT。此回复不包含4次紧凑gold诊断预算授权，后续真实协议验证仍待确认，heldout未审阅或执行。

## 固定回答诊断与12次校准（2026-11-02）

用户后续分别授权4次固定回答gold诊断、最多12次同模型Judge校准，并选择**继续校准自动Judge，通过后再冻结验收条件**；不使用人工兜底替代自动验收。两笔预算均已用完，全部每条一次、零修复、SDK零重试；没有SUT、embedding、API业务调用，没有运行或审阅heldout，不推进V1.2第五批/前端或覆盖并行Memory/鉴权代码。

统一使用官方DeepSeek `deepseek-flash`、thinking disabled、max_output_tokens=8192。三个实验的提示词与任务不同，必须分别解释，不合并为总体质量通过率，也不与旧v6回归作同条件提升比较。

| 实验与安全报告 | 结果 | Judge请求 | 已知输入/输出token |
| --- | --- | --- | --- |
| [保存回答gold诊断](../../data/cache/reports/fixed-saved-gold-diagnostic/20261102T085940Z-36fb6196/report.json) | 4份protocol valid，quality_pass_rate=null，不是质量4/4 | 4 | 4584/1478 |
| [修饰语与完整覆盖参照](../../data/cache/reports/judge-readiness-text-20261102/20261102T091351Z-1351a7dd/report.json) | 5 passed、3 failed、0 judge_error | 8 | 6340/444 |
| [真实图片正反参照](../../data/cache/reports/judge-readiness-visual-20261102/20261102T091529Z-c9fbe818/report.json) | 2 passed、2 failed、0 judge_error | 4 | 3256/312 |

本节共16次Judge请求，已知prompt/completion token为**14180/2234**，16份响应均有usage；不是全部历史账单或未来预算。4次固定回答与后续12次分开授权，没有把局部视觉确认当成额外调用许可。

### 保存回答诊断：结构合法不等于语义正确

新增受限入口 `scripts/diagnose_saved_gold.py`，仅对4个预先固定的regression case执行。先核验私有packet、原报告、input、observation、gold及摘要，拒绝错配、输入变换与路径越界；保留原claim_quotes，不调用SUT、不上传图片、不把旧判词发送给模型。执行需要三个显式开关，固定预算4、修复0。公共报告只保存安全摘要、关系和真值变化计数，所有接受/发布/校准资格保持false。

实际结果：河道wrong-hint的water从partial变entailed；Q版wrong-hint的hair_tone从partial变entailed，outer/inner仍partial；两份近景的四个目标仍entailed。但共7条truth从unverifiable变correct，涉及gold未证实的3D风格、具体发色、长发等限定，不能因协议可解析就重算旧失败或认定可靠。原判词/分数不变，新报告不生成质量通过率。

报告目录`source-snapshot`保存此次请求时的semantic.py和runner，早于随后补强规则；不能拿最新源码冒充这4次的运行条件。

### 12次校准：文字与视觉仍未通过

之后补强 `GOLD_DECISIONS_PROMPT`：truth必须证实整个quote的全部限定；增加盒子具体/概括的双向例子，不从覆盖反推真值。文字校准脚本新增 `--gold-policy derived`，直接调用当前运行时紧凑协议，输出预算显式设置，不改其他策略默认值。

新开发参照[文字8例](judge-readiness-text-20261102.json)包含修饰语真值4条、完整覆盖4条；标签是代理开发参照，不是人工金标，不修改原数据/gold/阈值。实际7/8关系匹配、5/8真值匹配，逐例通过5/8：

| 失败ID | 预期relation / truth | 实际relation / truth | 归因 |
| --- | --- | --- | --- |
| modifier-cup-general | partial / correct | partial / unverifiable | 具体事实能证实逻辑概括，不应因省略修饰语否认真值 |
| modifier-car-general | partial / correct | partial / unverifiable | 同上，覆盖不足与声明错误是不同方向 |
| coverage-location | partial / unverifiable | contradicted / incorrect | 门旁与窗边没有明确排他条件，可以共存；不能仅因位置词不同断言冲突 |

本组false_coverage_count=0、false_truth_count=0，仅表示没有这两类误放行；3条其他语义分歧仍是失败，不能只选某个误报计数宣布校准通过。

视觉通道和固定图片脚本共享新增 `VISUAL_GROUNDING_RULE`，要求结构、位置和肢体连接证据。新[视觉4例参照](judge-readiness-visual-20261102.json)仅选择两张已确认small图的正反声明，不执行prepare产生的normal变体：

| 参照ID | 预期 | 实际 | 结果 |
| --- | --- | --- | --- |
| vision-5a93ca83c3b4-small-umbrella | visible | visible | passed |
| vision-5a93ca83c3b4-small-wrong-object | contradicted | visible | failed，蘑菇错认再次漏检 |
| vision-d91513554e01-small-framing | visible | visible | passed |
| vision-d91513554e01-small-wrong-fingers | contradicted | visible | failed，衣饰错认手/指甲再次漏检 |

两个负例沿用用户局部确认，正例为开发参照，不扩大成人工接受整例。所有真实请求结构合法；共享规则仍未解决视觉语义问题。不通过改标签、忽略反例、重试取最好结果或manual判词绕过自动校准。其余旧固定图片参照仍按旧实验状态保留。

### 免费核验、归档与停止点

普通HTTP GET核对[官方视觉指南](https://api-docs.deepseek.com/guides/vision/)与[模型表](https://api-docs.deepseek.com/quick_start/pricing/)，未调用收费Search/Fetch或模型接口：当前deepseek-flash支持图片，OpenAI兼容user消息、base64 image_url和当前端点均符合指南；auto当前等价original。没有证据要求更换模型别名或改detail。另增加PNG/JPEG真实SDK序列化契约，以MockTransport检查最终请求、原始图片字节/SHA/MIME、模型、thinking和标签隔离，零网络。由此未发现本地图片装配错误，但不能证明远端使用像素，更不能断言模型不支持图片或自动校准已经通过。

安全报告、plan、逐例结果与本次12请求对应的源码/参照快照已归档两端；实际prompt与runner摘要核验一致。私有`.judge-debug`、`.review`、原始判词、密钥及模型推理正文未外拷。新源码快照与前4次旧快照分别留存，不修改冻结r3或候选manifest。

| 免费验证范围 | 结果 | 证据 |
| --- | --- | --- |
| Windows评测单元/进程内HTTP契约 | 399 passed、2 deselected、3既有警告 | [JUnit](../../data/cache/reports/judge-readiness-verification-20261102/windows-final.xml) |
| WSL评测防护与校准定向子集 | 214 passed、2 deselected、1既有警告 | [JUnit](../../data/cache/reports/judge-readiness-verification-20261102/wsl-final.xml) |

两端测试执行时阻断网络，Windows仅允许asyncio内部socketpair建立所必需的loopback连接，不开放普通API或外部网络。排除两项会加载原r3完整Persona/catalog的测试，避免顺带读取heldout语义。测试范围不同，不相加，不等于业务实测/远端Judge可靠性证明。定向Ruff通过。最近离线业务regression仍是11-01两端各822/822，本节未无变化重复；最近完整真实业务回归仍v6。

此前Windows验证曾因对socket的全局阻断误伤asyncio自用socketpair，出现8 failed/386 passed/2 deselected；只调整测试进程的网络拦截，未改产品代码，随后394 passed。两个原JUnit均保留在4次诊断目录`windows-final.xml`与`windows-corrected.xml`，不掩盖工具执行失误。新增校准及SDK测试后的当前结果以上表为准。旧WSL173项定向报告同样保留，不冒充214项是新增独立样本。

**当前heldout readiness=false。** 剩余顺序：先预先固定完整文字/视觉/Persona校准范围及门槛，解决上述自动Judge分歧并在另获预算后验证；再执行同条件业务regression，冻结数据/标注/源码/提示词/模型/环境/费用，最后交给用户做heldout。不能以有限子集通过、代码可运行或局部人工确认代替这些条件。此次预算已用完，无进一步真实请求授权，不启动服务、release、heldout或额外付费实验。

## 盲描述与独立双向诊断（2026-11-02）

用户另行明确授权最多12次同模型Judge请求，分配固定为两图盲描述2次、4条固定声明的文字核验4次，以及3条失败文字参照的独立双向蕴含6次。全部执行完，**12次Judge、0修复、SDK零重试、0次SUT、未审阅或运行heldout**。同一官方DeepSeek模型、thinking disabled、8192输出预算，不改变标注、门槛或split，不为质量失败补请求。

执行前保存runner、semantic与两份参照源码快照；输入固定为既有regression开发参照。盲描述不含待核验声明、gold或标签；文字核验只看自动描述，不再上传图片，也不接收预期关系。该实验有意区分“原图观察错”与“收到声明后的核验错”，不是新正式视觉评分器，也不输出质量pass_rate。

| 分项及安全报告 | 请求 | 实际结果 | 已知输入/输出token |
| --- | --- | --- | --- |
| [盲描述及文字核验](../../data/cache/reports/judge-causal-diagnostic-20261102T093746Z/visual/20261102T093812Z-eed01dcc/report.json) | 6 | 2份描述结构合法，文字核验与参照匹配2/4；0 judge_error | 2662/556 |
| [独立双向文字判断](../../data/cache/reports/judge-causal-diagnostic-20261102T093746Z/text/20261102T093854Z-1dbedea4/report.json) | 6 | 2 passed、1 failed、0 judge_error | 4703/732 |

本节已知输入/输出token合计**7365/1288**，12份响应均有usage。不同分项不合算通过率，也不与此前16次实验混作同条件基线；授权已全部用完，不追加付费请求。

### 视觉诊断结果

| 固定声明 | 仅依自动描述核验的结果 | 解释 |
| --- | --- | --- |
| 前景有红色伞 | entailed，匹配 | 盲描述提到前景红色伞状物 |
| 前景巨大红色物体是蘑菇 | contradicted，匹配 | 此次移除声明的观察先得到伞状物，后续文字核验没有再接受蘑菇 |
| 人物胸部以上近景 | not_mentioned，不匹配 | 盲描述未明确记录这一构图关系，后阶段没有靠原图或预期标签补证据；描述遗漏使正确声明也无法确认 |
| 左下有手的局部和蓝色指甲 | entailed，不匹配 | 没有待核验声明的盲描述仍主动生成手/指甲，随后文字核验继续接受，与用户已确认的衣饰事实相违 |

说明：两阶段能缓解本次红伞反例的声明诱导，但不能证明这是此前全部错误的原因；至少近景错误在独立观察阶段已经出现。后阶段又接受了从下方到左下的细化表述，完整限定核验仍不可靠。不能将盲描述当人工真值、用其自洽证明看图正确，或把2条匹配当视觉校准通过。私有原文留在WSL显式debug，公共结果只保存摘要、关系和引文数量，不导出原始描述。

### 文字诊断结果

复用已存在的 `bidirectional-v2` 校准策略，未新增另一套生产语义实现。前向检查答案是否覆盖gold，反向独立检查gold是否证实答案，两次请求互不见判词。

- modifier-cup-general：partial / correct，符合参照。
- modifier-car-general：partial / correct，符合参照。
- coverage-location：前后两方向均contradicted，真值incorrect；预期仍partial / unverifiable，失败保留。方向一致性保护不会捕获“两边一致地错判”，不能以一致性代替语义正确。

两条概括从单次紧凑判断的失败变为本次独立双向匹配，是不同协议/预算下的诊断证据，不是完整文字校准通过或统计显著改善。位置互斥误判尚未解决，不回写旧报告，也不因先前失败而删改该参照。

### 实现与免费回归

新增 `scripts/diagnose_judge_grounding.py` 作为显式执行的受限工具，固定两图四声明、硬预算6、零修复，默认dry-run；核验图片与候选来源摘要，严格JSON，文字引文必须来自确定描述；任一协议/请求错误停止余下调用。所有接受/发布/校准资格false，scope明确为自动描述文字一致性，`quality_pass_rate=null`，不接入正式评分。17项新免费测试覆盖信息隔离、预算、摘要、严格解析、引用、异常停止和禁止覆盖旧证据。

| 免费验证 | 结果 | JUnit |
| --- | --- | --- |
| Windows评测单元与进程内HTTP契约 | 416 passed、2 deselected、3既有警告 | [Windows](../../data/cache/reports/judge-causal-diagnostic-20261102T093746Z/windows-final.xml) |
| WSL评测防护与校准定向子集 | 231 passed、2 deselected、1既有警告 | [WSL](../../data/cache/reports/judge-causal-diagnostic-20261102T093746Z/wsl-final.xml) |

测试阻断网络；Windows仅允许asyncio内部socketpair初始化的loopback。排除会加载完整原r3 Persona/catalog的两项测试，避免顺带读取heldout语义。范围不相加、不代替真实模型或业务回归。定向Ruff通过；源代码和prompt摘要与请求前快照匹配。安全JSON、源码快照和JUnit归档两端，私有`.judge-debug`不外拷，原r3/候选/旧报告不修改。默认评分未变，不重复无变化的822条离线业务集或扩大为新付费完整回归。

**目标仍未完成，heldout readiness仍为false。** 当前证据不支持将盲描述或双向判断直接切为默认验收方案；自动视觉观察仍会错认，文字核验仍会把非排他关系当冲突。先保留并分析这些真实失败，不能靠持续追加提示词、小样本重试、降低标准或改用人工兜底宣布自动校准成功。本节额度已用完，未经新的明确授权不继续付费。

## 原图小图与位置关系对照（2026-11-02）

用户另行授权继续使用deepseek-flash、最多12次请求，查看两组原图/小图后确认素材正确，并明确近景左下蓝白尖状物是衣服饰品而非指甲；按8次视觉、4次文字执行。局部确认的图片SHA与范围见[审定记录](evaluation-adjudication-20261028.md#用户再次确认素材与局部口径2026-11-02)。该答案不写入Judge提示词，不扩大成人工接受全部候选。

全部请求thinking disabled、8192输出预算、每步一次、零修复、SDK零重试；**12次Judge、0次SUT，没有审阅或执行heldout**。源码与参照快照在请求前保存，prompt/runner摘要与实际运行匹配；原r3、候选、旧标注/报告不改写。

| 分项与安全报告 | 结果 | Judge请求 | 已知输入/输出token |
| --- | --- | --- | --- |
| [两图两分辨率正反声明](../../data/cache/reports/judge-resolution-position-20261102T095304Z/visual/20261102T095315Z-8cbd5997/report.json) | 6 passed、2 failed、0 judge_error | 8 | 8870/628 |
| [位置共存与排他对照](../../data/cache/reports/judge-resolution-position-20261102T095304Z/text/20261102T095337Z-ca62c5d6/report.json) | 3 passed、1 failed、0 judge_error | 4 | 3874/253 |

已知输入/输出token合计**12744/881**，12份响应均有usage，额度已全部用完。两个分项和旧实验不合算总体质量通过率。

### 视觉：本轮原图通过，小图反例仍漏检

两图各两个声明，原图与小图使用完全相同的FIXED_VISUAL_PROMPT、模型与声明；每条独立请求，不把正例或先前结论发给另一条。唯一有意变化为图片字节与分辨率。

| 图片与声明 | normal | small |
| --- | --- | --- |
| 红伞场景：前景有红伞，预期visible | visible，通过 | visible，通过 |
| 红伞场景：前景巨大红色物体是蘑菇，预期contradicted | contradicted，通过 | visible，失败 |
| 近景：胸部以上近景，预期visible | visible，通过 | visible，通过 |
| 近景：左下手的局部和蓝色指甲，预期contradicted | contradicted，通过 | visible，失败 |

原图两张均为1536宽，小图分别384×210与384×216；本轮normal4/4、small2/4，支持分辨率影响这两组样本的判断，但只有两组来源，不足以声称因果唯一、统计显著或所有原图可靠。没有重试或追加局部裁剪，不把小图替换成原图来制造同条件通过；不能据此取消低分辨率用例、降低门槛或解除完整视觉校准要求。

### 文字：通用开放世界规则尚未泛化

新增显式 `derived-open-world` 实验，复用紧凑gold结构，只补通用逻辑边界：不同位置关系不自动互斥，未知不是否定；同一对象可同时满足多个关系；明确否定、唯一位置或真正排他仍按冲突判断。正式运行时GOLD_DECISIONS_PROMPT和评分默认值均未改，既有策略默认不变。

独立[4条位置开发参照](judge-readiness-position-20261102.json)在请求前固定，为代理标注而非人工金标；预期标签不进入模型输入，旧8条参照保持原样：

| 参照 | 预期relation / truth | 实际relation / truth | 结果 |
| --- | --- | --- | --- |
| position-can-coexist：门旁/窗边桌上有水果 | partial / unverifiable | partial / unverifiable | passed |
| position-independent-relations：同一长椅在公园/河边 | partial / unverifiable | contradicted / incorrect | failed |
| position-explicit-negation：桌子在门旁/不在门旁 | contradicted / incorrect | contradicted / incorrect | passed |
| position-exclusive-side：灯只在左侧不在右侧/在右侧 | contradicted / incorrect | contradicted / incorrect | passed |

原门旁/窗边分歧修正，并保留对显式否定/排他的识别，但新共存关系仍失败；这是对已暴露边界补规则后的开发结果，不是泛化校准通过。不能据3/4改成正式默认、删除公园/河边难例或继续请求到通过。

### 免费回归与状态

| 范围 | 结果 | JUnit |
| --- | --- | --- |
| Windows评测单元/进程内HTTP契约 | 418 passed、2 deselected、3既有警告 | [Windows](../../data/cache/reports/judge-resolution-position-20261102T095304Z/windows-final.xml) |
| WSL评测防护与校准定向子集 | 233 passed、2 deselected、1既有警告 | [WSL](../../data/cache/reports/judge-resolution-position-20261102T095304Z/wsl-final.xml) |

两项新增测试覆盖开放世界策略显式选择、不泄漏标签、不改变运行时默认，以及固定参照中未知与明确冲突的区分。测试阻断网络，Windows仅允许asyncio内部socketpair初始化；排除会读原r3完整Persona/catalog的两项，避免读取heldout语义。定向Ruff和diff空白检查通过。两端范围不相加，不代替真实模型或部署业务验证；默认评分未变，未重复无变化的822条离线业务集，最近完整真实业务回归仍v6。

安全JSON、源码/参照快照和JUnit归档两端，私有debug不外拷。所有候选资格保持false，默认评分、split、门槛和旧报告不变。**目标仍未完成，heldout readiness=false**：低分辨率视觉漏检和文字关系泛化失败仍在，不以原图或已通过子集替代完整校准。当前12次授权已用完，不自动追加费用。

## 小图最近邻放大对照（2026-11-02）

用户另行授权最多8次deepseek-flash Judge请求，检验同一小图2倍/4倍非生成式放大是否能改善判断；两组图片各正反声明、两种倍数，各一次、零修复、SDK零重试。不读取原图像素补细节，不调用SUT，不审阅或运行heldout，旧失败保留。

新增受限工具 `scripts/calibrate_evaluation_image_scale.py`，复用固定小图选择和原视觉通道；提示词、声明、标签不变，仅改变图片输入。最近邻复制解码RGB，保存为PNG，8个诊断case共用4张生成图。源/生成SHA、尺寸、倍数、变换身份及像素恢复写入独立manifest；case ID与identity明确标出变换，不能冒充原小图条件。请求前源码与参照快照保留。

[真实报告](../../data/cache/reports/judge-small-scale-20261102T100453Z/20261102T100510Z-5772f14a/report.json)：**2 passed、6 failed、0 judge_error**；8次Judge、0修复、0次SUT，thinking disabled、8192输出预算。已知输入/输出token为**8962/628**，8份响应均有usage；额度已用完，没有额外请求。

| 声明与预期 | 2倍结果 | 4倍结果 |
| --- | --- | --- |
| 红伞场景有红伞，visible | contradicted，失败 | contradicted，失败 |
| 红色物体是蘑菇，contradicted | visible，失败 | visible，失败 |
| 人物胸部以上近景，visible | visible，通过 | visible，通过 |
| 左下手的局部和蓝色指甲，contradicted | visible，失败 | visible，失败 |

两种倍数各1/4，不能合成8个独立来源；未改善已知负例，红伞正例还被否定。原小图/原图报告保持原样，不将该结果标成统计显著恶化或唯一原因证明。变换同时改变尺寸、像素块形态与编码格式，不能由它单独断言“只是服务端尺寸问题”或“唯一原因是信息丢失”。它足以否定将本次简单最近邻放大直接作为修复方案，不接入默认评分，不继续追加倍数直到通过。

### 免费验证与归档

- 对实际4张落盘PNG做独立字节审计，逐行逐像素构造源小图RGB的整数复制结果，全部完全一致；未使用原图或生成式补细节。该证明仅关于字节变换，不证明模型语义判断正确。源尺寸384×210/384×216；生成尺寸768×420/1536×840及768×432/1536×864。
- runner、实际视觉提示词、变换清单与请求前源码/参照快照摘要匹配。原r3、候选、gold、split、阈值和历史报告不改写。
- 6项新免费测试覆盖像素复制与原输入不变、来源/输入摘要错误前置拒绝、8请求和标签隔离、默认dry-run及显式许可。定向Ruff、diff空白检查通过。

| 免费回归范围 | 结果 | JUnit |
| --- | --- | --- |
| Windows评测单元/进程内HTTP契约 | 424 passed、2 deselected、3既有警告 | [Windows](../../data/cache/reports/judge-small-scale-20261102T100453Z/windows-final.xml) |
| WSL评测防护与校准定向子集 | 239 passed、2 deselected、1既有警告 | [WSL](../../data/cache/reports/judge-small-scale-20261102T100453Z/wsl-final.xml) |

回归阻断网络，Windows仅允许asyncio内部socketpair初始化；排除会加载完整r3 Persona/catalog的两项测试，避免读取heldout语义。两端范围不相加，也不代替真实业务或自动Judge校准。安全JSON、4张非生成式放大PNG、源码快照和JUnit归档两端；私有debug未外拷。默认评分未改，不重复无变化的822条离线业务集；最近完整真实业务回归仍v6。

**目标仍未完成，heldout readiness=false。** 小图视觉错认与文字位置泛化失败仍未解决，简单放大无效；原图两组子集通过也不能放行完整验收。不建议再围绕同两图追加尺度或重复相同提示词请求。当前8次额度已用完，无进一步付费授权，不将失败实验升级为默认实现或发布基线。

## 同模型思考模式50次固定参照诊断（2026-11-03）

用户明确“先继续使用该默认模型ds-flash，同时支持50次付费调用”。按实际配置保留官方DeepSeek `deepseek-flash`，未擅自改成另一个模型ID、独立Judge或主Agent模型。本轮上限50次已全部用完；0次SUT、0次embedding、0次修复、SDK零重试，不启动业务API或容器，不审阅/执行heldout。

### 条件与预算

本轮显式thinking=enabled、max_output_tokens=8192，现有Judge v8及固定视觉提示词不变。所有文字参照统一使用已有实验 `derived-open-world`，Persona使用现有完整评审协议；均不是正式运行时默认切换。对照范围、提示词与模式不同，不能将所有变化单独归因于思考开关，不能与历史成绩合算。

执行前检查Windows/WSL的semantic与两个校准脚本SHA一致，校验全部输入、候选清单和图片摘要。首次dry-run被跨PowerShell/WSL变量传递导致的空Judge模型名阻断，0次请求；改由评测进程显式读取已授权的现有模型配置后dry-run通过。没有打印密钥、修改私有profile或回退为mock。

执行计划、不可覆盖分阶段台账和总报告：
[campaign-report.json](../../data/cache/reports/judge-thinking-20261103T023632Z/campaign-report.json)。同目录`plan.json`与`run_campaign.py`固定阶段配额8+8+4+6+24=50，任何Judge错误中止后续阶段；语义失败保留，不重试、不改分母。脚本为本轮一次性实验产物，不新增常驻业务入口，不重复执行。

一次性编排脚本的正常退出仅表示阶段执行结束，不表示校准通过；须读取各阶段`all_references_matched`及总报告`heldout_ready=false`，不能用它的进程退出码代替质量门禁。

| 固定参照范围 | 结果 | 请求 | 报告 |
| --- | --- | --- | --- |
| 两张图normal/small各正反声明 | 5 passed、3 failed、0 judge_error | 8 | [visual](../../data/cache/reports/judge-thinking-20261103T023632Z/visual/report.json) |
| 修饰语、逻辑概括、覆盖开发参照 | 8/8 | 8 | [text-development](../../data/cache/reports/judge-thinking-20261103T023632Z/text-development/report.json) |
| 位置共存、显式否定、排他参照 | 4/4 | 4 | [text-position](../../data/cache/reports/judge-thinking-20261103T023632Z/text-position/report.json) |
| Persona固定三轮合成回答 | 6/6 | 6 | [persona](../../data/cache/reports/judge-thinking-20261103T023632Z/persona/report.json) |
| 原24条文字参照 | 23/24；relation24/24、truth23/24 | 24 | [text-broad](../../data/cache/reports/judge-thinking-20261103T023632Z/text-broad/report.json) |

实际50次均返回usage且finish_reason=stop，无请求、截断、解析或协议校验错误。已知prompt/completion tokens合计**59157/37073**，completion包含推理token，不能再把推理token叠加收费或据此推测人民币账单；价格与实际费用以供应商为准。所有阶段未运行项为0，剩余额度0。不同来源、同源变体及重叠开发参照不合算46/50的Agent质量通过率。

### 失败分析

| 用例 | 原预期 | 实际 | 结论 |
| --- | --- | --- | --- |
| vision-5a93ca83c3b4-small-wrong-object | contradicted | visible | 小图蘑菇反例继续漏检 |
| vision-d91513554e01-normal-wrong-fingers | contradicted | visible | 原图也将衣饰接受为手/蓝色指甲；原图子集历史通过不能证明稳定可靠 |
| vision-d91513554e01-small-wrong-fingers | contradicted | visible | 小图衣饰反例继续漏检，用户局部确认不变 |
| framing-not-answered | relation=partial、truth=correct | partial、unverifiable | gold“画面以人物上半身近景为主”对回答“画面有一名人物”的概括真值被漏判；覆盖不足判断正确，两个方向不能混淆 |

原图衣饰错误使用5578 completion tokens，其中5497 reasoning tokens，仍输出完整合法错误结论；这不是输出被截断，也不能据此建议只增加token预算。此处只记录数量，不保存或展示推理正文。客户端装配无新异常证据，不声称供应商忽略图片或锁定模型内部根因。

位置参照本轮4/4，修正了此前公园/河边的互斥误判；Persona本轮同条件6/6，覆盖范围、实际回答与配置分离、行为违反、身份矛盾及注入控制。它们是有限固定参照的正向证据，不是真实Agent任务回归。开发文字8条的策略由此前derived变为derived-open-world，同时开启思考，不能将8/8全部归因于思考。24条存在一条truth失败，尚非完整文字校准通过。

### 免费验证、归档与停止点

- Windows校准脚本及紧凑gold测试68 passed、1条既有弃用警告；Windows协议与视觉通道50 passed、2 deselected、1条既有弃用警告。后者排除会加载完整r3 Persona/catalog的两项，不读取heldout语义。[Windows JUnit](../../data/cache/reports/judge-thinking-20261103T023632Z/windows-protocol.xml)。
- WSL校准与派生gold测试68 passed、1条既有弃用警告。[WSL JUnit](../../data/cache/reports/judge-thinking-20261103T023632Z/wsl-calibration.xml)。两端不相加，不替代最新代码的完整业务或部署验证。
- 各阶段报告、台账、执行脚本、JUnit归档两端；本轮未开启debug，不产生原始回答、原始判词或推理正文外拷。原r3、候选manifest、gold、split、阈值与旧报告不改写。
- 最终只读审计确认71份实验产物两端逐字节一致、五份当前评测文档同步一致；50条诊断均为首次请求且正常结束，总台账与分项额度一致。进程核对没有仍运行的本轮评测或模型任务。
- 本轮没有发现可由放松解析或修改标签合理修复的代码问题，因此未为追求通过改写核心评分器、业务Memory/鉴权或模型默认设置。最新完整业务实测仍v6；本轮不是全量业务regression复跑。

**自动Judge校准仍未通过，heldout readiness=false。** 保留改善的文字/Persona证据，但不能用其抵消3条视觉漏检和1条文字漏判；不冻结新发布条件、不批准候选、不调用heldout。当前50次授权已全部用完；下一步必须先确定有新依据的修复方案及所需预算，不能继续重复同条件请求或由同模型多次投票冒充独立正确性证据。
