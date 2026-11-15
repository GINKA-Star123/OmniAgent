# AIAgent

AIAgent 是一个面向 AI VTuber / 角色陪伴场景的统一运行时：对话、长期记忆、RAG 知识检索、视觉理解、
语音输入、TTS 输出、账号与多用户隔离、运行时遥测、执行状态一致性，以及多端控制台
（HTTP API、Flutter 手机端、Qt 桌面端）都放在同一个工程里。

- **后端**：FastAPI + LangGraph 图流程；默认 mock provider 即可跑通主链路。
- **账号体系**：Bearer token（静态映射 / 注册 / 登录 / 游客），按主体做资源隔离。
- **手机端**：Flutter，当前 `1.3.0+1`，支持激活码一键完成「地址 + 令牌 + 身份」配置。
- **桌面端**：PySide6 + Qt Quick(QML)，可打包成 Windows exe（绿色目录 / 单文件）。
- **评测**：`aiagent/evaluation/` 四层评测 CLI + CI 离线质量门禁，结论与边界见[评测导航](docs/quality/README.md)。
- **Live2D 表现层当前暂停**：两个客户端都不再渲染模型；后端 payload 协议与 `integrations/live2d/`
  原样保留未删除，恢复方式见文末「Live2D 现状」。

## 当前状态

| 项 | 状态 |
| --- | --- |
| 后端版本线 | V1.1 已收口；V1.2 批次 1-4 有交付记录，批次 5-10 已有计划与修订文档但按评测导航“暂不推进”；仓库提交已进入 V1.5 迭代（鉴权与多用户隔离、遥测、记忆写入约束、视觉 GIF 抽帧） |
| 鉴权 | `API_AUTH_MODE` 默认 `bearer`；公开 / 用户态 / 管理态三层策略在 `apps/api/user_auth.py` 统一定义 |
| 手机端 | `1.3.0+1`，文本 / 图片 / 录音 / ASR / TTS / 记忆 / 设置闭环 |
| 桌面端 | QML 版已重写并通过自检；打包脚本就绪（首次打包需先装 MSVC C++ 组件）；**尚未接入 Bearer 鉴权** |
| 自动化 | GitHub Actions `Backend` 工作流：锁文件校验、依赖漂移检查、ruff、分层 pytest、离线质量门禁、镜像构建与容器自检 |
| 验证口径 | 首页不维护易过期的用例收集数；具体结论、预算与运行记录见[评测导航](docs/quality/README.md)与[历史记录](docs/quality/evaluation-history.md) |

## 项目结构

~~~text
aiagent/              核心智能体：图流程、状态、记忆、知识库、语音、视觉、评测
  evaluation/         四层评测 CLI（数据契约、打分、Judge、报告）
apps/api/             FastAPI 服务：路由、鉴权策略、响应与中间件
apps/core/            Runtime 构建与本地命令行入口
apps/desktop_qt/      Qt 桌面端（PySide6 + QML）              <- 被 .gitignore 忽略
apps/flutter_client/  Flutter 手机端                           <- 被 .gitignore 忽略
apps/worker/          云端异步任务 worker
cloud/                云模式配置、限流、并发租约、任务队列、对象存储、GPU client
config/               统一配置、默认值、Provider 与 personas 模板
integrations/         LLM / ASR / TTS / Live2D / 音频等外部集成
data/                 本地运行资产（凭据、遥测、模型、缓存、知识库、日志）
deploy/               Dockerfile、docker-compose（腾讯云整栈 + 本地基础服务）、nginx
docs/                 文档导航、配置、观测性、评测、版本规划、安全
gpu_services/         GPU 服务草稿与占位目录
scripts/              测试、门禁、部署、评测数据与资源工具
tests/                Python 单元 / 契约 / 冒烟 / RAG 质量测试
.github/workflows/    CI：backend.yml
~~~

