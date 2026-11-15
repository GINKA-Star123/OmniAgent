# 移动端后端测试手册（v1.3）

覆盖：账号体系（注册/登录/游客）、Bearer 鉴权边界、聊天链路、遥测回流与统计、移动端联调。

## 0. 两种身份模式（二选一或共存）

| 模式 | 适用 | 配置 |
| --- | --- | --- |
| 静态激活码 | 50 人内测，身份固定、可追溯 | `API_AUTH_MODE=bearer` + `API_AUTH_TOKEN_SHA256_MAP=<token_map.json>` |
| 动态账号 | 注册/登录/游客自助开通 | `API_AUTH_MODE=bearer` + `AUTH_REGISTRATION_ENABLED=true`（或 `AUTH_GUEST_ENABLED=true`） |

静态与动态 token **合并生效**，可同时开启。

## 1. 启动前检查

关键 `.env`：

```dotenv
API_AUTH_MODE=bearer
API_AUTH_TOKEN_SHA256_MAP={}          # 或填 token_map.json 单行内容
ENABLE_LOCAL_AUDIO_PLAYBACK=false     # bearer 模式必须为 false
AUTH_STORE_PATH=data/auth/auth_store.json
AUTH_REGISTRATION_ENABLED=true        # 内测期
AUTH_GUEST_ENABLED=true               # 内测期
AUTH_INVITE_CODE=                     # 需要邀请码时填写
EXECUTION_STATE_MODE=local            # 本地无 Redis Stack 时
MEMORY_LONG_TERM_DEFAULT_ENABLED=false # 无 Qdrant 时
```

启动（WSL）：

```bash
cd /mnt/f/aiagent
uv run --no-sync python -m uvicorn apps.api.http_server:app --host 0.0.0.0 --port 8000
# 或直接 /root/.venvs/aiagent/bin/python -m uvicorn ...
```

启动后三连：

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s http://127.0.0.1:8000/runtime/diagnostics | head -c 400
```

预期：`/health` 200；诊断 `status=degraded` 属正常（Qdrant/Redis 未启）。

## 2. 自动化测试

```bash
cd /mnt/f/aiagent
export EXECUTION_STATE_MODE=local SDL_AUDIODRIVER=dummy

python -m pytest tests/api/test_auth_contract.py tests/api/test_telemetry_summary_contract.py -q
python -m pytest tests/api/test_telemetry_contract.py -q
python -m pytest tests/api/test_chat_resilience_contract.py -q

ruff check apps/api tests/api
python scripts/check_config_sync.py
python scripts/check_repo_hygiene.py
python scripts/v1_2_baseline.py --root . --output /tmp/baseline.json --markdown /tmp/baseline.md
```

## 3. 账号体系（手工）

```bash
# 游客（免注册）
curl -s -X POST http://127.0.0.1:8000/auth/guest \
  -H 'Content-Type: application/json' -d '{"device_id":"dev-1"}'

# 注册
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"secret123"}'

# 登录
curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"tester01","password":"secret123"}'

# 我是谁
curl -s http://127.0.0.1:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

预期与错误码：

| 场景 | 状态码 | code |
| --- | --- | --- |
| 注册成功 | 200 | — |
| 用户名重复 | 409 | `username_taken` |
| 密码 < 6 位 | 400 | `invalid_password` |
| 邀请码不匹配 | 403 | `invalid_invite` |
| 注册关闭 | 403 | `registration_disabled` |
| 游客关闭 | 403 | `guest_disabled` |
| 密码错误 | 401 | `invalid_credentials` |

## 4. 鉴权边界

```bash
echo "no-token  -> $(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' -d '{"user_id":"x","username":"x","text":"hi"}')"

echo "mismatch  -> $(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"user_id":"someone-else","username":"x","text":"hi"}')"

echo "matched   -> $(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"$USER\",\"username\":\"t\",\"text\":\"你好\"}")"
```

预期：401 / 403（`principal_mismatch`）/ 200。

音频（播放器无法带 header）：

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://127.0.0.1:8000/audio/any.wav?access_token=$TOKEN"   # 不应是 401
```

## 5. 遥测回流

```bash
curl -s -X POST http://127.0.0.1:8000/telemetry/batch \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"batch_id":"manual-batch-0001","app":{"version":"1.3.0","platform":"android"},
       "events":[{"id":"e1","type":"turn","latency_ms":1200,"degraded":false},
                 {"id":"e2","type":"feedback","rating":-1,"tags":["太慢"]}]}'

# 幂等：重复 batch_id → duplicates=1

# 统计（管理端）
curl -s "http://127.0.0.1:8000/telemetry/summary?date=$(date +%F)" \
  -H 'X-Cloud-Admin-Token: <CLOUD_ADMIN_TOKEN>'
```

预期：`accepted=2`；summary 返回 `turns/feedback/latency_ms/ratings/tags`；无管理员 token 返回 403/503。

## 6. 移动端联调

1. 安装 `app-arm64-v8a-release.apk`（若装过 debug 包先卸载）。
2. 首启粘贴激活码（`data/private/activation/activation_codes.csv` 任取一行）。
3. 聊天一轮 → 应有回复与情绪；顶栏显示在线。
4. 打开飞行模式发一条 → 气泡显示“待发送”，顶栏“离线”；关闭飞行模式 → 自动补发。
5. 发送图片、语音各一次 → 回复正常，语音可播放（音频带 query token）。
6. 对回复点 👎 → 选择原因 → 服务器 `telemetry/summary` 的 `ratings.down` 与 `tags` 增加。
7. 杀掉 App 重开 → 历史、反馈状态保留。

## 7. 故障排查

| 现象 | 排查 |
| --- | --- |
| 启动报 `api_auth_configuration_invalid` | bearer 模式下既无静态映射、也未开注册/游客 |
| `/chat` 401 | 未带 Bearer，或 token 过期（看 `expires_at`） |
| `/chat` 403 `principal_mismatch` | 请求 `user_id` 与 token 映射不一致 |
| `/auth/me` 503 | `api_auth_mode=local-dev` 之外鉴权配置无效 |
| 注册 403 | `AUTH_REGISTRATION_ENABLED=false` 或邀请码不匹配 |
| 游客 403 | `AUTH_GUEST_ENABLED=false` |
| summary 403/503 | 未配置/未携带 `CLOUD_ADMIN_TOKEN` |

重置账号库（仅测试环境）：

```bash
rm -f data/auth/auth_store.json    # 所有动态账号/令牌失效
```

## 8. 清理

```bash
pkill -f 'uvicorn apps.api.http_server'
rm -f data/auth/auth_store.json data/telemetry/*.jsonl
```
