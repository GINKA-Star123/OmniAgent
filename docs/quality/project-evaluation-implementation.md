# AIagent 评测当前实现说明

更新日期：2026-11-02。本文说明当前文件职责、调用关系、Judge 协议及证据边界，不提供可覆盖现有源码的历史模板。

执行入口为[总流程](project-evaluation-workflow.md)，设计原理见[四层体系](aiagent-evaluation-system.md)，运行证据见[历史记录](evaluation-history.md)。当前状态与下一步只在[现状入口](README.md)维护。

## 1. 调用关系

```text
冻结 Dataset + 可选 overrides + 独立目标类型标注
  → cli：校验、选择 split、显式外部调用许可、条件与预算记录
  → evaluate_one：调用实际 adapter，得到 Observation
  → score：业务/规则/检索/轨迹指标 + 可选独立 Judge
  → Result：状态、指标、安全诊断与观测摘要
  → summarize / compare_reports：汇总、适用数量和同条件回归
  → report.json + failures.jsonl + summary.md

独立系统入口：load → 隔离 API；telemetry → 真实 API 进程与可选 Redis
```

oracle/gold 供评分使用，不应进入被测模型提示词。RAG 的 fixed-context 对照使用来源原文窗口，不是将独立标准答案直接给模型。

## 2. 核心文件

### contracts.py：稳定数据契约

路径：`aiagent/evaluation/contracts.py`。

Case 记录 case_id、group_id、domain、layer、split、kind、inputs、oracle；group_id 用于处理来源、剧本和图片变体的相关性。Oracle 定义状态断言、排序相关性、独立 gold、事件偏序及指标上下限；语义评测必须有非空 gold。

Observation 承载实际回答、证据、检索结果、结构化状态及可见事件，不是判词。Result 分开 passed、failed、error、judge_error，保留安全诊断和观测摘要，默认不含原答复。JudgeDiagnostic 限定阶段和 finish_reason，不直接放任意服务端文本。

JSON 读取拒绝重复键和非有限数值；digest 使用规范序列化绑定内容。摘要用于一致性校验，不等于安全加密或匿名化证明。

### adapters.py：把真实组件变成观察值

路径：`aiagent/evaluation/adapters.py`。先验证输入，再调用现有业务组件，不把预期结果伪装成实际观察：

| 适配器 | 实际范围 | 不能据此宣称 |
| --- | --- | --- |
| rag_observation | BM25、fixed 原文窗口或隔离 API 检索；按输入可调用真实生成 | BM25 通过不等于向量/混合检索通过 |
| memory_observation | Memory intake、去重/敏感与 prompt 等策略 | 不能代替真实持久化和删除验收 |
| vision_policy_observation | 可信来源、阈值、身份确认等策略判断 | 文字 fixture 不是实际看图 |
| persona_observation | 真实 Persona prompt、多轮 strict LLM、可选 normalize guard | 内存里有 raw_answers 不代表报告保存它们 |
| graph_observation | 拒答路由或配置好的真实 Runtime Graph | 离线下游 mock 不等于整链路质量 |
| api_observation | 隔离 HTTP 剧本、真实 Memory 或图片上传等 | HTTP 200 不等于业务或语义成功 |

Persona 观察值在内存保留各轮 transcript 和 raw_answers，不自动导出全部 raw_answers。`fact_scope` 默认为 `last_answer`，事实只评末轮；显式设为 `trajectory` 才评全部真实助手回答。跨轮模式要求 transcript 与输入轮次、问题和末轮答案完全对应；claim 不能来自用户问题，也不能跨轮拼接。payload 记录 `fact_scope`、`fact_answers`、`last_answer`。查看每个 Result.scope，避免混合不同证据范围。

CLI 的 `provider_session()` 按运行懒创建并复用 strict LLMService，退出时释放同步客户端，不把全局客户端跨运行复用。这是减少重复 Settings/客户端构造和资源积累的防御改进，不是 fixed-RAG 原生中断根因已修复的证明。

Provider RAG 使用通用 `RAG_GENERATION_PROMPT`，与生产 `/chat` 共享 `knowledge/answer_policy.py` 的 `RAG_FACT_RULES`，限定所问字段和时间/单位/版本粒度。question/evidence 作为 JSON 用户数据输入，不传 gold。该规则用于检索证据与 fixed evidence 生成；提示词摘要进入 Observation 和生成任务的 conditions，不改变索引或检索排名。

生产 LLMRunner 对已注入 RAG、没有视觉上下文、只识别到一个资料字段的问答使用紧凑生成模式：保留用户原问题与实际片段，不加入推测性 Planner 或角色背景扩写，仍由真实模型生成；元数据 `llm_prompt_mode=rag_field`，回复不追加 Persona 模板尾句。多字段、歌曲/创作、无 RAG 和视觉任务保持普通路径。生日受限抽取仍是独立分支，不把字段生成计作抽取成功。

检索约定：适配器不再提前扩展查询，API 和离线入口均传递实际问题。`HybridRetriever.retrieve` 内部保留原始 BM25 候选，并在查询确有变化时增加一个扩展词法视图；同一 chunk 取最佳 BM25 排名，不重复计入 RRF。向量分支每次 retrieve 仅调用一次，使用原始问题，vector_top_k=0 时完全不调用。`query_normalizer.py` 不从普通“生日”触发活动/歌曲扩展，显式活动查询仍扩展。Runtime、Graph 和专项入口保留未扩展问题；Graph 分别记录组合原查询与归一化展示值。未改变向量索引或 tokenizer，当前字段重排规则见下段。