版本管理现状（根 `.gitignore`）：`apps/desktop_qt/` 与 `apps/flutter_client/` 被忽略；
`scripts/`、`docs/`、`tests/`、`deploy/`、`config/` 已入库；`data/` 下除
`data/characters/README.md` 外按子目录忽略（`data/persona/`、`data/models/`、`data/cache/`、
`data/uploads/`、`data/knowledge/`、`data/live2d/`）。运行期凭据与遥测数据的处置见「数据与资源」。

## 能力概览

- **文本 / 多模态对话**：`POST /chat`、`POST /chat/multimodal`，回复可带语音与情绪字段
- **语音**：转写 `/voice/transcribe`、语音回合 `/voice/turn`、实时通话 `/voice/realtime/*`（Redis 共享状态）
- **TTS 输出**：GPT-SoVITS / IndexTTS2 / VoxCPM，客户端播放
- **长期记忆**：Mem0 + Qdrant（可选 Neo4j 图谱），支持读取、搜索、固定、删除、清空与写入审计
- **RAG 知识检索**：文档切块、混合检索（向量 + BM25）、重建索引、新鲜度检查
- **视觉理解**：图片分析、角色图库索引、GIF 有界抽帧、视觉上下文进入对话
- **账号与隔离**：注册 / 登录 / 游客 token、邀请码、TTL 管理；请求主体与 `user_id` / `call_id` 强绑定
- **遥测**：客户端批量上报（幂等）+ 汇总查询，按日期落 JSONL
- **执行状态一致性**：会话短期上下文与线程归属跨 Worker 共享（V1.2 第 2 批），清理对所有 Worker 生效
- **可观测性**：`request_id`、阶段耗时、统一错误结构、运行时诊断、能力注册表、就绪性检查
- **评测**：四层评测 CLI、离线质量门禁、评测历史与边界记录
- **多端入口**：HTTP API、Flutter 手机端、Qt 桌面端；Web 控制台不在工作区（另有运维只读页 `/dashboard`）

## 环境要求

- **Python 3.11+**（仓库 `.python-version` 为 3.12）；桌面端使用 PySide6 6.8.2，其
  `Requires-Python` 为 `<3.14,>=3.9`，因此**桌面端必须用 3.12/3.13**（本项目 venv 为 3.12.7）。
- **可选服务**：Redis（限流 / 队列 / 通话状态 / 执行状态共享）、Qdrant（长期记忆向量）、
  Neo4j（记忆图谱）、Docker（一键起上述基础服务）。
- **可选工具链**：Flutter SDK（手机端）、MSVC C++ 生成工具 + Nuitka（桌面端打包 exe）。

依赖由 `pyproject.toml` 与 `uv.lock` 管理（venv 由 `uv` 创建，**默认不含 pip**）：

~~~powershell
cd F:\aiagent
uv sync --locked --extra dev
~~~

- `requirements.txt` 是 `uv export --locked --no-dev --no-emit-project` 的**生成物**（含哈希，供镜像构建），
  不要手改；CI 会重导出并校验零漂移。`requirements-cloud.txt` 必须只指向它。
- 安装/更新依赖请用 `uv sync` 或 `uv pip install --python .venv\Scripts\python.exe ...`，不要用裸 `pip`。

## 快速开始

### 1. 起本地基础服务（可选，但推荐）

~~~powershell
# Redis + Qdrant + Neo4j（只绑定 127.0.0.1；Postgres 为预留，需 --profile reserved）
powershell -ExecutionPolicy Bypass -File scripts\dev_services.ps1 -Action up

# 等价原生命令
docker compose -f deploy/docker-compose.services.yml --env-file .env up -d
~~~

脚本会等待端口就绪、打印端点状态，并给出该写进 `.env` 的连接串。详见「本地基础服务（Docker）」。

### 2. 准备配置

~~~powershell
cd F:\aiagent
Copy-Item .env.example .env      # 已存在则不要覆盖
~~~

配置含义以[配置参考](docs/config-reference.md)、源码与 `.env.example` 为准；私有 `.env` 不提交。
最小开发配置可以保持 mock：

~~~env
LLM_PROVIDER=mock
ENABLE_MOCK_LLM=true
TTS_PROVIDER=mock
ENABLE_MOCK_TTS=true
ASR_PROVIDER=mock
ENABLE_MOCK_ASR=true
~~~

