# Windows 本地评测运行手册

更新日期：2026-10-28。本文仅提供 Windows PowerShell 命令变体，依赖可使用 Docker Desktop。现状和停止点只在[现状入口](README.md)维护，执行顺序与外部调用许可按[WSL 总流程](project-evaluation-workflow.md)；当前先审阅候选，不自动重跑付费回归，heldout由用户最终验收。

Judge规则、错误码和双通道预算见[实现说明](project-evaluation-implementation.md#judge-protocol)。新实验先逐项进行[Provider smoke](project-evaluation-workflow.md#4-首次-provider-验证9-条-smoke)，不要批量执行本文全量命令。--debug-local仅在接受本地留档边界时开启；复现历史官方DeepSeek条件时显式指定 --judge-thinking disabled --judge-max-output-tokens 4096，其他端点不照搬thinking参数。

推荐数据集为 `F:\aiagent\data\evaluation\project-20261026-r3`。指标和数据限制见[数据集说明](../../data/evaluation/project-20261026-r3/DATASET_CARD.md)，WSL已创建环境见[总流程附录B](project-evaluation-workflow.md#wsl-records)。Windows与WSL是两个不同运行环境，虚拟环境、PID、资源曲线和基线不得混用。模型与密钥规则以[总流程第3步](project-evaluation-workflow.md#model-config)为准；历史DeepSeek配置已有真实图片验证记录；端点、模型或运行条件变化后仍需重新核验图片能力。

## 1. 原项目中的离线验证

本节只运行离线组件与测试，不启动生产Runtime或真实API。使用现有Windows虚拟环境，不覆盖原 `.env`，不重新安装整套依赖。

```powershell
Set-Location -LiteralPath 'F:\aiagent'
$ErrorActionPreference = 'Stop'
$Source = (Get-Location).Path
$Py = Join-Path $Source '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Py)) { throw 'Windows虚拟环境不存在，请先在新隔离副本中安装依赖。' }
$DS = Join-Path $Source 'data\evaluation\project-20261026-r3'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Reports = Join-Path $Source "data\cache\reports\windows-eval-$Stamp"
New-Item -ItemType Directory -Path $Reports | Out-Null

$env:PYTHONUTF8 = '1'
$env:APP_ENV = 'local'
$env:CLOUD_MODE = 'false'
$env:EXECUTION_STATE_MODE = 'local'
$env:LLM_PROVIDER = 'mock'
$env:ENABLE_MOCK_LLM = 'true'
$env:STATE_PROVIDER = 'mock'
$env:ENABLE_MOCK_STATE = 'true'
$env:PLANNER_PROVIDER = 'mock'
$env:ENABLE_MOCK_PLANNER = 'true'
$env:VISION_PROVIDER = 'mock'
$env:TTS_PROVIDER = 'mock'
$env:ENABLE_MOCK_TTS = 'true'
$env:ENABLE_LOCAL_AUDIO_PLAYBACK = 'false'
$env:ASR_PROVIDER = 'mock'
$env:ENABLE_MOCK_ASR = 'true'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
Remove-Item Env:EVAL_RUN_LIVE,Env:EVAL_BASE_URL,Env:EVAL_ISOLATED,Env:EVAL_JUDGE_API_KEY,Env:EVAL_JUDGE_VISION -ErrorAction SilentlyContinue

& $Py -V
& $Py scripts/audit_project_eval_data.py --dataset-dir $DS --source-root $Source --adapters --output (Join-Path $Reports 'data-audit-windows.json')
if ($LASTEXITCODE -ne 0) { throw '数据或输入模型预检失败，先查看错误，不继续付费阶段。' }

& $Py -m compileall -q aiagent/evaluation scripts/build_project_agent_eval_dataset.py scripts/audit_project_eval_data.py tests/unit tests/api/test_evaluation_http_contract.py tests/integration
if ($LASTEXITCODE -ne 0) { throw '语法检查失败。' }
& $Py -c 'import aiagent.evaluation.cli, aiagent.evaluation.load, aiagent.evaluation.telemetry'
if ($LASTEXITCODE -ne 0) { throw '评测依赖导入失败。' }
```

PowerShell的 `$ErrorActionPreference` 不保证原生命令非零退出码会抛异常，所以关键阶段显式检查 `$LASTEXITCODE`。下面每条测试/评测命令也应检查退出码，失败先排查，不要把多条命令放进忽略失败的自动循环。

```powershell
& $Py -m pytest tests/unit/test_evaluation_contracts.py tests/unit/test_evaluation_metrics.py tests/unit/test_evaluation_regression.py tests/unit/test_evaluation_contrast.py tests/unit/test_evaluation_judge_protocol.py -q
& $Py -m pytest tests/api/test_evaluation_http_contract.py -q

& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-all-smoke.json') --output (Join-Path $Reports 'offline-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-all.json') --split dev --output (Join-Path $Reports 'offline-dev')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-all.json') --split regression --output (Join-Path $Reports 'offline-regression')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-trajectory.json') --split adversarial --output (Join-Path $Reports 'offline-refusal')
```

CLI退出码0为当前所选用例全部通过，1为质量/业务断言失败，2为配置、执行或Judge异常。当前源文件修复不意味着这些测试已通过。

## 2. 真实服务前创建Windows隔离副本

真实Memory、图片上传和删除任务必须使用独立副本及独立依赖，**不要直接把第1节所在的原项目进程作为被测服务**。以下只复制，不删除或移动原文件。

```powershell
$Source = 'F:\aiagent'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Work = Join-Path 'F:\aiagent-eval' $Stamp
if (Test-Path -LiteralPath $Work) { throw '隔离目录已存在，请使用新的时间戳。' }
New-Item -ItemType Directory -Path $Work -Force | Out-Null

robocopy $Source $Work /E /R:1 /W:1 /NFL /NDL /NP `
  /XD "$Source\.git" "$Source\.venv" "$Source\data" "$Source\_tmp" "$Source\.pytest_cache" "$Source\.ruff_cache" "$Source\gpu_services" "$Source\third_party" "$Source\apps\flutter_client" "$Source\apps\desktop_qt" `
  /XF '.env' '.env.*' 'cloud*.env'
if ($LASTEXITCODE -ge 8) { throw "副本复制失败：robocopy退出码 $LASTEXITCODE" }
foreach ($Template in @('.env.example','cloud.tencent.example.env')) {
    $TemplatePath = Join-Path $Source $Template
    if (Test-Path -LiteralPath $TemplatePath) { Copy-Item -LiteralPath $TemplatePath -Destination $Work }
}

New-Item -ItemType Directory -Path (Join-Path $Work 'data\evaluation'),(Join-Path $Work 'data\knowledge\public'),(Join-Path $Work 'data\persona') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Source 'data\evaluation\project-20261026-r3') -Destination (Join-Path $Work 'data\evaluation') -Recurse
$DS = Join-Path $Work 'data\evaluation\project-20261026-r3'
Get-ChildItem -LiteralPath (Join-Path $DS 'corpus\public') | Copy-Item -Destination (Join-Path $Work 'data\knowledge\public') -Recurse
Copy-Item -LiteralPath (Join-Path $DS 'persona\yzl') -Destination (Join-Path $Work 'data\persona') -Recurse

Set-Location -LiteralPath $Work
git init -q
git add aiagent apps cloud config integrations scripts tests docs deploy pyproject.toml uv.lock .gitignore
git -c user.name='Local Evaluation Snapshot' -c user.email='eval@example.invalid' commit -q -m 'windows evaluation snapshot'

$env:UV_PROJECT_ENVIRONMENT = Join-Path $Work '.venv'
uv sync --locked --extra dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw '依赖锁安装失败，不自动移除 --locked。' }
$Py = Join-Path $Work '.venv\Scripts\python.exe'
uv pip install --python $Py psutil
$Reports = Join-Path $Work "data\cache\reports\windows-eval-$Stamp"
New-Item -ItemType Directory -Path $Reports -Force | Out-Null
uv pip freeze --python $Py | Set-Content -LiteralPath (Join-Path $Reports 'python-packages.txt') -Encoding utf8
& $Py scripts/audit_project_eval_data.py --dataset-dir $DS --source-root $Source --adapters --output (Join-Path $Reports 'data-audit-windows.json')
```

依赖锁为Linux指定了CPU版torch，Windows使用锁中的Windows发行包；不要据此宣称Windows也安装了Linux CPU wheel。如果不希望额外建立Windows依赖环境，继续使用已经创建好的WSL副本即可，不复制Windows venv到WSL。

## 3. 真实Provider组件评测

下面在第2节的Windows副本中运行。会发送对应资料与合成回答到外部服务，可能计费；先做smoke，再考虑扩大。

```powershell
function Read-EvaluationSecret([string]$Prompt) {
    $SecureValue = Read-Host $Prompt -AsSecureString
    [System.Net.NetworkCredential]::new('', $SecureValue).Password
}

$env:OPENAI_BASE_URL = 'https://api.deepseek.com'
$env:OPENAI_API_KEY = Read-EvaluationSecret '被测API Key'
$env:LLM_MODEL = 'deepseek-flash'
Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
$env:LLM_PROVIDER = 'openai'
$env:ENABLE_MOCK_LLM = 'false'
$env:LLM_TEMPERATURE = '0'
$env:LLM_TIMEOUT_SECONDS = '90'
$env:LLM_MAX_TOKENS = '600'
$env:EVAL_JUDGE_BASE_URL = Read-Host 'Judge base URL（含/v1）'
$env:EVAL_JUDGE_MODEL = Read-Host 'Judge模型名称'
$env:EVAL_JUDGE_API_KEY = Read-EvaluationSecret 'Judge API Key'

& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'provider-rag-smoke.json') --judge provider --allow-provider --output (Join-Path $Reports 'provider-rag-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'provider-rag-fixed-smoke.json') --judge provider --allow-provider --output (Join-Path $Reports 'provider-fixed-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'provider-persona-smoke.json') --judge provider --allow-provider --output (Join-Path $Reports 'provider-persona-smoke')
```

不要输出或持久化环境中的Key；Read-Host只避免明文输入进入命令历史，实际调用仍需明文环境变量，不能把它当作进程内密钥加密。重新进入PowerShell后需重新输入。

## 4. 独立Redis Stack与Qdrant

这些命令只在本机回环端口公开。端口已占用就换本轮评测端口，不停止原服务。Docker Desktop是Windows与WSL共同使用的引擎，不同时启动两套使用相同端口的评测容器。

```powershell
docker.exe desktop start
docker.exe version
$RedisName = "aiagent-eval-win-redis-$Stamp"
$QdrantName = "aiagent-eval-win-qdrant-$Stamp"
$RedisVolume = "aiagent-eval-win-redis-data-$Stamp"
$QdrantVolume = "aiagent-eval-win-qdrant-data-$Stamp"
docker.exe pull redis/redis-stack-server:latest
docker.exe pull qdrant/qdrant:v1.14.1
$RedisDigest = docker.exe image inspect --format '{{index .RepoDigests 0}}' redis/redis-stack-server:latest
$QdrantDigest = docker.exe image inspect --format '{{index .RepoDigests 0}}' qdrant/qdrant:v1.14.1
@($RedisDigest,$QdrantDigest) | Set-Content -LiteralPath (Join-Path $Reports 'container-image-digests.txt') -Encoding utf8

docker.exe run -d --name $RedisName -p '127.0.0.1:16379:6379' --mount "type=volume,source=$RedisVolume,target=/data" $RedisDigest
docker.exe run -d --name $QdrantName -p '127.0.0.1:16333:6333' --mount "type=volume,source=$QdrantVolume,target=/qdrant/storage" $QdrantDigest
docker.exe exec $RedisName redis-cli ping
docker.exe exec $RedisName redis-cli MODULE LIST
Invoke-RestMethod -Uri 'http://127.0.0.1:16333/readyz'
```

确认依赖就绪；普通redis:7不一定具备官方RedisSaver要求的JSON/搜索能力。不执行FLUSHDB/FLUSHALL，不删除任何已有通用集合或数据卷。

## 5. 在隔离副本启动本地Agent服务

继续使用第2、3节的变量与凭据。以下仅为四组件评测启用聊天、规划、Memory及Vision真实模型，语音保持mock。

```powershell
$env:REDIS_URL = 'redis://127.0.0.1:16379/0'
$env:REDIS_PREFIX = "aiagent:eval:win:$Stamp"
$env:EXECUTION_STATE_MODE = 'redis'
$env:EXECUTION_STATE_FAIL_CLOSED = 'true'
$env:QDRANT_HOST = '127.0.0.1'
$env:QDRANT_PORT = '16333'
$env:MEMORY_VECTOR_COLLECTION = "aiagent_eval_win_$($Stamp.Replace('-','_'))"
$env:MEMORY_ENABLE_GRAPH = 'false'
$env:MEMORY_RESET_VECTOR_STORE = 'false'
$env:MEMORY_WRITE_ASYNC_ENABLED = 'false'
$env:MEMORY_LONG_TERM_DEFAULT_ENABLED = 'true'
$env:MEMORY_PREFERENCES_PATH = Join-Path $Work 'data\runtime\eval-memory-preferences.json'
$env:STATE_PROVIDER = 'openai'
$env:STATE_MODEL = $env:LLM_MODEL
$env:ENABLE_MOCK_STATE = 'false'
$env:PLANNER_PROVIDER = 'openai'
$env:PLANNER_MODEL = $env:LLM_MODEL
$env:ENABLE_MOCK_PLANNER = 'false'
$env:MEMORY_LLM_PROVIDER = 'openai'
$env:MEMORY_LLM_MODEL = $env:LLM_MODEL
$env:MEMORY_LLM_API_KEY_ENV = 'OPENAI_API_KEY'
$env:SILICONFLOW_BASE_URL = 'https://api.siliconflow.cn/v1'
$env:SILICONFLOW_API = Read-EvaluationSecret 'SiliconFlow embedding API Key'
$env:MEMORY_EMBEDDER_PROVIDER = 'siliconflow'
$env:MEMORY_EMBEDDER_API_KEY_ENV = 'SILICONFLOW_API'
$env:MEMORY_EMBEDDER_MODEL = 'Qwen/Qwen3-VL-Embedding-8B'
$env:MEMORY_EMBEDDING_DIMS = '4096'
$env:RAG_EMBEDDING_PROVIDER = 'siliconflow'
$env:RAG_EMBEDDING_MODEL_NAME = $env:MEMORY_EMBEDDER_MODEL
$env:RAG_EMBEDDING_API_KEY_ENV = 'SILICONFLOW_API'
$env:RAG_EMBEDDING_BASE_URL = $env:SILICONFLOW_BASE_URL
$env:RAG_EMBEDDING_DIMENSIONS = $env:MEMORY_EMBEDDING_DIMS
$env:RAG_EMBEDDING_DEVICE = 'cpu'
$env:RAG_AUTO_REBUILD_ON_STALE = 'false'
$env:RAG_INDEX_MANIFEST_PATH = Join-Path $Work 'data\cache\knowledge\index_manifest.json'
$env:VISION_BASE_URL = $env:OPENAI_BASE_URL
$env:VISION_MODEL = $env:LLM_MODEL
$env:VISION_PROVIDER = 'openai'
$env:VISION_API_KEY_ENV = 'OPENAI_API_KEY'
$env:VISION_UPLOAD_DIR = Join-Path $Work 'data\uploads\eval-images'
$env:VISION_CHARACTER_ROOT_DIR = Join-Path $DS 'reference-gallery'
$env:VISION_CHARACTER_INDEX_DIR = Join-Path $Work 'data\cache\vision\eval-character-index'
$env:VISION_CHARACTER_EMBEDDING_DEVICE = 'cpu'
$env:VISION_CHARACTER_EMBEDDING_LOCAL_FILES_ONLY = 'false'
Remove-Item Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
$env:APP_ENV = 'local'
$env:CLOUD_MODE = 'false'
$env:API_CORS_ORIGINS = 'http://127.0.0.1:3000,http://localhost:3000'
$env:API_CORS_ALLOW_CREDENTIALS = 'true'
$env:RATE_LIMIT_ENABLED = 'false'
$env:INFLIGHT_LIMIT_ENABLED = 'false'
$env:TTS_PROVIDER = 'mock'
$env:ENABLE_MOCK_TTS = 'true'
$env:ENABLE_LOCAL_AUDIO_PLAYBACK = 'false'
$env:ASR_PROVIDER = 'mock'
$env:ENABLE_MOCK_ASR = 'true'
$env:EVAL_ISOLATED = '1'
$env:EVAL_BASE_URL = 'http://127.0.0.1:18080'
$env:EVAL_SUT_IDENTITY = "windows-eval-$Stamp"
$env:EVAL_CORPUS_SHA256 = (Get-FileHash -LiteralPath (Join-Path $DS 'corpus-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant()

$ApiProcess = Start-Process -FilePath $Py `
  -ArgumentList @('-m','uvicorn','apps.api.http_server:app','--host','127.0.0.1','--port','18080','--workers','1') `
  -WorkingDirectory $Work -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $Reports 'api-stdout.log') `
  -RedirectStandardError (Join-Path $Reports 'api-stderr.log')
$ApiProcess.Id | Set-Content -LiteralPath (Join-Path $Reports 'api-server.pid')

# 等待服务启动后再执行，首次知识库初始化可能较慢且会调用embedding服务。
Invoke-RestMethod -Uri "$env:EVAL_BASE_URL/live"
Invoke-RestMethod -Uri "$env:EVAL_BASE_URL/ready"
Invoke-RestMethod -Uri "$env:EVAL_BASE_URL/knowledge/stats"
Invoke-RestMethod -Uri "$env:EVAL_BASE_URL/knowledge/index/freshness?refresh=true"
```

当前Mem0各子组件需要确认使用正确endpoint，尤其非官方兼容接口；不要假设未知版本一定遵守OPENAI_BASE_URL。查看真实日志、知识统计和freshness，不能只看HTTP200，更不能让NullRAG/NullMemory或mock替代后仍宣称真实质量通过。未包含Neo4j图记忆验证。

<a id="windows-rag-rebuild"></a>

### 5.1 Windows 重建并供 WSL 复用

本节不再维护另一份重建脚本，完整的 PowerShell 构建、WSL 复制、离线校验和替换命令统一在[总流程第 6.3 节](project-evaluation-workflow.md#rag-cache-rebuild)。使用原项目的 Windows venv 构建，然后迁移完整四文件及 transfer_manifest；不要复制 Windows venv 到 Linux。

当前模型的 32 条返回存在重复 index，已改为验证通过的 8 条批量；保留严格响应校验。重建会调用远程 embedding 并计费，seal/verify/install 都是离线操作。原缓存构建完成后替换，旧目录保留为回滚备份。此操作不重建 Qdrant Memory，也不能解决 WSL 后续查询的网络连通性问题。

## 6. 真实API与联合验收

```powershell
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'api-rag-smoke.json') --allow-api --output (Join-Path $Reports 'api-rag-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'api-rag-chat-smoke.json') --allow-api --allow-provider --judge provider --output (Join-Path $Reports 'chat-rag-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'api-memory-smoke.json') --allow-api --allow-provider --judge provider --output (Join-Path $Reports 'memory-smoke')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'runtime-graph.json') --allow-api --allow-provider --judge provider --output (Join-Path $Reports 'runtime-graph')