通用字段策略：`knowledge/profile_fields.py` 用查询字段意图、明确非空字段与源文件对象建立内存补充召回；`retriever.py` 从缓存 Document 生成映射，补回 profile_field 候选并保留真实 BM25/vector rank，不额外计 RRF。`reranker.py` 将源文件对象和所问字段共同加权，优先直接对象与最长完整名称，单字名只支持明确问法。歌曲/活动/创作查询不触发；不生成答案值，不读 gold，不扩展生日抽取器，不改 tokenizer 或 FAISS。运行证据见[历史记录](evaluation-history.md)，当前真实复跑入口见[总流程](project-evaluation-workflow.md#current-rag-regression)。

### http_support.py：隔离 HTTP 与状态断言

路径：`aiagent/evaluation/http_support.py`。

Step 约束方法、相对路径、预期状态码、JSON 断言、图片 SHA、轮询超时和受限字段捕获。图片必须位于数据集目录下，防止任意读文件。轮询只允许 GET，有明确截止时间，不靠固定 sleep 假定异步完成。

require_isolated 要求显式 EVAL_ISOLATED 和有效 EVAL_BASE_URL；用户命名空间需为 eval-*。这是评测误用防线，不是生产权限体系替代。执行完核查 cleanup，不能全局清库掩盖残留。

### 固定声明的文字 Judge 校准

`scripts/calibrate_evaluation_judge.py` 复用 `semantic.Judge` 的请求、预算、协议校验及本地安全诊断，只执行固定声明，不执行 SUT 或业务适配器；默认参照为 `docs/quality/judge-calibration-20261028.json`，不读取 heldout 样本。预期 truth/relation 与合法/非法引用对照不发送给模型。

- `current` 复用原 gold 通道；`compact` 为未通过校准的精简提示词；`bidirectional` 对同一声明/目标交换前提和假设，执行两次互不见结论的单向蕴含请求。`bidirectional-v2` 是边界说明开发实验，未采用为默认。`derived` 复用运行时真实的 `GOLD_DECISIONS_PROMPT`，要求显式紧凑gold配置，每例一次；不是另写更容易通过的校准专用提示词。
- 双向模式首次判断声明是否完整覆盖 gold，反向判断 gold 是否证实声明。反向 entailed 映射 correct、contradicted 映射 incorrect，partial/not_addressed 映射 unverifiable；不按关键字硬改语义标签。
- 运行前预构造全部输入；必须使用新 Judge，硬预算为所选参照数乘以每例请求数，`max_repairs=0`。请求异常停止后续请求；协议/语义失败保留，不以反复重试获得通过。
- 后补一致性检测：相同两组声明的矛盾关系应对称；单向判 contradicted、反向未判时，记录 `semantic_consistency/contradiction_direction_mismatch`，不静默改成正确或业务失败。该保护已离线验证，没有据此回写既有真实成绩。
- 公共报告只含 ID、预期/观察标签、差异、错误码、用量、提示词/来源摘要及同模型标记；原文只在显式本地 debug 保存。逐例报告与 plan/report 独占新建，异常时不覆盖旧证据。
- `--execute --allow-provider` 才能真实请求；不带 `--execute` 是无网络结构检查。`--case-id` 精确筛选，不合并子集为新全量成绩。
- `--judge-max-output-tokens` 默认4096，范围128～8192；不会自动扩充预算或为语义失败重试。2026-11-02使用8192、disabled与derived的8例开发参照为5/8，仍未通过自动校准。
- `derived-open-world` 仅是显式校准实验：沿用真实紧凑协议，加上未知关系不等于否定、同一对象可同时具有多个位置关系、明确否定/排他仍算冲突的通用规则。每例1请求，要求紧凑gold配置；不泄漏参照标签、不改运行时默认prompt。独立4例位置参照实测3/4，未泛化通过，不采用为正式验收协议。

这些是校准实验策略，不是业务默认 Judge 协议升级。曾测试的 judge-v9 扩展提示词结果变差，已撤回默认变更并保留实验源码；当前业务默认仍为 judge-v8。文字校准不能证明图像支持、行为约束或候选已人工接受。2026-11-01 实测结果见[历史记录](evaluation-history.md#同模型-judge-文字校准诊断2026-11-01)。

### 固定图片与 Persona 通道诊断

`scripts/calibrate_evaluation_channels.py` 只读未接受的 regression 候选，核验 manifest 产物摘要及图片字节；不启动 SUT。默认 `--suite visual|persona` 为 dry-run，只有 `--execute --allow-provider` 才真实请求，预算严格等于选中参照数量，每条一请求、无修复；请求错误停止后续请求，失败项与未运行项均保留。

- 图片使用独立、完整结构的 `FIXED_VISUAL_PROMPT`；与业务 `VISUAL_REVIEW_PROMPT` 共享 `VISUAL_GROUNDING_RULE`，要求对象结构、位置与肢体连接证据，而不是颜色相似即支持。每条固定 quote 恰好一个 claim，正确/反例/未知信息三类标签仅本地比较，不进入模型输入；gold/evidence 为空。原36条参照只探测了红伞组6条；后续独立4条small图正反参照为2/4，不合并实验成绩，也不将规则补充当成视觉校准成功。
- Persona 使用实际候选配置、问题、目标类型和 `fact_scope`，将固定三轮合成回答构造成 Observation。比较事实覆盖、行为与身份矛盾，不预设人工风格分数。
- `--judge-max-output-tokens` 默认 4096，范围 128～8192；thinking 使用推理预算，4096 token 可能在最终判词前耗尽。必须显式更改预算，旧截断报告保留，不自动重试、不截取残缺 JSON。
- 图片/Persona 报告显式 `baseline_eligible=false`、`human_accepted=false`、`sut_called=false`，附固定回答、参照、payload、prompt、候选清单与 runner 摘要。这与业务 CLI 调用 SUT 后生成的报告不同。

`tests/unit/test_evaluation_channel_calibration.py` 覆盖目标不泄漏、分辨率与三类反例、缺少必填字段继续报错、预算透传、损坏输入前置拒绝、请求失败停止及默认零网络。模型返回 `evidence_quotes=[]` 而非 `{}` 等错误仍由严格 schema 拒绝，不通过宽容转换掩盖协议失败。当前结果和停止点见[现状](README.md)。

新增PNG/JPEG装配契约经过真实OpenAI SDK、`httpx.MockTransport`和模拟响应，检查 `/chat/completions` 最终JSON：图片位于user消息，base64解码字节等于已核验SHA的原文件，MIME正确，模型/thinking/JSON模式不丢失，预期标签和本地文件路径不进入请求。没有真实网络或费用；模拟响应不证明远端真的使用像素。

2026-11-02免费核对[DeepSeek官方视觉指南](https://api-docs.deepseek.com/guides/vision/)：当前 `deepseek-flash` 支持该OpenAI兼容格式，省略detail的auto当前等价original。尚未发现需要更换端点、添加特殊视觉模型别名或detail参数的证据；不能用旧模型常识断言不支持图片，也不能由请求成功推定视觉可靠。

### 保存回答的受限gold协议诊断

`scripts/diagnose_saved_gold.py` 只允许4个预先固定的regression case，从私有复核packet核验原报告、输入、观测和gold摘要，拒绝错配、输入变换或路径越界。请求保留原回答及原claim_quotes，不重新生成、不上传图片、不发送先前判词。执行需同时指定 `--execute --allow-provider --acknowledge-private-replay`，预算4、修复0；默认只做来源检查。

公共报告只含安全来源摘要、逐目标关系、真值变化计数、错误及用量，`quality_pass_rate=null`，资格始终false；原文仍只在显式本地私有debug保存。2026-11-02真实结果为4份结构合法，但7条真值变化包含未证实限定，不重写旧业务成绩。随后对紧凑提示词补充全限定与双向概括规则，再以8条新开发参照验证仍只有5/8；两个提示词快照、摘要及实验分开归档。[证据](evaluation-history.md#固定回答诊断与12次校准2026-11-02)。

### 盲描述与声明诱导的受限诊断

`scripts/diagnose_judge_grounding.py` 仅用于两张已审regression小图的诊断，不接入业务CLI评分、不输出视觉质量通过率。固定4条参照及两张图片摘要，先逐图做不含任何待核验声明、gold和标签的自动描述，再逐条把声明与描述交给仅文字的核验器。两次描述加四次文字核验，硬预算6，每步一次、无修复；任何请求、截断、解析或引文校验错误都会停止后续，原错误及未运行项保留。

描述结构为objects/relations/uncertainty；文字核验只有entailed/contradicted/not_mentioned，确定关系必须给objects或relations中的连续原文，不能把uncertainty当作证据。未提及不自动判反例正确。后阶段完全不上传图片，前阶段不发送预期标签；不重新调用SUT。`--execute --allow-provider`才付费，默认dry-run；原文只在显式 `--debug-local` 保存，公共结果仅存摘要、关系、引用数量和用量，所有资格false、`quality_pass_rate=null`。

该工具检验的是**与自动描述的文字一致性，不是原图事实正确性**。2026-11-02真实诊断中，红伞反例修正，但盲描述仍主动把衣饰认作手/指甲，并传递到后阶段；构图还因描述遗漏而无法判断，与4条参照仅匹配2/4。因此未将它并入正式视觉评分。另复用现有bidirectional-v2对3条失败文字参照做6次请求，2/3；也未替换默认协议。[完整证据](evaluation-history.md#盲描述与独立双向诊断2026-11-02)。

`tests/unit/test_evaluation_grounding_diagnostic.py` 的17项免费测试覆盖6请求上限、固定ID/图片摘要、两阶段信息隔离、文字证据必须来自确定描述、异常停止、质量分歧不重试、严格JSON、显式许可和禁止覆盖旧计划；模拟通过不证明盲描述或Judge真实正确。

### 固定小图整数放大诊断

`scripts/calibrate_evaluation_image_scale.py` 只复用两张固定small图片和四条声明，将解码RGB按最近邻复制为2倍、4倍PNG；不读取原图像素补细节，不使用生成式增强。先检查全部来源/输入摘要，再写全新目录及image-scale-manifest，记录源/生成SHA、尺寸、倍数和像素恢复校验。原输入不变，送Judge的图片SHA换为实际生成文件；case ID加nn2/nn4，identity明确不是原条件，不伪装成旧报告复跑。

实际评审复用已有通道、提示词和严格校验，预算8、修复0；默认dry-run，真实执行需许可及视觉开关。`tests/unit/test_evaluation_image_scale.py` 的6项测试覆盖像素复制、输入不变、损坏摘要前置拒绝、8条输入分开计费、标签隔离和显式许可。2026-11-02真实结果两种倍数各1/4，未改善，不接入正式评分。独立字节审计确认落盘PNG每个像素块均是小图源像素的精确复制；这不证明语义保持或识别正确。[报告](evaluation-history.md#小图最近邻放大对照2026-11-02)。

### semantic.py：语义评审与来源校准

路径：`aiagent/evaluation/semantic.py`。

build_payload 组织 question、answer、history、必要 Persona、evidence、gold、rubric 与真实 allowed_fact_ids/allowed_behavior_ids。角色配置用于身份与风格，不当检索证据；图片 payload 记录 SHA，实际图片另作多模态输入。

判词拆成事实 claims、covered_gold_ids、coverage_claims、行为 behavior_checks，以及身份/风格判断。声明引用必须来自回答原文；supported 需要 evidence 中的逐字引文；事实 ID 与行为 ID 不可混填。coverage_claims 的键必须恰好等于 covered_gold_ids，每个值为非空且无重复的完整 claim.quote 列表。普通模式只能绑定 truth=correct 的声明；显式视觉双通道另用 coverage_assessments 校验答案到目标的完整蕴含，详见第 6 节。绑定提供可追踪的一致性约束，不自动证明语义蕴含，也不能修正错误 gold。

普通评审每例最多一次协议修复，且仅限首次完整、可定位的判断不变；不为合法低分重试。首次不可解析、截断或声明/目标身份不可靠时直接保留错误，不再另答一次。初始/修复请求均计入预算，SDK 重试为0。可选视觉双通道各最多修复一次，共享同一个全局请求预算，不因文字通道失败而重跑已完成的看图通道。剩余额度不足完成当前用例的初始通道时，在生成observer前拒绝；该检查不预留可选修复，也不是整条业务链路的总费用上限。请求过程记录安全 channel/stage/code/finish_reason。

manual 判词绑定当前 payload_sha256，旧摘要不能静默复用。输出 token、模型版本、提示词和标注摘要进入评审条件。错误码、安全规则与预算见[本文 Judge 协议](#judge-protocol)。

来源校准：`source_attribution.py` 只从事实 gold 的明确来源声明提取文档身份，精确标题与同名 `.md` 文件等价；纯来源标签且原 truth 为 unverifiable 才可校准。任意作品名、行为目标、路径、未知来源及夹带额外事实的声明不适用。`score_verdict` 是无外部调用的统一重评分入口，先严格校验判词，保留原 truth 指标与 claim 分母，只复制被校准的 claim，不原地改变判词，不修改 support/证据/引用。identity 记录 `judge-v8`、提示词与规则摘要；新旧协议不混作同条件基线。

引用标记与来源声明分开：`[证据ID]` 本身不是额外事实，应关联到事实 claim 的 citation_ids；“来源：《文档》”仍是来源身份声明。仅包含本次真实 evidence ID 的纯标记 claim 会被判为 `citation_marker_not_fact` 协议错误。当前保护策略不自动删除这类 claim 后重试通过，避免改变评分分母；未知引用、错误事实和额外年份仍照常检查。原 v8 曾允许一次修复，旧报告保留，不回写为当前已通过保护。

`scripts/regrade_judge_sources.py` 仅回放已完成的文本 Judge v2 归档。它核验数据/标注摘要、原 payload 与 case 输入、原判词指标，拒绝错配、脱敏破坏、覆盖、图片、输入 overrides 和未完成判词；不重建完整 Observation、不调用模型或 API。此版本锁定入口显式使用旧覆盖口径，identity 为 `legacy-v2-source-only`、`coverage_bindings_validated=false`，不猜补旧绑定或冒充 v6。输出独立 `regrade.json`，仅列语义门槛，不生成普通评测的 ok/conditions/results，不能作为新实测或正常基线。归档回放的实际结果见[历史记录](evaluation-history.md)，不与真实 API 结果混用。

### diagnostics.py：显式本地审阅材料

路径：`aiagent/evaluation/diagnostics.py`。

只有 --debug-local 且 APP_ENV=local、CLOUD_MODE=false 时启用。独立目录使用私有 Linux 模式位，文件名用 case key 摘要，并拒绝覆盖。保存脱敏 payload 和最终判词文本，不保存请求头、完整 SDK 响应、推理正文或图片 base64。

构造评审 payload 后、首次 Judge 请求前另存 `HASH_OF_CASE_KEY-input.json`。因此网络、截断或判词校验失败不再导致已生成回答无法复核；未启用 debug 仍不留原文。留档失败返回 `debug_artifact_write_failed`，在此阶段不再发起付费 Judge 请求。原始 payload 摘要与实际脱敏/限长后的摘要分开保存，`payload_transformed` 表示两者是否不同；文件明确 `automatic_replay_allowed=false`、`human_accepted=false`、`baseline_eligible=false`，不把脱敏文件当作已核准的手工判词。

过滤已知敏感环境变量值、常见裸密钥和现有日志安全规则；这不是完备 DLP，未知个人信息仍可能保留。不要提交或公开目录。Windows 模式位不代替 NTFS ACL。默认不创建这些文件。

### metrics.py：不依赖模型的基础指标

路径：`aiagent/evaluation/metrics.py`。

实现排序指标、编辑距离、OCR CER/WER、macro-F1、Wilson 区间、百分位与选择性曲线。排序保序去重并截取 K；Precision@K 分母固定为 K；无相关目标时部分指标为 null。工具支持某个指标，不等于当前数据提供了相应真值。

### scoring.py：合成结果与错误分类

路径：`aiagent/evaluation/scoring.py`。

score 检查业务断言、答案规则、检索、类型/OCR/身份、事件偏序及可选语义指标，再应用 Oracle.limits。缺少适用指标不能自动通过。Judge 异常为 judge_error，观察执行异常为 error，合法低分为 failed。

evaluate_one 负责观测与总耗时。Provider语义评审在observer前按minimum_judge_requests检查剩余初始请求额度：普通文本1次、显式视觉双通道的图像用例2次；不足即返回budget/request_budget_exhausted，不生成被测回答。elapsed_ms 含评分/Judge，不是服务响应时间，不能直接当回答 P95。

### reporting.py：汇总与同条件回归

路径：`aiagent/evaluation/reporting.py`。

协议为 agent-eval-four-layers-v2。按全局、层级与组件分组，保留状态、scope、适用数量和分母；异常不从总数删除。比较器要求协议、conditions、overrides_sha256、case identity 和证据范围兼容，基线必须是人工接受的通过报告。不同事实范围的 overrides 不可冒充同条件基线。

重复与同源变体先按 group_id 聚合，再做配对 bootstrap，不把每次生成当独立样本。跨模型、跨 gold、跨 Judge 或 v1/v2 不作为同条件回归。

### cli.py：总编排与授权开关

路径：`aiagent/evaluation/cli.py`。

负责参数、split/repeat、输入 overrides、--allow-provider/--allow-api、Judge、预算、条件/代码摘要、执行与报告。--release 只做现有三层四组件覆盖检查，不代替性能和完整发布审批。

--case-id 可重复指定精确 ID，只选择当前 split 内的用例，保留原数据摘要与执行顺序，默认 Judge 预算仅按选中用例计算；未知或跨 split 的 ID 在请求前拒绝。筛选条件进入 conditions，不能把诊断子集当作完整回归，也不允许和 --release 同用。

自动读取同目录 judge-gold-kinds.json，也可显式指定。普通 Judge 默认预算为所选语义用例数 × repeat × (1+max_repairs)。显式开启 `--judge-verify-visual-gold` 时，视觉用例计算两个评审通道的预算，即每例最多 4 次 Judge 请求（max_repairs=1），不是 2 次；文本用例仍按一个通道计数。CLI 退出码0为满足断言、1为质量/业务失败、2为执行/配置/Judge异常。

执行首例前，CLI 独占创建 `run.json`，记录条件、源码摘要、输入覆盖摘要、选中 case/group 与计划执行数，不含 gold、原答复、判词或密钥。它是不可变的执行前计划，`complete=false` 不会在成功后改写；是否完成看 `report.json`。源码摘要现包含 `integrations`，摘要覆盖范围变更前后的值不能当成同一口径。

每条完成后，CLI 将安全 Result 追加到新建的 `results.jsonl` 并 flush。进程中断时可以检查已完成条目，但没有 `report.json` 就不是完整通过，不自动从中断位置恢复或重跑付费请求。journal 不含原回答、原判词或密钥。正常结束仍生成原有汇总报告。

### Chat / Memory smoke 的安全执行诊断

现有实现对编辑元数据、单字段问答和 HTTP 诊断作如下分工；原故障与运行记录见[历史记录](evaluation-history.md)：

| 文件 | 本次职责 |
| --- | --- |
| `knowledge/query_normalizer.py`、`profile_fields.py` | 保留原始查询；区分明确字段与歌曲/活动，识别源文件对象及字段，不读取 gold |
| `knowledge/retriever.py` | 从缓存语料补回同对象明确字段候选，标记 profile_field，无额外 embedding，不伪造原 rank |
| `knowledge/reranker.py` | 同对象与所问字段共同加权，保护长名称及复合名边界，非资料任务不触发 |
| `graphs/rag_graph.py` | 明确日期问答保持用户查询，不被 Planner 的扩展意图覆盖 |
| `graphs/llm_graph.py` | 生产 `/chat` 最小充分事实、真实来源、证据边界和 Planner 优先级约束 |
| `memory/mem0_memory.py` | 编辑后清理旧抽取/查询说明，安全新正文同步到 hint；历史审计不删除 |
| `evaluation/http_support.py` | 区分轮询未满足、请求超时、断言失败；稳定码与从 1 开始的步骤序号 |
| `evaluation/contracts.py`、`scoring.py`、`cli.py` | `execution_diagnostic` 安全字段进入报告和失败清单；旧报告读取时可使用空默认值 |
| `tests/unit/test_chat_memory_smoke_regression.py` | 14 项单元/回归/对照：恶意干扰向量、缺失词法候选、名称边界、编辑/置顶/快照、所属用户及诊断脱敏/cleanup |

诊断仅含 `step_index`、`method`、`last_status`、`failed_check_indices`，不序列化响应、检查期望值、URL 或异常原文。`EvaluationPollTimeout` 仍属于 `TimeoutError`，`EvaluationAssertionError` 仍属于 `AssertionError`，保留已有调用和测试约定。只记录有界的稳定错误字段，不放宽通过门槛。

### 单字段抽取式回答与路径归因

明确生日日期任务使用受限抽取路径，不等于模型自由生成质量提升；实际结果与 Judge 来源误扣修复见[历史记录](evaluation-history.md)。

- `knowledge/fact_answer.py`：受限问法与字段解析、标准库日期校验、别名精确匹配、显式冲突检查；返回带实际 chunk-id 的不可变 `GroundedFactAnswer`，从不读取 gold。未知格式、额外任务、多来源等返回 None。
- `knowledge/rag_context.py`：统一正文格式化，Graph 与 Pipeline 共享；RAGRunner 仅检索一次，引用、prompt 和抽取来自同一快照。
- `graphs/graph_model.py`、`main_graph.py`：增加并传递可空事实候选，旧调用默认 None；不增加外部 ChatRequest 参数。
- `graphs/llm_graph.py`：符合条件的字段问答跳过回答模型与 Persona 扩写，继续执行验证、消息持久化；无证据或有视觉上下文仍调用模型。每轮重置模式与来源 metadata，防止跨轮污染。
- `evaluation/scoring.py`：从实际 API/Graph metadata 读出 `extractive_answer_used` 诊断指标；不改变 Judge、原质量指标、门槛或错误分母，未标注的旧结果不猜测路径。
- `tests/unit/test_rag_extractive_answer.py`：37 项单元/回归/对照，含完整 Graph/checkpoint 与可选本地全语料对照；当前 Windows/WSL 已实际运行全语料项。系统抽取正确不能作为模型独立生成质量通过的证据。

## 3. 系统层单独运行

`aiagent/evaluation/load.py`：开环单文本 /chat 探针，限制 worker/queue/user，记录发送、完成、规则/SLO goodput、成功 HTTP 百分位及失败/清理。它不消费混合 Dataset，不提供真实 semantic_goodput 或 TTFT。

`aiagent/evaluation/telemetry.py`：采样指定真实服务进程 CPU/RSS，可选 Redis。PID、窗口、容器/多worker边界必须明确；不能把客户端资源当 API 资源，不自动覆盖 Qdrant、GPU 或外部模型。

## 4. 数据与环境工具保留理由

| 文件 | 用途与边界 |
| --- | --- |
| scripts/build_project_agent_eval_dataset.py | 从 MD、图片、Persona 构建资料派生集和标注 sidecar；不覆盖输出，不执行模型 |
| scripts/build_agent_eval_dataset.py | 极小 fixture 与 API 剧本；集成测试仍引用 api_dataset，不是可删除旧生成器 |
| scripts/audit_project_eval_data.py | 核对结构、来源 SHA、路径、分组及输入；不是质量测试 |
| scripts/setup_project_eval_wsl.sh | 仅为新副本准备环境，不每次恢复都运行 |
| scripts/project_eval_session.sh | 恢复模板，切回 mock 并清除 Judge Key；实际使用副本根 .eval-session.sh |
| scripts/check_project_eval_wsl_environment.sh | 新环境预检；报告拒绝覆盖，不证明真实业务质量 |
| config/env_secrets.py | 命名凭据先读进程后读工作目录 dotenv；显式空进程变量禁止回退，不全局导出 |
| scripts/sync_eval_model_env.py | 从源配置同步模型白名单到 WSL 私有 env/profile，保持隔离端口、集合、路径，不复制 Judge/管理员/数据库凭据 |
| scripts/rebuild_rag_cache.py | 默认只输出计划；--preflight 以模拟响应检查 SDK/FAISS；--execute 自动预检后分阶段暂存、校验、备份并发布；--execute --probe-provider 仅一次合成 embedding 调用（关闭 SDK 重试），无真实建库；安全错误码、结构摘要及调用位置不记录密钥/原文 |
| scripts/transfer_rag_cache.py | seal/verify/install 离线封装、复核与迁移自建 CPU FAISS；比对文件和语料 SHA256、依赖、配置、向量与文档映射；显式信任 pickle，安装需 --execute，保留回滚备份及稳定 ID |
| docs/quality/project-eval-visual-annotations.json | 基础12张标注，仍被v2的base_annotations引用，不能删 |
| docs/quality/project-eval-visual-annotations-v2.json | 增补12张及相关图片组；不是替换前者的完整独立集 |
| data/evaluation/project-20261026-r3/judge-gold-kinds.json | 逐例事实/行为类型，不按boundary等键名一刀切 |

旧数据、失败报告和修复记录不自动判定为无效；它们是来源与诊断证据。历史只读，不覆盖源码或直接当v2接受基线。

## 5. 测试职责

| 文件 | 主要验证 |
| --- | --- |
| tests/unit/test_evaluation_contracts.py | 契约、输入错误、manual判词与摘要绑定 |
| tests/unit/test_evaluation_metrics.py | 排序、OCR、统计、百分位边界 |
| tests/unit/test_evaluation_regression.py | CLI离线流程与报告回归 |
| tests/unit/test_evaluation_contrast.py | 故意坏观察/错答案/超时能否被识别 |
| tests/unit/test_evaluation_judge_protocol.py | fake响应模拟协议/ID/引用/finish_reason/预算/修复/脱敏，无外部请求 |
| tests/unit/test_evaluation_source_attribution.py | 36 项：严格文档来源等价、错误/未知来源与日期对照、完整声明边界、raw 指标和 support 保留、协议隔离、免费回放摘要绑定与拒绝覆盖 |
| tests/unit/test_rag_profile_field_recall.py | 39 项：通用字段召回/排名、错误或空字段、复合/单字名称边界、RRF 归因、完整语料 470 条 regression 在纯词法/模拟干扰向量两种条件下的对照 |
| tests/api/test_evaluation_http_contract.py | TestClient/MockTransport契约，不是部署实测 |
| tests/integration/test_evaluation_live.py | 显式EVAL_RUN_LIVE=1调用隔离API，有费用，不代替完整语义评测 |
| tests/unit/test_env_secrets.py | dotenv 命名引用、环境优先级、空值阻断、字面量和非法名称 |
| tests/unit/test_memory_provider_config.py | Mem0 LLM/embedding 独立地址与凭据、OpenRouter 冲突保护，无远程请求 |
| tests/unit/test_sync_eval_model_env.py | 同步白名单、评测状态隔离、命名引用验证与私有配置字面量保存 |
| tests/unit/test_rebuild_rag_cache.py | dry run、SIGSEGV 返回映射、预检失败阻断付费构建、暂存发布/回滚、manifest 边界、离线 FAISS 完整重建，以及探针单调用预算、禁止写缓存与异常脱敏 |
| tests/unit/test_rag_embedding_response.py | MockTransport 对照响应排序、条数、索引、维度与数值类型校验，阻止非法远程向量进入原生索引；稳定错误码及结构摘要，不泄露输入/响应原文 |
| tests/unit/test_transfer_rag_cache.py | 无网络封装/导入、路径规范与 ID 保留、摘要/语料/版本/维数错误拒绝、失败保留旧目录、信任开关与 dry run 保护 |
| tests/unit/test_evaluation_rag_generation.py | 生成消息装配、BM25/fixed/无证据路径、未知/错误声明仍计入分母、提示词条件与旧基线不兼容；不请求外部模型 |
| tests/unit/test_evaluation_visual_channels.py | 文字/图片/gold 三通道、图片问题传递、行为 ID 修复边界、生产字段 prompt 与普通路径对照、Vision 请求指令与数据隔离 |
| tests/unit/test_evaluation_repair_guard.py | 首次判断冻结、拒绝改分/增删声明/改变覆盖关系、不可解析或截断不重试、双通道绑定修复对照、旧条件不混比、图片字节与顺序 |
| tests/unit/test_evaluation_review_input.py | 请求前留档、请求/解析/截断失败仍保留输入、留档失败阻断请求、脱敏与限长摘要、私有模式及拒绝覆盖；全部模拟，无网络 |
| tests/unit/test_evaluation_visual_quote_policy.py | 连续原文优先的视觉提示词、补写主语/否定词仍拒绝、复合原文的 visible/unclear/contradicted 对照，不放宽门槛 |
| tests/unit/test_evaluation_derived_gold.py | 可选紧凑gold协议与确定性绑定派生、真值/关系保留、非法原文/目标/绑定/重复JSON仍拒绝、CLI装配和release阻断，全部免费 |
| tests/unit/test_evaluation_budget_admission.py | 初始评审额度计数、双通道额度不足时不生成/不请求、刚好够用与合法低分对照、文本可选修复不强制预留，以及gold占位不覆盖真实视觉/风格判断；23项免费测试 |
| tests/unit/test_audio_player_lazy_init.py | 无声卡时可构造 Runtime 的播放器；真正播放时仍初始化设备并如实报告失败 |
| tests/unit/test_rag_query_recall.py | 原始/扩展 BM25 候选并集、单票 RRF、单次原始向量请求、关闭向量时零调用、符号/ASCII 名称边界、混合噪声下日期资料保留，以及 Runtime/Graph/API 适配器不提前改写查询 |

业务测试按改动范围补跑；上述职责表不是全量覆盖或真实服务验收证明。可执行命令只在[总流程](project-evaluation-workflow.md)维护。

<a id="judge-protocol"></a>

## 6. 当前 Judge 协议

2026-10-28 的[标注与口径审定](evaluation-adjudication-20261028.md)仅生成候选，未直接改变运行时代码。2026-11-01 后续已实现 `repair_policy=freeze-first-decisions-v1`，并经合成响应与两组历史真实判词零网络回放验证；这不是重新运行真实模型，也不证明 Judge 的语义判断可靠。新原子目标/轨迹范围仍只在独立候选数据中，不回写冻结集或候选构建时的政策快照。

当前 Judge identity 为 **judge-v8**，另有显式 **repair_policy=freeze-first-decisions-v1**；报告协议仍为 **agent-eval-four-layers-v2**，两者不是同一个版本号。普通模式保留 v6 的正确声明绑定和显式 Persona 事实范围；v7 引入事实拆分、Markdown 逐字引用与可选视觉双通道；v8 修正双通道中 gold 真值与答案覆盖的蕴含方向。修复保护阶段未改提示词；后续候选诊断仅修改独立视觉通道的引用优先级，新增 **visual_quote_rule=contiguous-before-atomic-v1**，普通合并通道标记为 combined-original。提示词摘要和政策均进入 conditions，新旧报告不能混作同条件基线。未改变模型、评分公式、gold 或门槛，最近完整业务回归仍为 v6；当前候选诊断不是新全链路回归。

`--judge-verify-visual-gold` 仅适用于 Provider 模式、没有文字 evidence 或行为目标的图像事实评测。看图通道不接收 gold，全部 truth 为 unverifiable、覆盖为空，输出连续原文 claim 与图片支持度；随后文字通道不接收图片和前一个通道的判词，只接收原文 claim、答案及独立 gold，评定 truth 和完整目标覆盖。合成时只替换事实真值/覆盖，图片支持度保持看图结果不变，文字通道不能删掉、增加或改写 claim。

视觉通道遵循“连续原文优先于事实原子化”：可独立截取时用短声明；共享主语或否定词时允许保留完整复合原文，不能补写“人物”、复制否定词或改标点来伪造独立句。复合声明的全部事实都有像素支持才可判 visible，任一事实被明确反驳为 contradicted，其余证据不足为 unclear。严格的 substring 校验、不得漏评额外细节和零无支持声明门槛保持不变。该提示词不能保证每次提取正确，也不能解决首次视觉误判；声明粒度可能改变，不直接比较新旧 claim 比率作为质量提升。

该开关默认关闭，是否开启、两个提示词摘要均进入 identity；普通模式不能冒充双通道结果。双通道仍可使用同一模型，并不等于异模型独立评审，也不保证语义判断绝对正确。v7 原子拆分会改变 claim 粒度和指标分母，不直接拿 v6 的图片错误率比较成生成质量提升。错标仍需人工审定后另建数据版本，不能靠评审自动修订 gold。

v8 文字 gold 通道额外返回 coverage_assessments，必须逐一包含全部事实目标，记录完整 gold_text、relation（entailed/partial/contradicted/not_addressed）及回答原文 claim_quotes。只有完整蕴含 entailed 能进入 covered_gold_ids，引用必须与 coverage_claims 完全一致，不能用 incorrect 声明支持覆盖，not_addressed 不允许绑定。原文、目标全文、ID、重复与绑定均作严格校验。

### 显式可选的绑定派生诊断

`--judge-derive-gold-bindings` 默认关闭，要求 Provider、`--judge-verify-visual-gold`、`--judge-max-repairs 0`，并在执行前拒绝 `--release`。identity记录 `gold_binding_rule=derive-explicit-relations-v1` 和新gold提示词摘要；旧模式记录model-asserted-v1。它改变请求协议，不把旧冗余字段异常宽容转换成通过。

新协议只接收两个顶层字段：`claims`中的quote/truth，以及`coverage_assessments`。严格模型`GoldDecisions`拒绝其他字段，`to_verdict()`仅从已有entailed关系派生covered_gold_ids/coverage_claims；文字通道固定的support/视觉/行为占位由代码提供，不让模型反复输出。其余语义约束仍经原validate与通道校验，错误目标、非连续引文、缺失/重复绑定、incorrect支持entailed等仍为judge_error。不将partial、contradicted或not_addressed升级为entailed，也不把unverifiable改成correct。

实际诊断发现4份判词已明确entailed及引文，却把冗余覆盖列表留空；后补新模式消除这类双写机会，不保证模型语义本身正确。历史显式判断的投影回放4/4只验证结构保真，没有请求模型或改写旧分数。2026-11-02已有4份保存回答真实诊断，结构全部合法但不生成质量通过率；补强提示词后的文字参照5/8，语义校准仍失败。原默认通道继续严格拒绝冗余字段矛盾。

后续对全部18例作零网络兼容审计：11份原有效判词的claims/coverage_assessments保真，按实际双通道合成后全部指标与旧报告一致；4份冗余绑定异常仅结构投影，2份视觉引用错误和1份截断保留。gold结构中的固定风格/行为/视觉占位不参与替换视觉通道真实判定，不能比较gold单通道占位分数冒充最终评分一致性。报告见[历史记录](evaluation-history.md#免费兼容审计与预算前置检查2026-11-01)，这不是新协议的真实模型成绩或语义校准。

两个方向不能混淆：truth=correct 要求 gold 能证实 claim；coverage 要求答案能回答 gold 的全部条件。例如 gold 为“桌上有水果”，答案“桌上有一盘苹果”可能覆盖 gold，但具体种类/容器未被 gold 证实，truth 仍可为 unverifiable。反向的“有水果”不能覆盖“窗边桌上有一盘苹果”。v8 不自动把 unverifiable 改成 correct，不改变 fact_accuracy 或视觉支持度分母；普通模式仍拒绝不可核验声明绑定，payload 不能自行开启此规则。coverage_rule 与提示词摘要进入 identity，旧手工判词不能直接冒充 v8 双通道结果。

新增校验错误码包括 coverage_assessments_mismatch、coverage_gold_text_mismatch、coverage_unaddressed_has_claims、coverage_claim_incorrect、coverage_assessment_bindings_mismatch、coverage_entailed_ids_mismatch、coverage_assessments_not_enabled 和 coverage_modes_conflict。文本 Judge 对蕴含关系的判断仍可能出错，这些结构校验不是逻辑证明器。

双通道新增错误码：`visual_channel_mixed`、`gold_claims_mismatch`、`gold_channel_mixed`；未实现的混合 evidence/行为场景在调用前拒绝为 `visual_gold_review_requires_fact_only`，非 Provider 模式拒绝为 `visual_gold_review_requires_provider`。诊断 channel 为 combined/visual/gold；旧诊断缺少此字段时默认 combined。本地调试按原 case key 的 `:visual`、`:gold` 后缀分别绑定、脱敏保存，不回写旧材料。

v6 引入的稳定错误码仍为 `coverage_bindings_mismatch`、`coverage_claims_empty`、`coverage_claim_duplicate`、`coverage_claim_missing`、`coverage_claim_not_correct`。每个通道最多一次有预算且不改变首次判断的绑定修复；当前策略也不自动接受质量降级，判断改变统一转交复核。Persona 输入配置错误为 `fact_scope_invalid` 或 `trajectory_history_invalid`，不是可自动修复的判词格式错误。

v5 明确 `support` 仅比较文字 evidence，`visual_support` 仅比较真实图片，`truth` 仅比较独立 gold。没有文字 evidence 时，图片可见也必须填 `support=insufficient`、`evidence_quotes={}`，不得编造图片哈希引文；faithfulness 仍为 null。图片问题从 HTTP body 的 text/prompt 读取。行为编号不能混入事实覆盖编号；协议修复重述真实 ID 集合及空 evidence 约束，最多一次，不因低分触发。

### 6.1 事实与行为

Judge接收question、最后一轮answer、history、evidence、独立gold、rubric及Persona身份/风格/规则/行为配置。音频路径与渲染配置不传给文本Judge，角色配置也不能冒充检索证据。gold只进入Judge，不进入被测模型生成提示词。

事实目标使用allowed_fact_ids；covered_gold_ids只能填写实际键（例如fact、spirit），不能照抄不存在的g1。若声称覆盖事实，还必须给出实际回答中的事实声明。声明和证据引用仍要求逐字连续原文，不能通过同义改写伪造引用。

历史 v5 仅校验覆盖 ID 与 claims 存在性，v6 增加正确声明逐项绑定，但仍发现把红伞误绑定到蘑菇目标的合法结构判词。v7 分离像素与 gold 后，该已知误判对照转为覆盖失败；v8 进一步区分真值与覆盖方向，不把粗 gold 未提供的细节自动标正确。各版仍依赖模型的语义判断，“协议校验成功”不等于“覆盖语义可靠”。风险与对应运行见[执行记录](evaluation-history.md)，错标修订和异模型评审需另建实验。

行为目标使用allowed_behavior_ids；behavior_checks必须逐项给出satisfied、violated或not_observable。行为是否满足看实际表现，不要求复述规则。例如用户未上传图片，回答“你想用冷色还是暖色？”可满足不捏造图片细节的约束；不能仅因没说“我没看到图片”判为漏答。violated与not_observable都不算满足。

| 指标 | 当前口径 |
| --- | --- |
| factual_gold_coverage | 已覆盖事实目标 / 全部事实目标；无事实目标为null |
| behavior_pass_rate | satisfied行为目标 / 全部行为目标；无行为目标为null |
| gold_coverage | (已覆盖事实 + satisfied行为) / 全部目标，兼容现有门槛的总目标满足率 |
| fact_accuracy、faithfulness | 仍按事实声明与独立gold/实际证据计算，不用行为成功伪造事实分数 |
| fact_unverifiable_rate | 2026-10-27 增补：truth=unverifiable 的声明 / 全部声明；诊断用途，不改变原门槛 |

标注是明确的逐例元数据，不按键名猜测：persona-yzl-03的boundary是“怕死鱼眼”的角色事实，仍是事实；persona-yzl-29的boundary是不捏造未上传图片，是行为。未标注默认事实。CLI自动读取数据集旁的judge-gold-kinds.json，也可用--judge-gold-kinds显式指定。提示词、标注摘要、协议及预算进入conditions。

评审口径升级，旧协议报告与手工判词 payload 摘要不能冒充同条件当前基线；不要靠修改标注来追求通过率。

### 6.2 诊断与预算

结果中的error_stage标明configuration/budget/request/response/parse/validation/internal，error_code是固定机器可读码。judge_diagnostics逐次记录attempt、stage、code、finish_reason、retryable。成功评审的末次记录为complete/ok；普通质量失败的error_code为空。

每次诊断另含 output_chars、completion_tokens、reasoning_tokens；后两项未提供时为 null，不推测为 0。不存储或输出 reasoning_content，普通报告仍不保存回答、判词或密钥。旧诊断可使用这些字段的空默认值读取。

`--judge-thinking disabled|enabled` 是显式的 DeepSeek 扩展，仅允许官方 HTTPS api.deepseek.com，发送 `extra_body.thinking.type` 对应值；default 不发送扩展字段，不按模型名字猜测兼容接口。参数与 prompt 摘要进入评审条件，修改后不与旧报告作同条件基线。官方请求格式见 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode.md)，支持请求不等于 Judge 可靠性获准。只记录 reasoning_tokens 等数字，不保存或回传 reasoning_content。不自动增加 token、预算或对鉴权/请求错误降级重试。

2026-11-03新增50次同模型固定参照实验使用enabled、8192预算、零修复，视觉5/8、开发文字8/8、位置4/4、Persona6/6、较广文字23/24。文字使用现有显式`derived-open-world`，未切换业务默认或解除derived的release限制；所有合法响应中仍有语义误判。不能将enabled、更多推理token、结构合法或局部参照匹配当作完整自动校准证明。[条件与结果](evaluation-history.md#同模型思考模式50次固定参照诊断2026-11-03)。

| 错误码示例 | 含义 | 修复重试 |
| --- | --- | --- |
| verdict_json_invalid / verdict_schema_invalid | 非严格JSON或结构非法，首次判断无法完整定位 | 不重试 |
| gold_identifier_invalid | 目标ID不存在或类型不匹配，首次目标身份不可靠 | 不重试 |
| claim_quote_not_in_answer / citation_marker_not_fact | 声明不属于回答原文或将纯引用标记当事实 | 不重试，不改写或删声明 |
| evidence_quote_invalid / supported_evidence_missing | 证据无效或缺少支持证据 | 仅首次判断完整可定位时，最多一次 |
| behavior_identifiers_mismatch | 行为目标遗漏或多出 | 不重试 |
| response_truncated | finish_reason为length | 不重试，不自动加token |
| repair_semantics_changed | 修复改动首次事实/覆盖/视觉/行为/角色/风格判断 | 不接受、不评分，不继续重试 |
| request_authentication_failed / request_timeout / request_rate_limited | 鉴权、超时或限流 | 不重试 |
| request_budget_exhausted | 本次CLI请求额度用尽 | 不重试，也不生成后续答案 |
| debug_artifact_write_failed | 本地调试证据保存失败 | 不重试 |
| metric_limit:* | 判词合法，质量门槛未达到 | 不重试，不刷分 |

每通道默认最多一次初始Judge请求和一次受保护的协议修复；显式视觉双通道每例有两个通道，共享同一预算。`--judge-max-repairs 0` 可关闭修复，SDK重试固定为0。修复只追加固定错误码、原输入和保留首次判断的规则，不回传旧判词；保护摘要仅在进程内比较，不作为新事实输入模型。审定校准入口仍显式关闭修复。

首次必须可解析为完整 Verdict，声明是回答的连续原文且不重复、行为ID完整、目标身份可靠，才能建立修复比较摘要。普通通道冻结 claims 原文及 truth/support/visual_support、covered_gold_ids、行为、身份矛盾和风格分；文字gold通道冻结每个目标的明确 relation，covered_gold_ids/coverage_claims 只能作为这些关系的结构派生项修正。允许声明次序变化，不允许增删声明、改引文或将 partial 改为 entailed；绑定改正后仍可合法低分。原 judgment 缺失或不可定位时不另答一次，错误保持原代码且诊断 retryable=false。该保护只能阻止修复漂移，不能识别第一次就发生的语义误判。

--judge-request-budget限制本CLI的Judge请求总数，初始与修复都计入。默认额度为所选评审通道数 × repeat × (1 + max_repairs)：普通模式每例一个通道，显式视觉双通道的视觉例每例两个，文本例仍为一个。--judge-max-output-tokens默认4096，允许128至8192。logical_requests是实际发起请求数，repair_requests是其中的修复请求数；token统计包含失败判词。未知finish_reason归为unknown，不回显任意原文。

默认预算与运行前检查共用minimum_judge_requests，identity记录budget_policy=complete-initial-review-v1。图像判断覆盖vision_api、inputs.image及轨迹steps中的image；非语义用例无需Judge额度。检查只要求完成全部初始通道，不为可选协议修复预留额度，后续实际请求仍逐次检查总上限；并非保证用例一定成功或全链路费用封顶。新旧预算政策条件不混作同条件基线。

预算只控制Judge，不是全链路费用配额。总流程的 9 条 Provider smoke 含多轮 Persona，正常约12次生成调用，加9至18次Judge调用；被测LLM的网络重试可能额外收费，推理token计费须以实际服务为准。

### 6.3 调试安全

默认不创建调试文件。只有显式--debug-local且APP_ENV=local、CLOUD_MODE=false才写入OUTPUT/RUN_ID/.judge-debug/HASH_OF_CASE_KEY-ATTEMPT.json，并在请求前写入 HASH_OF_CASE_KEY-input.json。该目录0700，文件0600（Linux）；Windows模式位不等于已设置NTFS私有ACL。

文件只含payload摘要、脱敏评审输入及原始判词文本，不含完整SDK响应或请求头。已知敏感环境变量值、常见裸密钥、Bearer和key=value秘密会过滤；图片仅存SHA，不存base64。公共report和failures.jsonl不包含这些文本。

这是辅助脱敏，不是完备DLP；原文、个人信息或未知格式秘密仍可能敏感。不要提交、公开或整目录上传.judge-debug，自行控制保留时间。脱敏payload不保证逐字可重放，不能用它绕过手工判词的摘要校验。