> `*_API_KEY_ENV` 有两种取值形式：填**环境变量名**（该变量必须存在于进程环境，本项目没有
> `load_dotenv`，只写在 `.env` 里不会进入 `os.environ`），或**直接填密钥本身**（纯 `.env`
> 工作流下唯一能直接生效的形式）。完整说明见两份 env 文件文件头。

### 3. 配置鉴权（默认必填，否则后端起不来）

`API_AUTH_MODE` 默认 `bearer`，且要求至少一个凭据来源，否则启动校验直接失败
（`api_auth_configuration_invalid`）。三种可用方式，任选其一：

~~~env
# 方式 A：本地开发模式（最简单；生产/云模式会拒绝启动）
API_AUTH_MODE=local-dev
API_LOCAL_PRINCIPAL=local-user

# 方式 B：静态 token 映射（sha256( token ) -> user_id，JSON 字符串）
API_AUTH_MODE=bearer
API_AUTH_TOKEN_SHA256_MAP={"<sha256-hex>":"user-001"}

# 方式 C：开放游客/注册（内测期；正式环境建议关闭并配合邀请码）
API_AUTH_MODE=bearer
AUTH_GUEST_ENABLED=true
AUTH_REGISTRATION_ENABLED=false
AUTH_INVITE_CODE=
~~~

方式 B 的 token 与映射建议直接用脚本生成（产物落在 `data/private/activation/`，**不要提交**）：

~~~powershell
.\.venv\Scripts\python.exe scripts\gen_activation_codes.py --count 1 --base-urls http://127.0.0.1:8000
# 产物：activation_codes.csv / token_map.json / tokens.txt
# 把 token_map.json 的内容整体填进 API_AUTH_TOKEN_SHA256_MAP 即可
~~~

其他启动校验（报错即改）：

| 报错 | 含义与处理 |
| --- | --- |
| `api_auth_configuration_invalid` | bearer 模式没有任何凭据：填静态映射，或开启注册/游客 |
| `multiuser_http_requires_client_audio_playback` | bearer 模式下必须 `ENABLE_LOCAL_AUDIO_PLAYBACK=false`（音频由客户端播） |
| `local_dev_auth_forbidden_in_production` | `CLOUD_MODE=true` 或 `APP_ENV=production` 时不能用 `local-dev` |
| `production_private_resources_require_redis` | 生产要求 `EXECUTION_STATE_MODE=redis` |
| `production_voice_call_store_requires_fail_closed_redis` | 生产要求通话状态用 Redis 且 `VOICE_CALL_STORE_FAIL_OPEN=false` |

> 本地没有 Redis 时，把 `EXECUTION_STATE_MODE` 设成 `local`（`.env.example` 默认给的是 `redis`）。
> 需要运维接口（`/dashboard`、`/cloud/*`、`/knowledge/*`、`/telemetry/summary` 等）时，另外设置
> `CLOUD_ADMIN_TOKEN`，请求带 `x-cloud-admin-token` 或 `x-admin-token` 头。

### 4. 启动后端

~~~powershell
cd F:\aiagent
.\.venv\Scripts\python.exe -m uvicorn apps.api.http_server:app --host 0.0.0.0 --port 8000 --reload
~~~

~~~powershell
# 公开端点
Invoke-RestMethod http://127.0.0.1:8000/health

# 用户态端点：必须带 Bearer，且 body 里的 user_id 必须等于 token 所属主体
$token = "<上一步生成的 token>"
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:8000/auth/me -Headers $headers
Invoke-RestMethod http://127.0.0.1:8000/chat -Method Post -Headers $headers -ContentType 'application/json' -Body '{"user_id":"user-001","username":"tester","text":"你好"}'

# 游客令牌（AUTH_GUEST_ENABLED=true 时）
Invoke-RestMethod http://127.0.0.1:8000/auth/guest -Method Post -ContentType 'application/json' -Body '{"device_id":"demo-device"}'
~~~

