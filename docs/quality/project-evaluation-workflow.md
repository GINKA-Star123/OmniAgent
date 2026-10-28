# AIagent 评测总流程：从离线到真实验收

更新日期：2026-10-28。本文是 WSL 评测的唯一操作入口，覆盖 RAG、Memory、Vision、Persona；不推进 V1.2 第五批，不包含前端。Windows 命令变体见 [Windows 手册](project-evaluation-windows-runbook.md)。

命令逐项执行并审阅报告，不整篇当一键脚本。首次评测依次阅读第 1～11 步；已有环境只做尚未完成的步骤。原理见[实现说明](project-evaluation-implementation.md)，历次结果与原始报告位置见[历史记录](evaluation-history.md)。

## 0. 先确认当前位置

执行前先读[现状入口](README.md)和[标注与口径审定](evaluation-adjudication-20261028.md)。当前停止点是用户审阅候选及评审口径；批准校准前，不因本文列有命令就重跑付费回归。最近完整回归与定向验证分开记录，见[历史记录](evaluation-history.md#judge-v6-regression-复跑)。heldout留给用户最终验收。

总路线：环境/数据 → 离线验证 → 模型与 Judge → Provider smoke → 隔离 API → 业务 smoke → 回归/对照 → 冻结 → heldout → 负载 → 归档。系统层由独立 load/telemetry 工具完成，Dataset 的 layer 只有 component、trajectory、task。

## 1. 恢复会话，确认隔离边界

在 Windows PowerShell 中进入现有副本：

```powershell
wsl.exe -d sp3-build -u root --cd /root/aiagent-eval/20261026T091836Z-i4Fyhq
```

**新开的 WSL Bash 会话**执行：

```bash
source /root/aiagent-eval/20261026T091836Z-i4Fyhq/.eval-session.sh
python -V
pwd
printf '数据集：%s\n报告根：%s\n' "$DS" "$REPORTS"
```

如果当前终端已经输入过真实 Provider/Judge Key，**不要再次 source**。只激活环境并恢复非秘密路径即可：

```bash
cd /root/aiagent-eval/20261026T091836Z-i4Fyhq
source .venv/bin/activate
export WORKSPACE="$PWD" SOURCE=/mnt/f/aiagent
export STAMP="$(basename "$WORKSPACE")"
export DS="$WORKSPACE/data/evaluation/project-20261026-r3"
export REPORTS="$WORKSPACE/data/cache/reports/project-eval-$STAMP"
export APP_ENV=local CLOUD_MODE=false
```

上述两条路径二选一。恢复脚本会切回 mock 并清除 Judge Key；退出 shell 不删除副本，但环境变量、函数、PID 的会话状态不能直接沿用。

恢复脚本同时激活 Linux venv、恢复 `WORKSPACE/SOURCE/STAMP/DS/REPORTS/UV_PROJECT_ENVIRONMENT`，并用空凭据阻止私有 `.env` 的密钥回退；它不安装依赖、不复制项目、不启动服务。无需每次 `uv sync`；若主动同步依赖移除了额外安装的 psutil，需自行补装并记录版本。

PowerShell 单指令交互恢复也可使用下面方式，与前面两步式二选一，不要重复 source：

```powershell
wsl.exe -d sp3-build -u root --cd /root/aiagent-eval/20261026T091836Z-i4Fyhq -- bash --rcfile /root/aiagent-eval/20261026T091836Z-i4Fyhq/.eval-session.sh -i
```

副本不是源目录的实时镜像。需要新环境时看[附录 A](#new-wsl-workspace)，历史环境、Docker 桥接与报告位置看[附录 B](#wsl-records)。不要全量覆盖已有 `.venv`、`.git`、运行数据或报告；逐文件同步后重新记录代码摘要，不把不同代码快照的结果当作同条件基线。

在选定的同一 Bash 会话建立本轮报告目录，后文统一使用 `$ROUND`：

```bash
umask 077
export ROUND_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
export ROUND="$REPORTS/round-$ROUND_ID"
mkdir -p "$ROUND"
test -f "$DS/judge-gold-kinds.json"
test -f "$DS/corpus-manifest.json"
```

继续条件：Python 是副本的 Linux `.venv/bin/python`，数据目录是 r3，工作目录不是 `/mnt/f/aiagent`。不要 source `.env`、读取生产 Memory、重建 r3 或覆盖原报告。时间标签用 UTC，便于关联报告。

## 2. 离线验证：不调用模型、不启动业务 API

本阶段已经通过。若没有新增代码，可直接去第 3 步；修改评测器、检索或 Memory 策略后再复跑。

先切离线；若执行本块，后面必须重新配置 Provider：

```bash
export APP_ENV=local CLOUD_MODE=false EXECUTION_STATE_MODE=local
export LLM_PROVIDER=mock ENABLE_MOCK_LLM=true
export STATE_PROVIDER=mock ENABLE_MOCK_STATE=true
export PLANNER_PROVIDER=mock ENABLE_MOCK_PLANNER=true
export VISION_PROVIDER=mock
export OPENAI_API_KEY= SILICONFLOW_API= EVAL_OFFLINE_MEMORY_KEY=
export MEMORY_LLM_API_KEY_ENV=EVAL_OFFLINE_MEMORY_KEY
export RAG_EMBEDDING_PROVIDER=huggingface RAG_EMBEDDING_LOCAL_FILES_ONLY=true
export TTS_PROVIDER=mock ENABLE_MOCK_TTS=true ENABLE_LOCAL_AUDIO_PLAYBACK=false
export ASR_PROVIDER=mock ENABLE_MOCK_ASR=true
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
unset EVAL_RUN_LIVE EVAL_BASE_URL EVAL_ISOLATED EVAL_JUDGE_API_KEY EVAL_JUDGE_VISION

python -m pytest \
  tests/unit/test_evaluation_contracts.py \
  tests/unit/test_evaluation_metrics.py \
  tests/unit/test_evaluation_regression.py \
  tests/unit/test_evaluation_contrast.py \
  tests/unit/test_evaluation_judge_protocol.py \
  tests/unit/test_evaluation_source_attribution.py \
  tests/api/test_evaluation_http_contract.py -q

python -m aiagent.evaluation.cli --dataset "$DS/offline-all-smoke.json" \
  --output "$ROUND/offline-smoke"
python -m aiagent.evaluation.cli --dataset "$DS/offline-all.json" --split dev \
  --output "$ROUND/offline-dev"
python -m aiagent.evaluation.cli --dataset "$DS/offline-all.json" --split regression \
  --output "$ROUND/offline-regression"
python -m aiagent.evaluation.cli --dataset "$DS/offline-trajectory.json" --split adversarial \
  --output "$ROUND/offline-refusal"
```

以上只覆盖评测基础设施。涉及检索、回答或 Memory 修复时，补跑对应范围：

```bash
python -X faulthandler -m pytest \
  tests/unit/test_rag_profile_field_recall.py \
  tests/unit/test_rag_query_recall.py tests/unit/test_rag_extractive_answer.py \
  tests/unit/test_reranker_query_specificity.py tests/unit/test_retriever_filename_tokens.py \
  tests/unit/test_chat_memory_smoke_regression.py \
  tests/unit/test_evaluation_rag_generation.py \
  tests/unit/test_env_secrets.py tests/unit/test_memory_provider_config.py \
  tests/unit/test_sync_eval_model_env.py tests/unit/test_rebuild_rag_cache.py \
  tests/unit/test_rag_embedding_response.py tests/unit/test_transfer_rag_cache.py -q
```

按变更范围补充其他业务测试，不把上述列表称为全项目测试。conftest 会给测试进程设置 mock；它不是生产模型验收。完整语料项缺少缓存/冻结集时可能 skip，需单独报告。

继续条件：测试和四项离线 CLI 均退出 0。离线 RAG 只用每题小语料 BM25，Memory/Vision 主要测策略，拒答 Graph 下游为 mock；不能替代真实混合检索、持久化或图片验收。

## 3. 配置真实被测模型与独立 Judge

从此步骤后的模型调用可能计费，会向所选端点发送对应资料或合成对话。先核实端点可信、数据可外发、模型可用和费用预算；不要把 Key 发到聊天或写进命令历史。

<a id="model-config"></a>

### 3.1 模型与凭据基准

| 用途 | Provider | 模型 | 地址 | 密钥引用 |
| --- | --- | --- | --- | --- |
| 主 LLM / State / Planner / Memory LLM | `openai` | `deepseek-flash` | `https://api.deepseek.com` | `OPENAI_API_KEY` |
| Vision | `openai` | `deepseek-flash` | `https://api.deepseek.com` | `OPENAI_API_KEY` |
| Memory embedding / RAG embedding | `siliconflow` | `Qwen/Qwen3-VL-Embedding-8B` | `https://api.siliconflow.cn/v1` | `SILICONFLOW_API` |

embedding 维数沿用本地 `4096`。`openai` 是接口协议，不表示请求发送至 OpenAI 官方。主聊天和 Memory LLM 发往 DeepSeek，embedding 独立发往 SiliconFlow；RAG embedding 曾实测为 4096 维，不能据此推断其他模型的权限或能力。

**Vision 配置按用户要求与聊天一致，2026-10-28 已完成真实图片请求和带图 Judge smoke。** 这只证明当时端点与模型支持该路径，不保证以后模型别名、权限或服务行为不变。若出现不支持图片或协议不兼容，停止该分项再确认能力；CLIP 检索、mock、文本问答和初始化成功均不能替代图片能力验证。

`*_API_KEY_ENV` 只填写变量名，不能直接填密钥；`*_BASE_URL` 填实际 URL，不能填另一个变量名字符串。现有对应关系：

```dotenv
MEMORY_LLM_API_KEY_ENV=OPENAI_API_KEY
MEMORY_EMBEDDER_API_KEY_ENV=SILICONFLOW_API
RAG_EMBEDDING_API_KEY_ENV=SILICONFLOW_API
RAG_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
VISION_API_KEY_ENV=OPENAI_API_KEY
VISION_BASE_URL=https://api.deepseek.com
```

实际 `OPENAI_API_KEY`、`SILICONFLOW_API` 只在本地私有配置填写，不发到聊天、不写入本文。`Settings` 读取当前工作目录 `.env`，进程环境优先；旧终端 export 可覆盖文件。命名凭据解析器先查进程再查 `.env`，显式空进程值阻止回退，且不会把所有 dotenv 内容导出到全局环境。

Mem0 的 LLM 已显式接收 `OPENAI_BASE_URL`；embedder 单独接收 `SILICONFLOW_BASE_URL`。当前安装的 Mem0 可能优先使用 `OPENROUTER_API_KEY`，项目遇到它与显式 Memory 地址冲突时拒绝初始化；评测 shell 先 unset 该变量。改配置后需要重启 API/worker 或重新创建容器，已有进程不会自动更新。

### 3.2 本地、云端与 WSL 的边界

本地 `.env` 与 `cloud.tencent.env` 共享模型参数和命名凭据，但云端保留 `APP_ENV=production/CLOUD_MODE=true`、容器地址、已有域名/CORS、限流及安全配置；不能直接复制开发网络、管理员或数据库设置。云端 CORS 占位域名、管理员令牌和数据库凭据仍需部署前审查。

云端 CLIP 不使用 Windows 路径，需准备实际模型及图库资产。若已有 Qdrant Memory 集合是 `1024` 维，切换 `4096` 维前换新集合并迁移/重新嵌入旧记忆，不启用 `MEMORY_RESET_VECTOR_STORE` 删除旧数据。RAG 重建不是 Memory 迁移。云端 Redis 同样需要 RedisJSON/Search；普通 `redis:7-alpine` 不能仅凭 PONG 认定满足 RedisSaver 要求。

既有 WSL 副本在 2026-10-27 已生成私有 `.env` 和 `.env.eval-models.sh`，权限为 `600`。它们含真实模型凭据，不能 `cat`、`set -x`、截图或提交 Git；“建环境时未复制凭据”仅是历史状态。Judge 独立配置，不从本地自动复制。

源模型/密钥变化后，先在 WSL 更新私有文件；本块只同步配置，不调用模型：

```bash
cd "$WORKSPACE"
.venv/bin/python -m scripts.sync_eval_model_env \
  --source /mnt/f/aiagent/.env \
  --workspace "$WORKSPACE" \
  --dataset "$DS"
```

同步工具只复制模型白名单与被引用密钥，不复制管理员、数据库、S3 或 Judge 凭据；目标已有 Judge 配置保留。WSL 使用独立 Redis `16379`、Qdrant `16333`、评测集合和路径；第 6 步再用 `ROUND_ID` 隔离每轮状态。图库只用冻结 `reference-gallery`。Windows CLIP 路径转换为 `/mnt/f/...`，依赖 F 盘可访问，不复制整个模型目录。副本不是实时镜像，代码更新另行逐文件审阅同步。

### 3.3 加载配置并设置独立 Judge

新会话或第 2 步后，先加载 profile，再输入 Judge。Profile 只加载变量，不请求模型、不启服务、不重建索引；**不要直接 `source .env`**。已有真实配置的会话不再 source 离线恢复脚本，以免清空凭据或切回 mock：

```bash
source "$WORKSPACE/.env.eval-models.sh"
unset OPENROUTER_API_KEY
export LLM_PROVIDER=openai ENABLE_MOCK_LLM=false
export LLM_TEMPERATURE=0 LLM_TIMEOUT_SECONDS=90 LLM_MAX_TOKENS=600

read -rp 'Judge base URL（按服务要求，通常含 /v1）: ' EVAL_JUDGE_BASE_URL
read -rp 'Judge 模型名: ' EVAL_JUDGE_MODEL
read -rsp 'Judge Key: ' EVAL_JUDGE_API_KEY
printf '\n'
export EVAL_JUDGE_BASE_URL EVAL_JUDGE_MODEL EVAL_JUDGE_API_KEY
export APP_ENV=local CLOUD_MODE=false
```

已配置的当前终端不需要重新输入，但应检查存在性，不打印值：

```bash
: "${OPENAI_BASE_URL:?缺少被测端点}"
: "${LLM_MODEL:?缺少被测模型}"
: "${OPENAI_API_KEY:?缺少被测Key}"
: "${EVAL_JUDGE_BASE_URL:?缺少Judge端点}"
: "${EVAL_JUDGE_MODEL:?缺少Judge模型}"
: "${EVAL_JUDGE_API_KEY:?缺少Judge Key}"
```

Judge 最好与被测模型不同，并记录实际版本。当前 Judge v8 自动读取 r3 旁的 `judge-gold-kinds.json`；该文件将 Persona 行为目标与事实目标分开，不能为了通过率随意改标注。普通模式要求覆盖绑定正确 claim；显式 `--judge-verify-visual-gold` 将图像支持度与文字 gold 分通道，使用独立覆盖评定，详见[协议](project-evaluation-implementation.md#judge-protocol)。Persona 默认仍只评末轮事实，跨轮范围需显式 overrides。完整回归仍为 v6，v7/v8 只是失败定向验证，使用同模型，结构合法不保证语义正确；不要混作同条件全量基线。下方 smoke 是新实验的命令示例，不能用来重复已完成运行。

复现 2026-10-28 本轮条件时，Judge 为 `https://api.deepseek.com` 的 `deepseek-flash`，所有带 `--judge provider` 的命令还需加 `--judge-thinking disabled --judge-max-output-tokens 4096`，包括后续由用户执行的 heldout。前者只支持官方 HTTPS DeepSeek 端点，换到其他 Judge 时不能照搬；默认 thinking 与显式 disabled 是不同评审条件，不混作同条件基线。

## 4. 首次 Provider 验证：9 条 smoke

首次 Provider 验证时使用本节；已有报告不无故重跑。Provider 自由生成与 `/chat` 抽取是不同路径，不能互相替代质量结论。三组各 3 条，**每执行一条命令就审阅报告，再决定是否继续**。

```bash
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-smoke.json" \
  --judge provider --allow-provider --judge-max-repairs 1 \
  --judge-request-budget 6 --judge-max-output-tokens 4096 --debug-local \
  --variant rag-question-scope --output "$ROUND/provider-rag-smoke"

python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-fixed-smoke.json" \
  --judge provider --allow-provider --judge-max-repairs 1 \
  --judge-request-budget 6 --judge-max-output-tokens 4096 --debug-local \
  --output "$ROUND/provider-rag-fixed-smoke"

python -m aiagent.evaluation.cli --dataset "$DS/provider-persona-smoke.json" \
  --judge provider --allow-provider --judge-max-repairs 1 \
  --judge-request-budget 6 --judge-max-output-tokens 4096 --debug-local \
  --output "$ROUND/provider-persona-smoke"
```

预算含初始 Judge 与协议修复，三组最多 18 次 Judge 请求；不是整链路最多 18 次调用。多轮 Persona 使这 9 条用例正常约需 12 次生成调用，被测模型网络重试还可能额外收费。质量失败不重试；Judge 鉴权、限流、网络超时不自动重试。

`--debug-local` 是显式允许本地脱敏留档，可删掉以完全不保存回答/判词；启用时写入每个运行目录的 `.judge-debug/`，不上传、不提交 Git。Linux 目录 0700、文件 0600，仍不能保证过滤全部个人信息和未知格式秘密。

判定意义：`provider-rag` 是 BM25 检索 + 真实生成；`provider-rag-fixed` 是给定原文窗口 + 真实生成；Persona 是实际角色配置下的真实生成。此时还没有评测真实业务 API 的向量混合检索。

## 5. 每跑一项，统一按这个方法判读

CLI 会输出实际 `report.json` 路径。将它填入下面变量，不要拿旧运行或随便找到的第一份报告：

```bash
read -rp '刚输出的 report.json 完整路径: ' REPORT
jq '{protocol, ok, operational_error, operational_diagnostic, judge_usage, summary}' "$REPORT"
jq '[.results[] | select(.status != "passed") |
  {case_id, status, scope, error_stage, error_code, judge_diagnostics, failures, metrics}]' "$REPORT"
```

| 状态 | 含义 | 怎么处理 |
| --- | --- | --- |
| CLI 0，ok=true | 本次选中用例满足当前断言 | 核对适用指标、scope 与覆盖后再继续 |
| CLI 1，failed | 业务断言或质量门槛失败 | 抽审来源、回答、检索和行为，不刷分、不自动降低门槛 |
| CLI 2，judge_error | Judge 协议、配置、请求等异常 | 看 error_stage/error_code/finish_reason，先修评审链路 |
| CLI 2，error / operational_error | 观察、HTTP、适配器或运行配置异常 | 看错误类别、隔离服务和本地私有日志，不能计为模型答错 |
| 指标为 null、样本为 0 或测试 skipped | 没有适用证据或未执行 | 不等于 0 分，也不等于通过 |

`judge_diagnostics` 末次 `complete/ok` 只说明判词合法，不说明回答质量通过；有过一次协议修复但最终成功时，前面的错误仍保留。报告没有原答复时不能凭哈希恢复；只有显式 debug 的语义用例才有本地脱敏评审材料，不是完整业务追踪包。

### 核心指标统一口径

| 指标 | 解释与边界 |
| --- | --- |
| pass_rate | passed / 本次选中结果总数；异常不能从分母隐去，另报 status 分布 |
| top-k | 检索返回前 K 条的设置，不是准确率；分别报告 Hit/Recall/MRR/nDCG@1/3/5/10 |
| faithfulness | 事实声明中被实际提供证据支持的比例；无证据不造分 |
| fact_accuracy | 与独立 gold 一致的事实声明比例；不等于外部世界事实全部被核实 |
| fact_unverifiable_rate | 独立 gold 无法核验的事实声明 / 全部声明；仍计入 fact_accuracy 分母，不自动视为正确 |
| factual_gold_coverage | 已覆盖事实目标 / 全部事实目标 |
| behavior_pass_rate | satisfied 行为目标 / 全部行为目标；violated、not_observable 均不算满足 |
| gold_coverage（当前口径） | (已覆盖事实 + satisfied 行为) / 全部目标；不能混用旧 v1 基线 |
| persona_consistency / style_score | 核心身份、跨轮设定与风格；正确拒绝和不确定性不能当作风格失败 |
| visual_grounded/unsupported/contradiction_rate | 实际图片下的可见支持、无支持或矛盾声明；不是身份准确率/OCR 准确率 |

继续条件：Judge 无未解决的执行/协议问题，且 smoke 质量符合已约定的逐例门槛；若严格门槛仍失败，先定位检索、生成、gold 或标注问题，再决定是否做有限、另存报告的调试实验。

`faithfulness=1`、`gold_coverage=1`、`fact_contradiction_rate=0` 仍可能不满足 `fact_accuracy=1`：回答可能补充了来源支持但独立 gold 未覆盖的信息。RAG Provider 生成现按问题字段和时间/单位/版本粒度给出最小充分答案，证据作为 JSON 数据而非系统指令输入。生成提示词摘要进入结果条件；新旧提示词不能冒充同条件接受基线。此改动不调整生产 `/chat` prompt，也不改变评分分母、gold 或阈值。

## 6. 启动隔离真实依赖与 API

只有第 4、5 步处理完成后再进入。Memory 用例含写入、修改、删除，**不得连接生产 Redis/Qdrant/真实用户**。

### 6.1 新建本轮依赖

```bash
docker version
export REDIS_NAME="aiagent-eval-redis-$ROUND_ID"
export QDRANT_NAME="aiagent-eval-qdrant-$ROUND_ID"
export REDIS_VOLUME="aiagent-eval-redis-data-$ROUND_ID"
export QDRANT_VOLUME="aiagent-eval-qdrant-data-$ROUND_ID"

docker pull redis/redis-stack-server:latest
docker pull qdrant/qdrant:v1.14.1
export REDIS_DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' redis/redis-stack-server:latest)"
export QDRANT_DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' qdrant/qdrant:v1.14.1)"
printf '%s\n%s\n' "$REDIS_DIGEST" "$QDRANT_DIGEST" > "$ROUND/container-image-digests.txt"

docker run -d --name "$REDIS_NAME" -p 127.0.0.1:16379:6379 \
  --mount "type=volume,source=$REDIS_VOLUME,target=/data" "$REDIS_DIGEST"
docker run -d --name "$QDRANT_NAME" -p 127.0.0.1:16333:6333 \
  --mount "type=volume,source=$QDRANT_VOLUME,target=/qdrant/storage" "$QDRANT_DIGEST"

docker exec "$REDIS_NAME" redis-cli ping
docker exec "$REDIS_NAME" redis-cli MODULE LIST
curl --fail --silent --show-error http://127.0.0.1:16333/readyz
```

先等待依赖就绪。Redis 需要 JSON 与搜索能力，仅 PONG 不代表官方 RedisSaver 可用。端口已占用就为评测换端口并同步后面的配置，不停止原服务。

当前 Docker 通过 Windows 客户端桥接；若新会话没有 `docker` 函数，按[附录 B 的 Docker 说明](#wsl-docker)恢复。容器健康但 WSL 连接不到端口时先核查 Docker Desktop/WSL 网络，不把问题归因于模型；不要为打通测试随意公开绑定 0.0.0.0。

### 6.2 配置真实 Runtime

沿用第 3 步的聊天模型/Judge。Memory LLM 使用 DeepSeek；Memory/RAG embedding 独立使用 SiliconFlow，不能把 embedding 地址覆盖为聊天地址。模型、密钥和 CLIP 路径由私有 profile 加载；下面只覆盖逐轮隔离参数：

```bash
export REDIS_URL=redis://127.0.0.1:16379/0
export REDIS_PREFIX="aiagent:eval:$ROUND_ID"
export EXECUTION_STATE_MODE=redis EXECUTION_STATE_FAIL_CLOSED=true
export QDRANT_HOST=127.0.0.1 QDRANT_PORT=16333
export MEMORY_VECTOR_COLLECTION="aiagent_eval_${ROUND_ID//[^a-zA-Z0-9]/_}"
export MEMORY_ENABLE_GRAPH=false MEMORY_RESET_VECTOR_STORE=false
export MEMORY_WRITE_ASYNC_ENABLED=false MEMORY_LONG_TERM_DEFAULT_ENABLED=true
export MEMORY_PREFERENCES_PATH="$WORKSPACE/data/runtime/preferences-$ROUND_ID.json"

export STATE_PROVIDER=openai STATE_MODEL="$LLM_MODEL" ENABLE_MOCK_STATE=false
export PLANNER_PROVIDER=openai PLANNER_MODEL="$LLM_MODEL" ENABLE_MOCK_PLANNER=false
export MEMORY_LLM_PROVIDER=openai MEMORY_LLM_MODEL="$LLM_MODEL"
export MEMORY_LLM_API_KEY_ENV=OPENAI_API_KEY
export MEMORY_EMBEDDER_PROVIDER=siliconflow MEMORY_EMBEDDER_API_KEY_ENV=SILICONFLOW_API
: "${SILICONFLOW_API:?缺少SiliconFlow凭据，请重新同步并加载profile}"
: "${MEMORY_EMBEDDER_MODEL:?缺少embedding模型}"
: "${MEMORY_EMBEDDING_DIMS:?缺少embedding维数}"

export RAG_EMBEDDING_PROVIDER=siliconflow RAG_EMBEDDING_DEVICE=cpu
export RAG_EMBEDDING_MODEL_NAME="$MEMORY_EMBEDDER_MODEL"
export RAG_EMBEDDING_API_KEY_ENV=SILICONFLOW_API RAG_EMBEDDING_BASE_URL="$SILICONFLOW_BASE_URL"
export RAG_EMBEDDING_DIMENSIONS="$MEMORY_EMBEDDING_DIMS"
export RAG_AUTO_REBUILD_ON_STALE=false
export RAG_INDEX_MANIFEST_PATH="$WORKSPACE/data/cache/knowledge/index_manifest.json"

# Vision 默认对齐聊天端点；该历史配置已完成真实图片请求验证，新端点/模型仍需单独验证。
# 若后续选择独立视觉模型，先修改源配置并重新同步，不在此覆盖它。
: "${VISION_BASE_URL:?缺少Vision地址}"
: "${VISION_MODEL:?缺少Vision模型}"
export VISION_UPLOAD_DIR="$WORKSPACE/data/uploads/eval-$ROUND_ID"
export VISION_CHARACTER_ROOT_DIR="$DS/reference-gallery"
export VISION_CHARACTER_INDEX_DIR="$WORKSPACE/data/cache/vision/eval-character-index"
export VISION_CHARACTER_EMBEDDING_DEVICE=cpu
# CLIP 路径及离线设置沿用 profile，不自动下载或换回含查询图片的图库。

export APP_ENV=local CLOUD_MODE=false
export API_CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
export API_CORS_ALLOW_CREDENTIALS=true
export RATE_LIMIT_ENABLED=false INFLIGHT_LIMIT_ENABLED=false
export TTS_PROVIDER=mock ENABLE_MOCK_TTS=true ENABLE_LOCAL_AUDIO_PLAYBACK=false
export ASR_PROVIDER=mock ENABLE_MOCK_ASR=true
export EVAL_ISOLATED=1 EVAL_BASE_URL=http://127.0.0.1:18080
export EVAL_SUT_IDENTITY="local-eval-$ROUND_ID"
export EVAL_CORPUS_SHA256="$(sha256sum "$DS/corpus-manifest.json" | awk '{print $1}')"
```

Mem0 已显式装配 LLM 与 embedding 的两个地址，离线配置测试只证明参数正确传递，不能证明远端可用。`deepseek-flash` 图片输入仍待核实，真实 Vision 失败时停止该分项，不以 mock 冒充通过。缓存过期时按[第 6.3 节重建](#rag-cache-rebuild)；不要在主服务与脚本中同时重建。

Voice 不在本轮范围，因此 ASR/TTS 保持 mock，不将它们写为已真实验收。图记忆未启用，不声明覆盖 Neo4j。CLIP 首次可能下载模型；已经缓存且希望完全本地加载时，保持已验证的离线设置。参考图库只用冻结 reference-gallery，不换回含查询原图的整个图库。

<a id="rag-cache-rebuild"></a>

### 6.3 Windows 重建、WSL 复用与离线校验

当前推荐：在 Windows 请求 embedding 并构建完整 CPU FAISS，再离线复制到 WSL。两端可以复用索引，不要求一定在运行服务的系统里重建。**WSL 后续查询仍需要访问 embedding 服务；迁移不能消除查询侧网络超时。**

#### 6.3.1 已确认的问题与处理

2026-10-27，Windows 的 2 条及 8 条合成探针成功，实际维数为 4096；32 条探针返回 32 个向量，但 index 为 0～7 各重复四次。此前整库首批失败也命中 `embedding_response_index_mismatch`。这证明当前端点/模型的 32 条响应不能可靠对齐，不代表已经确认供应商内部实现或所有模型都存在同一限制。

保留连续、唯一整数 index 的严格校验，不按未知响应顺序重新编号，不补零、不重复向量。当前本地、云端及示例配置统一 `RAG_EMBEDDING_BATCH_SIZE=8`，同步 WSL 后使用相同值。模型仍为 SiliconFlow 的 `Qwen/Qwen3-VL-Embedding-8B`，4096 维；不更换密钥、维数或降低评测门槛。构建采用暂存后替换，旧索引只作为回滚备份，不再作为当前索引。

#### 6.3.2 Windows 完整命令

以下重建会外发知识原文并计费；确认语料范围与预算，先停用本项目 API/worker。不要为了查看结果再次运行 `--execute`。已经构建成功时从 seal 开始。

在新的 PowerShell 中执行：

```powershell
Set-Location F:\aiagent
$ErrorActionPreference = 'Stop'
$Py = 'F:\aiagent\.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 清除本终端旧的 RAG 覆盖；密钥由本地 .env 命名引用读取，不打印。
Get-ChildItem Env: | Where-Object { $_.Name -like 'RAG_*' } |
    ForEach-Object { Remove-Item -LiteralPath ("Env:" + $_.Name) }
$Log = 'F:\aiagent\data\cache\rag-rebuild-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '.log'

& $Py -m scripts.rebuild_rag_cache --preflight
if ($LASTEXITCODE -ne 0) { throw '离线预检失败，停止' }
& $Py -X faulthandler -u -m scripts.rebuild_rag_cache --execute 2>&1 | Tee-Object -FilePath $Log
if ($LASTEXITCODE -ne 0) { throw "重建失败，保留日志并停止：$Log" }

& $Py -m scripts.transfer_rag_cache seal --cache-dir data/cache/knowledge --knowledge-dir data/knowledge/public --trusted-local-cache
if ($LASTEXITCODE -ne 0) { throw '封装校验失败' }
& $Py -m scripts.transfer_rag_cache verify --cache-dir data/cache/knowledge --knowledge-dir data/knowledge/public --trusted-local-cache
if ($LASTEXITCODE -ne 0) { throw '索引复核失败' }
```

`--preflight` 使用 MockTransport/合成向量，不联网；真实重建仍自动再预检一次。默认不带开关仅输出计划；`--cache-dir`、`--knowledge-dir` 支持独立输出/语料并传递到子进程，禁止两个目录重叠。自定义 manifest 必须在目标缓存内。真实构建只有通过向量计数、保存/重载及 freshness 后才发布，失败不覆盖旧目录。

#### 6.3.3 WSL 接收与发布

先由 Windows 同步模型配置，命令只同步白名单和被引用密钥，不输出密钥、不请求模型：

```powershell
wsl -d sp3-build -- bash -lc 'cd /root/aiagent-eval/20261026T091836Z-i4Fyhq && .venv/bin/python -m scripts.sync_eval_model_env --source /mnt/f/aiagent/.env --workspace /root/aiagent-eval/20261026T091836Z-i4Fyhq --dataset /root/aiagent-eval/20261026T091836Z-i4Fyhq/data/evaluation/project-20261026-r3'
```

进入 WSL 后：

```bash
export WORKSPACE=/root/aiagent-eval/20261026T091836Z-i4Fyhq
cd "$WORKSPACE"
source .venv/bin/activate
source .env.eval-models.sh
# 不 source .eval-session.sh：它会重新切回 mock 并清空真实凭据。
# 在子 shell 中执行迁移；任一步失败即停止，不影响外部终端。
(
set -euo pipefail
INCOMING=$(mktemp -d "$WORKSPACE/data/cache/.rag-incoming-XXXXXX")
mkdir -p "$INCOMING/faiss_index"
cp -- /mnt/f/aiagent/data/cache/knowledge/{split_docs.json,index_manifest.json,transfer_manifest.json} "$INCOMING/"
cp -- /mnt/f/aiagent/data/cache/knowledge/faiss_index/{index.faiss,index.pkl} "$INCOMING/faiss_index/"

python -m scripts.transfer_rag_cache verify --cache-dir "$INCOMING" \
  --knowledge-dir "$WORKSPACE/data/knowledge/public" --trusted-local-cache
# 上一步退出非 0 时停止，不执行发布。
# 已停止该副本 API/worker 的全部索引读写后才发布；先不加 --execute，查看计划：
python -m scripts.transfer_rag_cache install --cache-dir "$INCOMING" \
  --knowledge-dir "$WORKSPACE/data/knowledge/public" \
  --target-dir "$WORKSPACE/data/cache/knowledge" --trusted-local-cache
# 校验和计划均成功后执行：
python -m scripts.transfer_rag_cache install --cache-dir "$INCOMING" \
  --knowledge-dir "$WORKSPACE/data/knowledge/public" \
  --target-dir "$WORKSPACE/data/cache/knowledge" --trusted-local-cache --execute
python -m scripts.transfer_rag_cache verify --cache-dir "$WORKSPACE/data/cache/knowledge" \
  --knowledge-dir "$WORKSPACE/data/knowledge/public" --trusted-local-cache
)
```

四个必需索引文件为 `split_docs.json`、`index_manifest.json`、`faiss_index/index.faiss` 和 `faiss_index/index.pkl`；`transfer_manifest.json` 额外提供文件与完整语料 SHA256、依赖版本。不得仅复制 FAISS 二进制或 split docs。

迁移工具**不创建远程 embedding 客户端**，检查完整语料字节、四文件摘要、FAISS/numpy/LangChain 精确版本、manifest 配置、向量数量/维数/有限性、JSON-pickle 逐行内容映射及原生自检索；然后只修正路径与目标语料指纹，保留 doc_id、chunk_id 及向量顺序。在本地生成的新缓存中重新封装后发布，源端摘要仍保留在 incoming 中。摘要能证明完整性，不能证明来源可信；`--trusted-local-cache` 只用于自己构建且全程保管的 pickle，禁止用于网上下载的未知缓存。

工具目前使用标准文件名 `index_manifest.json`；自定义文件名需先扩展并测试工具。两次 rename 不是断电事务，普通发布失败尝试回滚；不要在读写中发布，不删除备份、失败暂存或原报告。迁移成功只证明索引可复用，不证明回答、Memory 或 Vision 质量通过。接着按第 6.4 节启动 API，再做第 7 节真实 RAG smoke，不需要再次重建。

#### 6.3.4 故障分流与历史

| 现象 | 处理 |
| --- | --- |
| embedding_provider_timeout / embedding_provider_connection_error | 未拿到响应，检查当前系统 DNS/TLS/代理；看 cause_type 区分 ConnectTimeout/ReadTimeout，不能归因为维数错误。Windows 能构建不代表 WSL 查询联网已经解决；合成探针单请求超时为 30 秒、SDK 重试为 0 |
| embedding_response_index_mismatch | 看安全字段 actual_indexes；当前已证实 32 条重复，使用已验证的 8 条配置，不删除对齐校验 |
| embedding_response_count_mismatch / dimension_mismatch | 核对条数/实际维数，不丢输入、不自动修改维数 |
| embedding_response_vector_type / nonfinite_or_nonnumeric | 拒绝非法值，不强转或替换为零 |
| embedding_provider_http_error | 核对状态码与权限/配额，不反复整库重试 |
| 摘要、语料、版本、freshness 不一致 | 停止导入，核对两端配置和来源，不手改清单为 fresh |
| native_crash | 保留阶段日志、faulthandler 栈和退出码，不自动循环付费重建 |

原生故障、超时与响应索引问题的历史证据见[评测历史](evaluation-history.md)。AVX2 独立包装缺失但统一 `faiss.swigfaiss` 可用不等于失败；以预检输出的实际 backend 和退出码判断，不隐藏异常或自动循环重建。

### 6.4 启动与检查

先检查 18080 未被占用；已有服务则换评测端口与 EVAL_BASE_URL，不停止它。然后：

```bash
python -m uvicorn apps.api.http_server:app --host 127.0.0.1 --port 18080 --workers 1 \
  > "$ROUND/api-server.log" 2>&1 &
export API_PID=$!
printf '%s\n' "$API_PID" > "$ROUND/api-server.pid"

curl --fail --silent --show-error "$EVAL_BASE_URL/live"
curl --fail --silent --show-error "$EVAL_BASE_URL/ready" | jq .
curl --fail --silent --show-error "$EVAL_BASE_URL/knowledge/stats" \
  | tee "$ROUND/knowledge-stats.json" | jq .
curl --fail --silent --show-error "$EVAL_BASE_URL/knowledge/index/freshness?refresh=true" \
  | tee "$ROUND/knowledge-freshness.json" | jq .
```

启动尚未完成时等待后再检查，不循环重启。继续条件：请求确实到达本轮进程，关键能力就绪，知识库文档/块数量合理，freshness 可接受，没有降级到 NullRAG/NullMemory/mock。HTTP 200 不是充分证据。首次索引/embedding 可能收费，冷启动另记，不计作稳态性能。

## 7. 真实组件、轨迹和任务先做 smoke

本节每条执行后都按第 5 步判读。真实检索虽不生成聊天回答，远程 embedding 仍可能计费。

已完成的检索修复与原失败报告见[历史记录](evaluation-history.md)。无需按历史运行的补丁命令逐轮重跑；新环境才从本节依次验证。已有环境先审阅[现状入口](README.md)，不要重复启动已经完成的付费项目。

```bash
# 真正的 256 篇 Markdown 切分、索引与混合检索。
python -m aiagent.evaluation.cli --dataset "$DS/api-rag-smoke.json" \
  --allow-api --output "$ROUND/api-rag-smoke"

# 真正 /chat 的知识问答；没有实际注入证据就不计算 faithfulness。
python -m aiagent.evaluation.cli --dataset "$DS/api-rag-chat-smoke.json" \
  --allow-api --allow-provider --judge provider --debug-local \
  --output "$ROUND/chat-rag-smoke"

# 学习、禁用、编辑、置顶、跨会话、删除与清理断言。
python -m aiagent.evaluation.cli --dataset "$DS/api-memory-smoke.json" \
  --allow-api --allow-provider --judge provider --debug-local \
  --output "$ROUND/memory-api-smoke"

# 真实配置的 Runtime Graph；在评测进程内额外构建 runtime。
python -m aiagent.evaluation.cli --dataset "$DS/runtime-graph.json" \
  --allow-api --allow-provider --judge provider --debug-local \
  --output "$ROUND/runtime-graph"
```

Vision 还要求 **Judge 本身支持图片**。若第 3 步的 Judge 是纯文本模型，先在当前会话重新输入真实可看图 Judge 的 endpoint/model/key，然后执行；不能只设置环境变量就宣称模型具备视觉能力。

```bash
export EVAL_JUDGE_VISION=1
python -m aiagent.evaluation.cli --dataset "$DS/api-vision-reviewed-smoke.json" \
  --allow-api --allow-provider --judge provider --debug-local \
  --output "$ROUND/vision-api-smoke"
```

后续混合验收沿用已核实支持图片的 Judge；切换 Judge 后的结果不能与旧 Judge 当同条件基线。图片 gold 是可见内容的代理粗粒度标注，仍需用户审定，没有身份与完整 OCR 真值，因此不能报告身份识别准确率或 CER/WER 基线。

可选的真实集成测试只补充上传和状态链路验证，**另有实际模型调用费用，不替代上述语义评测**：

```bash
EVAL_RUN_LIVE=1 EVAL_VISION_DATASET="$DS/api-vision-reviewed-smoke.json" \
  python -m pytest tests/integration/test_evaluation_live.py -q
```

这里只给单个命令开启 EVAL_RUN_LIVE，不全局开启。pytest 客户端会被 conftest 设为 mock，但它调用的是另一个已启动的真实 API 进程，不能据此称 API 也变成 mock；跳过也不能写作通过。

继续条件：无未解决的执行/Judge 异常，关键业务与质量断言满足，Memory cleanup 无失败。残留只按本轮 eval 用户核查，不执行 FLUSHALL/FLUSHDB 或删除通用集合。

<a id="current-rag-regression"></a>

### 7.1 真实检索回归已通过

用户报告 `api-rag-regression-profile-fields/20261027T143310Z-cef82a02/report.json` 为 470/470，Hit@1/3/5/10 均为 1，无执行异常或 Judge 请求。该结论仅适用于当前 regression 的真实文档检索，不等于片段充分性、生成事实正确率或 heldout 泛化通过。原 403/470 和新报告均保留，详情见[历史记录](evaluation-history.md)。

<a id="provider-regression-diagnostics"></a>

### 7.2 Provider 诊断已完成

2026-10-28 已完成有预算的诊断、引用协议修复和后续 regression，详见[本轮执行记录](evaluation-history.md)。此入口是小语料 BM25 + 真实生成，**不是**真实 API 混合检索；不再保留已经过期的逐轮补丁命令。

旧低分、Judge 截断、主动停止和原生中断均保留原始证据。不要重复运行诊断，也不要把缺少原回答的旧报告重评分为成功。后续只有实际代码或协议变化、数据版本变化且明确获准时，才按第 8 步新建输出目录复跑。

复现本轮 Judge 条件需在 Provider 命令显式加入 `--judge-thinking disabled --judge-max-output-tokens 4096`；`disabled` 只适用于已核实的官方 HTTPS DeepSeek 端点。最多一次格式修复且预算有界，合法质量低分不重试到通过。新旧 Judge 与生成提示词条件不可混作同一接受基线。

## 8. 分项回归、对照实验与候选基线

### 8.1 先计算付费规模，再分项运行

下面是 regression，不是 heldout，不使用 repeat=3 作为默认首跑。未指定 Judge 预算时，CLI 按所选评审通道数 × repeat × (1+max_repairs) 计算：普通文本/单通道每例一个，显式视觉双通道每例两个；max_repairs=1时分别最多2/4次。预算不限制被测生成、embedding或服务内部调用费用。

例如先查看 Persona 这一项的规模：

```bash
jq '{selected: ([.cases[] | select(.split == "regression")] | length),
     semantic: ([.cases[] | select(.split == "regression" and .oracle.semantic)] | length)}' \
  "$DS/provider-persona.json"
```

按当前批准的费用，选择一项执行、看报告、再进入下一项，不把下列代码当无条件批处理：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/api-rag.json" --split regression \
  --allow-api --output "$ROUND/api-rag-regression"
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag.json" --split regression \
  --allow-provider --judge provider --output "$ROUND/provider-rag-regression"
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-fixed.json" --split regression \
  --allow-provider --judge provider --output "$ROUND/provider-rag-fixed-regression"
python -m aiagent.evaluation.cli --dataset "$DS/provider-persona.json" --split regression \
  --allow-provider --judge provider --output "$ROUND/persona-regression"
python -m aiagent.evaluation.cli --dataset "$DS/api-rag-chat.json" --split regression \
  --allow-api --allow-provider --judge provider --output "$ROUND/chat-rag-regression"
python -m aiagent.evaluation.cli --dataset "$DS/api-memory.json" --split regression \
  --allow-api --allow-provider --judge provider --output "$ROUND/memory-api-regression"
python -m aiagent.evaluation.cli --dataset "$DS/api-vision-reviewed.json" --split regression \
  --allow-api --allow-provider --judge provider --output "$ROUND/vision-api-regression"
```

dev 用于调试；`provider-rag-challenge.json` 分别用 `--split dev`、`--split regression`、`--split adversarial` 检查原文矛盾、跨角色、无答案与隐私场景，不提前用 heldout 调参。例如：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-challenge.json" --split adversarial \
  --allow-provider --judge provider --output "$ROUND/rag-adversarial"
```

### 8.2 用对照解释收益，不只看总分

检索重排对照不调用模型：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/offline-rag.json" --split regression \
  --variant rerank-on --output "$ROUND/rerank-on"
python -m aiagent.evaluation.cli --dataset "$DS/offline-rag.json" --split regression \
  --variant rerank-off --overrides "$DS/offline-rag-contrast-overrides.json" \
  --output "$ROUND/rerank-off"
```

Persona guard 对照会额外付费，先 repeat=1：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/provider-persona.json" --split regression \
  --allow-provider --judge provider --variant guard-on --output "$ROUND/guard-on"
python -m aiagent.evaluation.cli --dataset "$DS/provider-persona.json" --split regression \
  --allow-provider --judge provider --variant guard-off \
  --overrides "$DS/provider-persona-contrast-overrides.json" --output "$ROUND/guard-off"
```

`*-overrides.json` 是输入覆盖，不是 Dataset。现有 API 适配器不能靠这个 overrides 关闭真实服务的 rerank。检索上下文与 fixed 原文上下文的 RAG 结果按 group_id 配对，不同 case-id 不调用 --baseline 硬比。若要看脱敏最终回答，需在执行前显式加 --debug-local；事后不能从 report 哈希恢复。

### 8.3 联合功能验收与候选基线

各项通过并完成失败/成功样本抽审后：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/release-suite.json" \
  --allow-api --allow-provider --judge provider --release \
  --output "$ROUND/release-suite"
```

40 条复用已有 dev/regression/adversarial 用例，不含 heldout；不是新增 40 个独立样本。`--release` 检查当前三层四组件覆盖，不验证负载、容器资源或所有安全故障，也不是产品已可发布的充分条件。

人工接受通过报告为候选基线，并冻结数据/gold/标注、模型/Judge、提示词、阈值与环境。回归例子如下，基线必须来自同一个 offline-rag regression：

```bash
read -rp '已人工接受的 offline-rag regression report.json 路径: ' BASELINE_REPORT
python -m aiagent.evaluation.cli --dataset "$DS/offline-rag.json" --split regression \
  --baseline "$BASELINE_REPORT" --max-drop 0 --output "$ROUND/baseline-regression"
```

比较器要求相同协议、数据、split、repeat、Judge 条件、被测配置、SUT identity、API origin、corpus 等。更换 Judge、端口、路径、隔离集合或预算可能导致条件不兼容；应作为新实验或新基线，不改报告伪造兼容。v1/v2 不直接比较；重复运行/同源变体不当独立样本，按 group_id 分组分析。

## 9. 冻结后再做 heldout 验收

**此节仅供用户最终验收时执行，本轮代理不会运行。先处理 regression 中的标注待复核项，并记录接受的候选快照。**

只有第 8 步方案冻结、来源与视觉标注审阅、费用确认后才执行。按分项逐条运行并检查，不用 heldout 反复挑提示词或参数：

```bash
python -m aiagent.evaluation.cli --dataset "$DS/offline-all.json" --split heldout \
  --output "$ROUND/heldout-offline"
python -m aiagent.evaluation.cli --dataset "$DS/api-rag.json" --split heldout \
  --allow-api --output "$ROUND/heldout-api-rag"
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag.json" --split heldout \
  --allow-provider --judge provider --output "$ROUND/heldout-provider-rag"
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-fixed.json" --split heldout \
  --allow-provider --judge provider --output "$ROUND/heldout-fixed-rag"
python -m aiagent.evaluation.cli --dataset "$DS/provider-rag-challenge.json" --split heldout \
  --allow-provider --judge provider --output "$ROUND/heldout-rag-challenge"
python -m aiagent.evaluation.cli --dataset "$DS/provider-persona.json" --split heldout \
  --allow-provider --judge provider --output "$ROUND/heldout-persona"
python -m aiagent.evaluation.cli --dataset "$DS/api-rag-chat.json" --split heldout \
  --allow-api --allow-provider --judge provider --output "$ROUND/heldout-chat"
python -m aiagent.evaluation.cli --dataset "$DS/api-memory.json" --split heldout \
  --allow-api --allow-provider --judge provider --output "$ROUND/heldout-memory"
python -m aiagent.evaluation.cli --dataset "$DS/api-vision-reviewed.json" --split heldout \
  --allow-api --allow-provider --judge provider --output "$ROUND/heldout-vision"
```

heldout 失败时如实记录泛化失败，不删除难例或归零重跑次数；如果根据失败调参，这批数据已成为开发证据，下一次独立泛化验收需新的留出组。当前留出是来源/剧本/原图组划分，不代表模型预训练未见。

## 10. 最后测系统负载与资源

先保证功能质量与 Memory 清理正常，再从低负载逐档测。现有 load 只支持单固定文本，不支持这批混合 JSON，因此只能形成知识问答探针的容量结果，不是全业务混合容量。

下面先测低档；0.1 QPS/20 请求约有 200 秒的计划窗口，另有预热、排空和清理。资源采样预留 600 秒，若实际拖得更久需延长覆盖，不把未采到的时段当作零资源：

```bash
export EVAL_TELEMETRY_REDIS_URL="$REDIS_URL"
ps -p "$API_PID" -o pid,args
python -m aiagent.evaluation.telemetry --pid "$API_PID" \
  --seconds 600 --interval 1 --redis --output "$ROUND/resources-0.1qps.jsonl" &
export TELEMETRY_PID=$!

python -m aiagent.evaluation.load \
  --rate 0.1 --total 20 --workers 2 --queue 10 --users 20 \
  --timeout 120 --slo-ms 30000 --warmup 2 \
  --text '你的音之精灵叫什么？请只回复名字。' --required '释天' \
  --minimum-pass-rate 0.95 --output "$ROUND/load-0.1qps.json"

wait "$TELEMETRY_PID"
```

确认费用与上一档稳定后再测 0.2、0.5、1、2 QPS。每档独立报告、重新启动覆盖完整窗口的采样，不做无条件升压循环。0.5 档示例参数为 total=100/workers=8/queue=40/users=50；长窗口可用 rate=1/total=1200/workers=20/queue=100/users=100，并为预热/排空另留时间。成功样本不到 1000 时，P99 只作小样本观察，不能承诺稳定尾延迟。

| 必须同时看 | 防止误读 |
| --- | --- |
| sent_qps、completed_qps、http_2xx_qps | 计划 QPS 不等于实际发送/成功吞吐，completed 可包含非 2xx |
| rule_goodput_qps、rule_slo_pass_rate | 仅规则正确且满足 SLO，不是完整语义正确率；分母含计划但丢弃的请求 |
| successful_http_latency_ms.p95/p99 | 成功 HTTP 的尾延迟，不是所有请求的尾延迟；单位 ms |
| timeout_n、states、attempt_elapsed_ms_censored | 单独报告失败/排队/超时，不能将超时截止值伪装为完整完成时延 |
| cleanup_failures、CPU/RSS、Redis 内存/连接 | 质量、清理与资源一起判断，不只看吞吐 |

P95/P99 也可叫 Q95/Q99。功能评测 CLI 的 elapsed_ms 包含评分与 Judge，不用于宣称服务端回答 P95；当前没有 TTFT、SSE token 速率、真实 semantic_goodput 或 server_admitted_qps，不补造数字。

第 6 步关闭限流是隔离功能诊断设置。正式容量还需按目标部署恢复 RATE_LIMIT_ENABLED/INFLIGHT_LIMIT_ENABLED、相同模型配额与 SLO 后**重启服务并另测**，不能用关闭保护的吞吐冒充生产容量。单 worker 采样不等于多 worker/容器/Qdrant/GPU/外部模型服务总资源。

## 11. 归档、验收与安全收尾

每项报告包含 report.json、failures.jsonl、summary.md。汇总不能简单相加 smoke、完整回归、release-suite 和 repeat 的条数，它们大量重叠。

```bash
find "$ROUND" -name report.json -print
find "$ROUND" -name summary.md -print
uv pip freeze > "$ROUND/python-packages.txt"
git rev-parse HEAD > "$ROUND/source-commit.txt"
git status --short > "$ROUND/source-status.txt"
sha256sum "$DS/manifest.json" "$DS/corpus-manifest.json" "$DS/judge-gold-kinds.json" \
  > "$ROUND/dataset-hashes.txt"
```

发布结论至少包含：代码提交/实际源码摘要与脏状态、数据和标注摘要、容器 digest、模型/Judge 版本、配置条件、分组样本与适用数量、错误/质量失败分类、调用/token/实际账单费用、性能/资源和仍未验收项目。不导出整个 env，以免泄露 Key；日志和 .judge-debug 均按敏感本地材料管理。

最终检查：

- [ ] 四组件的适用质量门槛、真实业务状态和关键安全断言满足。
- [ ] Judge 异常、执行异常与质量失败分开报告，人工抽审完成。
- [ ] Memory 禁用、编辑、置顶、跨会话、删除、隔离与 cleanup 已验证。
- [ ] Vision 粗粒度标注已审定；未覆盖身份/OCR/图记忆/Voice 等边界明确。
- [ ] 对照收益与回归风险有证据，heldout 没有用于调参。
- [ ] 目标部署保护配置下负载与资源达到约定 SLO，费用可接受。
- [ ] 原始失败、新运行和候选/接受基线均保留，不覆盖或挑选性隐去。

只在同一会话、核实进程/容器确实属于本轮之后停止；新终端不要直接使用旧 PID：

```bash
ps -p "$API_PID" -o pid,args
docker inspect --format '{{.Name}} {{.State.Status}}' "$REDIS_NAME" "$QDRANT_NAME"
# 人工核实上面均为本轮对象后，再执行下面三条。
kill "$API_PID"
docker stop "$REDIS_NAME" "$QDRANT_NAME"
export OPENAI_API_KEY= SILICONFLOW_API=
unset EVAL_JUDGE_API_KEY EVAL_VISION_PROVIDER_KEY
```

保留报告与本轮独立数据卷，不执行全局删除、生产清理或默认销毁数据。当前 cleanup 不承诺清除所有 Mem0 内部历史、图片和资源，隔离实例与工作区才是最终边界。

清空进程 Key 不会删除私有 `.env` 或 profile。需要禁止文件回退时使用显式空变量，而不是只 unset 后仍保留真实 Provider。新终端也须重新判断离线/真实配置，不复用旧 PID。

<a id="new-wsl-workspace"></a>

## 附录 A：仅在新建 WSL 副本时执行

**现有副本继续评测不执行本附录。** 已创建副本使用第 1 步恢复；准备脚本每次创建唯一新目录，不是恢复工具，也不是同步工具。以下命令仅供用户审阅执行，本次文档整合未执行安装、创建环境或预检。

新环境采用 WSL Ubuntu 24.04、Bash、Python 3.12。先核对已有工具，确有缺失时才安装系统包；不要在共享发行版无故升级系统。Ubuntu 24.04 的依赖检查使用 `libglib2.0-0t64`：

```bash
sudo apt-get update
sudo apt-get install -y python3-venv pipx git rsync curl jq ffmpeg libgl1 libglib2.0-0t64 libgomp1 libportaudio2
command -v uv || pipx install uv
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

确认 `/mnt/f/aiagent` 是本次来源且包含修复后的代码、r3 冻结集。准备脚本复制当前工作树而非仅 Git HEAD，排除源 `.git`、Windows venv、私密 env、模型、运行状态、前端和 GPU 服务；只复制冻结集、公开知识语料和 `yzl` Persona：

```bash
bash /mnt/f/aiagent/scripts/setup_project_eval_wsl.sh
# 等脚本成功完成，将实际输出路径输入下一行，不照抄旧副本路径。
read -rp 'PREPARATION_COMPLETE 对应的新副本绝对路径: ' NEW_WORKSPACE
source "$NEW_WORKSPACE/.eval-session.sh"
python -V
```

准备脚本会建立独立 Git 快照和 `.eval-session.sh`，按 `uv.lock` 安装 dev 依赖及 psutil，记录代码、数据哈希和依赖清单；不运行评测、pytest、模型或业务 API。锁安装失败先停止，不去掉 `--locked`。Linux 使用锁内 CPU torch，不复制或调用 Windows `.venv`。创建前确认源码和冻结资料仍符合当前评测版本。新副本 source 成功后已恢复自己的路径，不再执行第 1 步中硬编码旧副本的 cd/source；只继续建立新的 `ROUND_ID/ROUND`，再进入第 2 步。

Docker Desktop 连接按[附录 B](#wsl-docker)检查；**仅新副本首次预检**可运行：

```bash
bash "$WORKSPACE/scripts/check_project_eval_wsl_environment.sh" "$WORKSPACE"
```

该脚本核对输入、编译/模块导入和 Docker 版本，不执行质量评测。报告有独占写入限制；不要在现有副本上为“恢复环境”重跑并覆盖旧日志。后续重新审计先按第 1 步建立新的 `ROUND`，确认下面输出尚不存在，再执行：

```bash
python scripts/audit_project_eval_data.py \
  --dataset-dir "$DS" --source-root "$SOURCE" --adapters \
  --output "$ROUND/data-audit-recheck.json"
```

新副本默认没有真实凭据。完成第 2 步离线后，按第 3.2 节生成私有模型 profile，再做第 3.3 节的 Judge 配置；不要把生产管理员或数据库凭据全量复制过去。

如确实需要根据变更后的来源重新构造数据，另选唯一目录，不能覆盖 r3；此命令不调用模型，但输出版本和哈希会改变，后续须审定 gold 并使用新路径，不能混作同一基线：

```bash
python scripts/build_project_agent_eval_dataset.py \
  --data "$SOURCE/data" \
  --output "$WORKSPACE/data/evaluation/project-rebuilt-$(date -u +%Y%m%dT%H%M%SZ)-$$"
```

<a id="wsl-records"></a>

## 附录 B：现有环境与历史证据

本表保留 2026-10-26 环境创建记录及 2026-10-27 配置更新，不表示此次整合重新验证了系统或 Docker 的实时状态。

| 项目 | 已记录状态 |
| --- | --- |
| WSL 发行版 / 用户 | `sp3-build` / `root`，Ubuntu 24.04 |
| 副本 | `/root/aiagent-eval/20261026T091836Z-i4Fyhq` |
| 来源 | Windows `F:\aiagent`，WSL `/mnt/f/aiagent` |
| Linux venv | Python `3.12.15`，PyTorch `2.14.1+cpu`，按锁装 dev，另装 `psutil==7.2.2` |
| 数据 | `data/evaluation/project-20261026-r3/`，冻结语料、图片与 Persona |
| 创建时预检 | 数据/输入检查、语法及 `cli/load/telemetry` 导入通过 |
| 2026-10-27 配置 | 私有 `.env` 与 `.env.eval-models.sh` 权限 600；CLIP `/mnt/f/...` 资产可访问 |
| 历史验证 | 164 项修复回归、203 项 Judge v2 回归、103 项配置回归是不同范围，不相加计数 |

原 `Ubuntu-24.04` 注册项因缺少 `ext4.vhdx` 无法启动，用户选择现有 `sp3-build`；没有注销、重装原发行版或停止其他发行版。WSL 可能显示 Windows localhost 代理未映射到 NAT 网络的警告，本轮未修改全局代理。依赖安装成功不证明模型端点可达，WSL 的 `127.0.0.1` 也不能无条件视为 Windows 宿主机。

<a id="wsl-docker"></a>

### Docker 桥接

创建时 Docker Desktop Linux 引擎经 `docker.exe` 可访问，`sp3-build` 未启用原生 WSL 集成。恢复脚本在原生 Docker 不可用时提供 Bash `docker` 函数桥接。若当前会话已配置真实 Key，不为恢复函数重新 source 离线脚本；可单独定义桥接：

```bash
if ! command docker version >/dev/null 2>&1 && command -v docker.exe >/dev/null 2>&1; then
    docker() { command docker.exe "$@"; }
    export -f docker
fi
docker version
type docker
```

Windows 重启后引擎未启动时，由用户在 PowerShell 启动并核对；本轮不代执行：

```powershell
docker.exe desktop start
docker.exe version
```

无需另装第二套 daemon。本文用命名卷，不将 `/root/...` bind mount 直接传给 Windows 客户端；需要 Linux 目录挂载时先启用并验证 Docker Desktop WSL 集成。

### 报告位置与复用边界

WSL 报告根：

```text
/root/aiagent-eval/20261026T091836Z-i4Fyhq/data/cache/reports/project-eval-20261026T091836Z-i4Fyhq
```

环境记录包含 `data-audit-wsl.json`、`data-audit-console.log`、`syntax-preflight.log`、`import-preflight.log`、`docker-version.txt`、`python-packages.txt`、`source-commit.txt`、`dataset-hashes.txt`、`environment-setup.json`。空语法日志表示当时没有编译报错；它不是质量报告。

Windows 完成记录为 `F:\aiagent\data\cache\evaluation-environments\20261026T091836Z-i4Fyhq-ready.json`。原始 `data-audit-final.json` 保留修复前历史，不覆盖成“无告警”；后续诊断写独立目录。具体运行 ID、根因及原始报告位置见[历史记录](evaluation-history.md)。

PowerShell 打开既有副本：

```powershell
explorer.exe '\\wsl.localhost\sp3-build\root\aiagent-eval\20261026T091836Z-i4Fyhq'
```

测试和恢复脚本的源码仍保留，不因合并文档而删除。已有环境无需重建；重新打开 shell 后须核实进程、模型、隔离 Redis/Qdrant 及报告标签，不直接复用上次 `API_PID`。

阅读索引统一见[评测导航](README.md)，不在本文重复维护另一份目录。