$env:EVAL_JUDGE_VISION = '1'
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'api-vision-reviewed-smoke.json') --allow-api --allow-provider --judge provider --output (Join-Path $Reports 'vision-smoke')

# 先完成分项与人工抽审，再执行联合验收；Judge必须实际支持图片。
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'release-suite.json') --allow-api --allow-provider --judge provider --release --output (Join-Path $Reports 'release-suite')
```

全量回归将相应 `*-smoke.json` 改为完整数据集并加 `--split regression`；heldout留到配置/gold冻结后，不能拿它调参。重复运行用 `--repeat 3`，但同组重复不算新增独立样本。真实chat未导出注入证据，不报告其faithfulness；未标注身份/OCR不报告对应正式质量基线。

## 7. 对照与性能

```powershell
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-rag.json') --split regression --variant rerank-on --output (Join-Path $Reports 'rerank-on')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'offline-rag.json') --split regression --variant rerank-off --overrides (Join-Path $DS 'offline-rag-contrast-overrides.json') --output (Join-Path $Reports 'rerank-off')

& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'provider-persona.json') --split regression --repeat 3 --allow-provider --judge provider --variant guard-on --output (Join-Path $Reports 'guard-on')
& $Py -m aiagent.evaluation.cli --dataset (Join-Path $DS 'provider-persona.json') --split regression --repeat 3 --allow-provider --judge provider --variant guard-off --overrides (Join-Path $DS 'provider-persona-contrast-overrides.json') --output (Join-Path $Reports 'guard-off')