交互式接口文档：`http://127.0.0.1:8000/docs`（FastAPI Swagger UI）。
API 入口是 [apps/api/http_server.py](apps/api/http_server.py)，鉴权策略在 [apps/api/user_auth.py](apps/api/user_auth.py)，
运行时构建入口是 [apps/core/bootstrap.py](apps/core/bootstrap.py)。

### 5. 启动客户端

~~~powershell
# 桌面端（PySide6 + QML，启动约 1-3 秒）
.\.venv\Scripts\python.exe -m apps.desktop_qt.main

# 手机端
cd F:\aiagent\apps\flutter_client
flutter pub get
flutter run
~~~

> 桌面端当前**未接 Bearer 鉴权**：对接默认 `bearer` 后端会收到 401。本地联调请让后端以
> `API_AUTH_MODE=local-dev` 运行；正式使用前需在桌面端补 token 配置（后续项）。

## 账号与鉴权

- **模式**：`API_AUTH_MODE=bearer`（默认）或 `local-dev`（仅开发，生产拒绝）。
- **令牌**：43-256 位 `[A-Za-z0-9_-]`；静态配置里存的是 **sha256 摘要**，明文 token 只交给客户端。
- **动态账号**：`POST /auth/register`（邀请码 `AUTH_INVITE_CODE`）、`POST /auth/login`、
  `POST /auth/guest`；token 与用户记录存 `AUTH_STORE_PATH`（默认 `data/auth/auth_store.json`），
  有效期 `AUTH_TOKEN_TTL_HOURS`（默认 720h），游客 `AUTH_GUEST_TOKEN_TTL_HOURS`（默认 168h）。
- **三层访问策略**（见 `apps/api/user_auth.py`）：

| 层 | 判定 | 代表性端点 |
| --- | --- | --- |
| 公开 | 无需凭据 | `GET /`、`/live`、`/health`、`/ready`、`POST /auth/register`、`/auth/login`、`/auth/guest` |
| 用户态 | Bearer token，且主体要与 `user_id` / `call_id` 一致（不一致 403 `principal_mismatch`） | `/chat`、`/session/open`、`/voice/*`、`/vision/analyze`、`/vision/chat`、`/memory/user/{user_id}*`、`/telemetry/batch`、`/auth/me` |
| 管理态 | `x-cloud-admin-token` 或 `x-admin-token`（**未列入用户面的路径默认走这里**） | `/dashboard*`、`/cloud/*`、`/knowledge/*`、`/vision/characters/*`、`/live2d/*`、`/cloud-files/*`、`/telemetry/summary`、`/control/*` |

- **激活码**：`scripts/gen_activation_codes.py` 生成 `base64url(JSON{v,b,ba,t,u,n})`，手机端一次粘贴即可
  同时得到「服务地址 + 令牌 + 身份」；激活码与 token 映射同源，便于内测分发。
  产物默认在 `data/private/activation/`，**属于凭据，不要提交**。

## 本地基础服务（Docker）

`deploy/docker-compose.services.yml` 只包含后端依赖的基础服务，不含 api / worker 容器，
适合「服务在 Docker、后端在 venv」的本地开发方式。

| 服务 | 端口（仅 127.0.0.1） | 用途 |
| --- | --- | --- |
| Redis | 6379 | 限流、并发租约、任务队列、通话状态、跨 Worker 执行状态 |
| Qdrant | 6333 / 6334 | 长期记忆向量库 |
| Neo4j | 7474 / 7687 | 记忆图谱（`MEMORY_ENABLE_GRAPH=true` 时才使用） |
| Postgres | 5432 | 预留（`--profile reserved`；当前 Python 代码不依赖） |

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts\dev_services.ps1 -Action status   # 容器状态 + 端口探活
powershell -ExecutionPolicy Bypass -File scripts\dev_services.ps1 -Action logs     # 实时日志
powershell -ExecutionPolicy Bypass -File scripts\dev_services.ps1 -Action down     # 停止（保留数据）
powershell -ExecutionPolicy Bypass -File scripts\dev_services.ps1 -Action reset    # 停止并删数据卷
~~~

- 与 `deploy/docker-compose.tencent.yml`（整栈部署）互不冲突：项目名与数据卷都不同，但不要混用数据。
- Neo4j 密码取 `.env` 的 `NEO4J_PASSWORD`，脚本显式 `--env-file .env`，保证容器与后端读同一份密码。
- Redis 不可用时按既定策略降级（限流放行、执行状态退化并暴露 degraded），状态在
  `/runtime/capabilities` 与 `/cloud/ops/readiness` 可见。

## 桌面端（Qt / QML）

~~~powershell
# 运行（两种写法都可用）
.\.venv\Scripts\python.exe -m apps.desktop_qt.main
.\.venv\Scripts\python.exe apps\desktop_qt\main.py

# 自检（Python 层 / QML 层 / 桥接链路，离屏运行不弹窗）
.\.venv\Scripts\python.exe -m apps.desktop_qt.tools.smoke_check
~~~

- 功能：聊天（气泡流 / Enter 发送 / Shift+Enter 换行）、语音播报、长期记忆浏览与删除、运行诊断、设置页。
- 配置文件：源码运行在 `apps/desktop_qt/runtime/config.json`；打包后在 **exe 同目录**（绿色便携）。
- 样式入口：颜色 / 圆角 / 间距 / 字号集中在 `apps/desktop_qt/bridge/theme_bridge.py`，
  QML 侧统一引用 `Theme.palette.xxx`。
- 打包 exe（首次需先装 MSVC 组件 `Microsoft.VisualStudio.Component.VC.Tools.x86.x64` 与 Nuitka）：

~~~powershell
uv pip install --python .venv\Scripts\python.exe nuitka ordered-set
powershell -ExecutionPolicy Bypass -File apps\desktop_qt\packaging\build.ps1                 # 绿色目录
powershell -ExecutionPolicy Bypass -File apps\desktop_qt\packaging\build.ps1 -Mode onefile  # 单文件
~~~

细节与故障排查见 [apps/desktop_qt/README.md](apps/desktop_qt/README.md)。

## Flutter 手机端

~~~powershell
cd F:\aiagent\apps\flutter_client
flutter pub get
flutter run
~~~

- 真机调试时 API 地址填电脑的**局域网 IP**（例如 `http://192.168.x.x:8000`），不要填 `127.0.0.1`。
- 配置可用**激活码**一次性导入（服务地址 + 令牌 + 身份）；出码与三终端（后端 / Cloudflare 隧道 / 出码）
  联调流程见[三终端启动手册](docs/mobile-3-terminal-startup.md)与[移动端测试手册](docs/mobile-backend-test-playbook.md)。
- RC 检查命令：`dart format lib test` → `flutter analyze` → `flutter test` → `flutter build apk --release`。
- Android release 读取 `apps/flutter_client/android/key.properties`；没有 release keystore 时 fallback
  debug signing，只适合内测安装。

## Web 控制台

当前工作区没有 `apps/web` 目录。早期文档里的 Next.js 控制台不属于当前可运行代码。
仓库内另有一个运维向只读页面：`GET /dashboard`（需 admin token）。

## API 速览

按访问层分组，完整签名与参数以运行中的 `/docs` 为准。

账号与遥测：

| 路径 | 层 | 用途 |
| --- | --- | --- |
| `POST /auth/register` / `login` / `guest` | 公开 | 注册（邀请码）/ 登录 / 游客签发 |
| `GET /auth/me` | 用户 | 当前主体 |
| `POST /telemetry/batch` | 用户 | 批量上报（≤200 条，`batch_id` 幂等） |
| `GET /telemetry/summary` | 管理 | 遥测汇总 |

对话、会话与控制：

| 路径 | 层 | 用途 |
| --- | --- | --- |
| `POST /chat` / `POST /chat/multimodal` | 用户 | 文本 / 图片 + 文本 |
| `POST /session/open` | 用户 | 开场与 presence 初始化 |
| `POST /control/input` / `pause` / `resume` / `reset-context` / `interrupt`，`GET /control/status` | 管理 | 运行时控制 |

语音：