# 原项目第1节离线执行时没有启动ApiProcess，不能直接跳到以下命令。
# 先确认第5节创建的服务仍在运行，采样的是Windows服务PID。
$env:EVAL_TELEMETRY_REDIS_URL = $env:REDIS_URL
$TelemetryProcess = Start-Process -FilePath $Py `
  -ArgumentList @('-m','aiagent.evaluation.telemetry','--pid',"$($ApiProcess.Id)",'--seconds','400','--interval','1','--redis','--output',"$(Join-Path $Reports 'resources-smoke.jsonl')") `
  -WorkingDirectory $Work -WindowStyle Hidden -PassThru

& $Py -m aiagent.evaluation.load --rate 0.1 --total 20 --workers 2 --queue 10 --users 20 --timeout 120 --slo-ms 30000 --warmup 2 --text '你的音之精灵叫什么？请只回复名字。' --required '释天' --minimum-pass-rate 0.95 --output (Join-Path $Reports 'load-0.1qps.json')
Wait-Process -Id $TelemetryProcess.Id
```

示例使用400秒采样，覆盖低档约200秒计划到达窗口与尾部排空；较大档和长测须另按实际窗口增加时长。当前是单固定问题探针，不是混合业务容量。先低档验证费用和限流，再提升到达率；成功样本不足1000时P99只作观察。

检查 sent/completed QPS、HTTP成功QPS、rule_goodput_qps、rule_slo_pass_rate、超时/丢弃、cleanup_failures、P95/P99及RSS/CPU，规则有效吞吐不等于语义有效吞吐。更详细的指标解释与阶梯设计见[总流程第10步](project-evaluation-workflow.md#10-最后测系统负载与资源)，命令参数在两种系统中一致。

## 8. 重新打开PowerShell与收尾

原项目离线验证可重新执行第1节设置变量，使用新的Reports目录。真实隔离副本则将第2节实际得到的路径填入下方，不重新复制或重建环境：

```powershell
$Work = 'F:\aiagent-eval\替换为实际已创建的目录名'
$Source = 'F:\aiagent'
Set-Location -LiteralPath $Work
$Py = Join-Path $Work '.venv\Scripts\python.exe'
$DS = Join-Path $Work 'data\evaluation\project-20261026-r3'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Reports = Join-Path $Work "data\cache\reports\windows-eval-$Stamp"
New-Item -ItemType Directory -Path $Reports | Out-Null
& $Py -V
```

只设这些路径不会恢复在线配置；接真实服务前重新设置第3至5节所需变量和Key，并确认要连接的是哪一轮隔离实例。不要复用落盘旧PID后直接停止进程，也不要重启使用相同端口的第二个服务。

仍在同一会话，结束本轮时仅停止自己创建的进程和容器：

```powershell
if ($ApiProcess -and -not $ApiProcess.HasExited) { $ApiProcess.Kill() }
docker.exe stop $RedisName $QdrantName
$env:OPENAI_API_KEY = ''
$env:SILICONFLOW_API = ''
Remove-Item Env:EVAL_JUDGE_API_KEY,Env:EVAL_VISION_PROVIDER_KEY -ErrorAction SilentlyContinue
```

保留报告与命名卷，不运行全局清理或递归删除。通过率、基线和性能报告明确标Windows，不与WSL报告直接合并或使用同一个已接受基线强行比较。