| 路径 | 层 | 用途 |
| --- | --- | --- |
| `POST /voice/transcribe` / `turn` / `interrupt`，`GET /voice/state` | 用户 | 转写 / 语音回合 / 打断 / 状态 |
| `POST /voice/realtime/start` / `end` / `turn` / `interrupt`，`GET /voice/realtime/state/{call_id}` | 用户 | 实时通话（状态存 Redis） |

记忆 / 知识 / 视觉：

| 路径 | 层 | 用途 |
| --- | --- | --- |
| `GET /memory/user/{user_id}` / `snapshot` / `stats` / `search` / `audit` / `layers/{layer}` / `preferences`（`PUT`） | 用户 | 读取、分层、偏好、审计 |
| `DELETE /memory/user/{user_id}` / `memories/{memory_id}` / `layers/{layer}`，`POST` 或 `DELETE` `/memory/user/{user_id}/memories/{memory_id}/pin`，`POST /memory/user/{user_id}/merge` | 用户 | 删除、固定、合并 |
| `GET /knowledge/stats` / `rebuild/status` / `index/freshness`，`POST /knowledge/search` / `rebuild` | 管理 | RAG 状态、检索与重建 |
| `POST /vision/analyze` / `chat`，`GET /vision/schema` | 用户 | 视觉分析与输入约定 |
| `POST /vision/characters/rebuild`，`GET /vision/characters/stats` | 管理 | 角色图库索引 |

运行时、云端与媒体：

| 路径 | 层 | 用途 |
| --- | --- | --- |
| `GET /runtime/diagnostics` / `runtime/capabilities` | 管理 | 运行时诊断与能力注册表 |
| `GET /dashboard` / `dashboard/api/snapshot` | 管理 | 运维面板 |
| `GET /cloud/tasks`（`dead` / `summary` / `/cloud/tasks/{task_id}`），`POST /cloud/tasks/...` | 管理 | 异步任务与重建任务 |
| `GET /cloud/ready` / `limits` / `ops/readiness` / `ops/config-snapshot` | 管理 | 云端就绪与运维快照 |
| `GET /cloud/gpu/health` / `POST /cloud/gpu/llm-smoke` | 管理 | GPU 服务健康与连通性 |
| `POST /cloud/storage/upload` / `presign-upload`，`GET /cloud-files/{key}` | 管理 | 对象存储上传与私有文件读取（local provider） |
| `GET /audio/{filename}` | 用户 | TTS 音频文件 |

请求追踪、`request_id` 与统一错误结构见 [docs/api-observability.md](docs/api-observability.md)；
Live2D 端点（`/live2d/*`）保留可用，但当前不在使用。

## 评测

评测代码在 `aiagent/evaluation/`（数据契约、打分、Judge、报告），当前结论与边界以
[评测导航](docs/quality/README.md)为准，**不要从本页复制历史分数**。

~~~powershell
# 四层评测 CLI（数据集、分层与输出目录按 runbook 指定）
.\.venv\Scripts\python.exe -m aiagent.evaluation.cli --dataset <dataset.json> --split <split> --output <dir>

# CI 同款离线质量门禁
.\.venv\Scripts\python.exe -m aiagent.knowledge.evaluation.agent_quality --mode offline
~~~

- 执行流程：[评测总流程](docs/quality/project-evaluation-workflow.md)；Windows 复现步骤见
  [Windows runbook](docs/quality/project-evaluation-windows-runbook.md)。
- 数据准备与审计：`scripts/build_project_agent_eval_dataset.py`、`scripts/audit_project_eval_data.py`、
  `scripts/build_adjudicated_regression.py`、`scripts/calibrate_evaluation_*.py`。
- 人设与对白演绎回归：[人设与对白演绎](docs/quality/yzl-persona-performance.md)；安全边界见
  [威胁模型](docs/security/threat-model-v1.2.md)。

## 自检与门禁

| 命令 | 作用 |
| --- | --- |
| `uv lock --check` / `uv sync --locked --extra dev` | 锁文件一致性与环境同步 |
| `uv run --locked python scripts/check_dependency_runtime.py` | 依赖可导入与运行期能力 |
| `uv run --locked python scripts/check_config_sync.py` | 配置三方一致：源码 ↔ `.env.example` ↔ `docs/config-reference.md` |
| `uv run --locked python scripts/check_repo_hygiene.py` | 仓库卫生（忽略规则、临时文件、敏感产物） |
| `uv run --locked ruff check aiagent apps/core apps/api apps/worker cloud config integrations scripts tests` | 静态检查 |
| `uv run --locked python scripts/check_container_runtime.py` | 镜像运行期依赖自检 |
| `.venv\Scripts\python.exe scripts\v1_preflight.py --mode all --env-file .env` | 发布前检查（占位符、mock、真实 provider） |
| `.venv\Scripts\python.exe scripts\v1_2_baseline.py --root . --print` | V1.2 基线快照（测试函数 / 缺陷 / 优化项） |
| `.venv\Scripts\python.exe -m apps.desktop_qt.tools.smoke_check` | 桌面端三阶段自检 |
| `powershell -File scripts\test_runtime_diagnostics.ps1` | 运行时诊断链路 |

CI（`.github/workflows/backend.yml`）：锁文件与 requirements 漂移检查 → ruff → 分层 pytest
（`unit` 与 `api + smoke`，排除 `integration`）→ 离线质量门禁 → 构建 api / worker 镜像 →
容器运行期自检；音频相关用例在 headless PulseAudio 下运行。

## 测试

~~~powershell
cd F:\aiagent
.\.venv\Scripts\python.exe -m pytest -q tests\unit tests\api tests\smoke -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest --collect-only -q tests      # 查看当前环境实际收集数，不执行
.\.venv\Scripts\python.exe -m pytest -q tests\rag -p no:cacheprovider
~~~

- `tests\rag` 依赖 `data\knowledge\public`，本地没有知识库目录时按条件跳过；
  质量基线与阈值见 [RAG 评测](docs/quality/rag-eval.md)。
- 分层标记：`unit` / `api` / `smoke` / `rag` / `integration`（`pytest -m <标记>` 可筛选）。
- 统一入口：`powershell -ExecutionPolicy Bypass -File scripts\test_all.ps1 -ContinueOnFailure`。
- V1.0 收尾记录：[smoke](docs/v1.0/v1-final-smoke.md)、[发布清单](docs/v1.0/v1-release-checklist.md)。

## 数据与资源

`data/` 用于放本地运行资产，按子目录忽略；`data/characters/*` 只保留 README：

~~~text
data/persona/           运行时人格配置（模板见 config/personas/yzl.yaml）
data/characters/        视觉角色图库（大文件）
data/live2d/            Live2D 模型与背景（表现层暂停中，资源保留）
data/models/            本地 ASR / embedding / CLIP 等模型
data/uploads/           API 上传文件缓存
data/cache/             RAG / Vision 等索引缓存与报告
data/knowledge/         本地知识库文档
data/auth/              账号与 token 存储（运行时生成，含凭据）
data/telemetry/         遥测 JSONL（按日期滚动）
data/private/           激活码与 token 映射等分发产物（含凭据）
data/logs/              本地日志
~~~

> **提交前自查**：`data/auth/`、`data/private/`、`data/telemetry/` 属于凭据与用户数据，
> 不应进入版本库；`config/personas/` 下的 YAML 是**版本化模板**，运行时读的是 `data/persona/`。
> 提交前用 `git status` / `scripts/check_repo_hygiene.py` 核对；
> 若发现这些目录里的文件已被跟踪，先 `git rm --cached -r data/auth data/private data/telemetry`
> 再把对应规则加入 `.gitignore`（已提交过的凭据还应轮换）。

## Live2D 现状

- **前端不再渲染 Live2D**：桌面端已移除模型面板，手机端 WebView 舞台也不再是主链路。
- **后端不删除、不影响**：`integrations/live2d/`、`aiagent/live2d/` 与 `/live2d/*` 端点原样保留，
  `scripts/` 下的 Live2D 测试脚本也保留。
- **情绪仍然有用**：`emotion` / `expression` 由客户端以「情绪胶囊」轻量展示，不依赖模型渲染。
- **恢复方式**：后端契约无需改动，客户端重新引入渲染层即可（Qt 可走 QtWebEngine + 现有
  `apps/flutter_client/assets/live2d_web/` 舞台，或原生 `live2d` Python 包 + `QOpenGLWidget`）。

## 已知注意事项

- **鉴权是启动硬门槛**：`bearer` 模式下没有任何凭据、或 `ENABLE_LOCAL_AUDIO_PLAYBACK=true`，
  后端会启动失败；处理方式见「快速开始 3」的报错对照表。
- **主体绑定**：用户态接口要求 body 的 `user_id`（或路径 `user_id` / `call_id`）与 token 主体一致，
  否则返回 403 `principal_mismatch`；管理态接口需要 admin token。
- **PowerShell 读取 UTF-8 中文**偶尔乱码：用 VS Code 查看，或先设置
  `[Console]::OutputEncoding = [Text.Encoding]::UTF8`；含中文的 `.ps1` 必须保存为 **UTF-8 with BOM**。
- **venv 没有 pip**：安装依赖用 `uv sync` / `uv pip install --python .venv\Scripts\python.exe ...`。
- **系统 Python 是 3.14**：PySide6 6.8.2 不支持 3.14，桌面端务必使用项目 venv（3.12.7）。
- **系统代理会拦截本机请求**：Windows 注册表级代理会把 `127.0.0.1` 请求变成 `HTTP 502`；
  桌面端默认忽略系统代理，只有后端确实在代理之后时才在设置页打开开关。
- **requirements.txt 是生成物**：改依赖请改 `pyproject.toml` 并 `uv lock`；CI 会校验导出零漂移。
- `apps/desktop_qt/` 与 `apps/flutter_client/` 被根 `.gitignore` 忽略，改动不会出现在 `git status`。
- RAG / Vision / Memory / TTS / ASR 依赖外部模型或服务；mock 模式能跑通主流程，不代表生产效果。
- Qdrant collection 的 embedding 维度必须与实际模型一致（`RAG_EMBEDDING_DIMENSIONS` /
  `MEMORY_EMBEDDING_DIMS`），维度变化需要重建 collection。
- 没有 release keystore 时 Flutter release 包 fallback debug signing，不能作为正式外发包。
- 多实例部署必须共享执行状态（`REDIS_URL` + `EXECUTION_STATE_MODE=redis`），否则同一用户在不同
  Worker 上会看到两套上下文。

## 参考文档

统一从[项目文档导航](docs/README.md)选择配置、运维、评测或版本资料：

- 配置与运维：[配置参考](docs/config-reference.md)、[API 可观测性](docs/api-observability.md)、
  [执行状态与部署门禁](docs/operations/v1.2-execution-state-and-gates.md)、[仓库治理](docs/repo-governance.md)。
- 评测：[评测导航](docs/quality/README.md)、[评测总流程](docs/quality/project-evaluation-workflow.md)、
  [RAG 评测](docs/quality/rag-eval.md)、[人设与对白演绎](docs/quality/yzl-persona-performance.md)、
  [评测历史](docs/quality/evaluation-history.md)。
- 移动端联调：[三终端启动手册](docs/mobile-3-terminal-startup.md)、
  [移动端测试手册](docs/mobile-backend-test-playbook.md)。
- 安全与版本：[威胁模型](docs/security/threat-model-v1.2.md)、
  [V1.2 十批实施计划](docs/v1.2/v1.2-ten-batch-implementation-plan.md)、
  [V1.2 范围与基线](docs/v1.2/v1.2-scope-and-baseline.md)、
  [V1.0 smoke](docs/v1.0/v1-final-smoke.md)、[V1.0 发布清单](docs/v1.0/v1-release-checklist.md)。

客户端说明位于本机的 `apps/desktop_qt/README.md` 与 `apps/flutter_client/README.md`
（两个目录被 gitignore，克隆仓库后不会出现）。
