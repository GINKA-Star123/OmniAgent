# 移动端联调：三个 WSL 终端启动手册

适用环境：WSL 发行版 `sp3-build`，项目在 `/root/aiagent`，原生 venv 在 `/root/.venvs/aiagent-native`。

三个终端分工：

| 终端 | 作用 | 是否常驻 |
| --- | --- | --- |
| 1 | 启动后端（uvicorn） | 是 |
| 2 | 启动 Cloudflare 隧道 | 是 |
| 3 | 用当前隧道地址出码，并复制到 Windows 桌面 | 跑完可关 |

> 快速隧道每次重启 URL 都会变。**只要终端 2 重启过，就必须重跑终端 3**，否则 App 会报 530。

---

## 0. 启动前检查（任意终端）

```bash
test -x /root/aiagent/run_api.sh && echo "run_api.sh OK" || echo "缺少 run_api.sh，见 0.1"
cloudflared --version
test -f /root/aiagent/data/private/activation/activation_codes.csv && echo "激活码源文件 OK"
```

### 0.1 如果缺少 run_api.sh

```bash
cat > /root/aiagent/run_api.sh <<'EOF'
#!/usr/bin/env bash
set -u
cd /root/aiagent || exit 1

export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT=/root/.venvs/aiagent-native

export API_AUTH_MODE=bearer
export API_AUTH_TOKEN_SHA256_MAP="$(python3 -c "import json;print(json.dumps(json.load(open('data/private/activation/token_map.json')),separators=(',',':')))")"
export ENABLE_LOCAL_AUDIO_PLAYBACK=false
export EXECUTION_STATE_MODE=local
export MEMORY_LONG_TERM_DEFAULT_ENABLED=false
export CLOUD_ADMIN_TOKEN="$(openssl rand -hex 32)"

printf '%s' "$CLOUD_ADMIN_TOKEN" > /root/aiagent/.admin_token
chmod 600 /root/aiagent/.admin_token

exec uv run --no-sync python -m uvicorn apps.api.http_server:app \
  --host 127.0.0.1 --port 8000 --log-level info
EOF

chmod +x /root/aiagent/run_api.sh
bash -n /root/aiagent/run_api.sh && echo "语法 OK"
```

---

## 终端 1：后端

```bash
pkill -f 'uvicorn apps.api.http_server' 2>/dev/null || true
sleep 1
cd /root/aiagent
bash run_api.sh
```

保持运行。正常会看到：

```text
Uvicorn running on http://127.0.0.1:8000
INFO:     127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200 OK
[INFO] aiagent.api.request [request_id=... path=/health]: request completed status_code=200 latency_ms=0.9
```

之后每次手机请求都会在这个终端打印一行。

---

## 终端 2：Cloudflare 隧道

```bash
pkill -f 'cloudflared tunnel' 2>/dev/null || true
sleep 1
cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate --protocol http2 2>&1 | tee /tmp/cloudflared.log
```

保持运行。看到下面两行才算就绪：

```text
https://xxxx-xxxx.trycloudflare.com
Registered tunnel connection connIndex=0 ... protocol=http2
```

`tee` 同时把日志写到 `/tmp/cloudflared.log`，终端 3 会从里面读 URL。

---

## 终端 3：出码 + 复制到 Windows 桌面

```bash
cd /root/aiagent
export PATH="$HOME/.local/bin:$PATH"
export UV_PROJECT_ENVIRONMENT=/root/.venvs/aiagent-native

# 1) 等终端 2 的隧道 URL
PUBLIC=""
for i in $(seq 1 90); do
  PUBLIC=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cloudflared.log 2>/dev/null | head -1)
  [ -n "$PUBLIC" ] && break
  sleep 1
done
[ -n "$PUBLIC" ] || { echo "没读到隧道 URL，先看终端 2"; exit 1; }
echo "PUBLIC=$PUBLIC"

# 2) 等隧道注册完成
for i in $(seq 1 60); do
  grep -q "Registered tunnel connection" /tmp/cloudflared.log && break
  sleep 1
done

# 3) 用当前 URL 重新出码（token 不变，后端不用重启）
uv run --no-sync python scripts/gen_activation_codes.py \
  --reuse-from data/private/activation/activation_codes.csv \
  --base-urls "$PUBLIC" \
  --out-dir data/private/activation-public

# 4) 找 Windows 桌面（兼容 OneDrive 重定向）
WIN_DESKTOP="$(powershell.exe -NoProfile -Command '[Environment]::GetFolderPath("Desktop")' 2>/dev/null | tr -d '\r')"
DESKTOP=""
[ -n "$WIN_DESKTOP" ] && DESKTOP="$(wslpath "$WIN_DESKTOP" 2>/dev/null || true)"
if [ -z "$DESKTOP" ] || [ ! -d "$DESKTOP" ]; then
  DESKTOP=/mnt/c/Users/zangp/Downloads
fi
mkdir -p "$DESKTOP" 2>/dev/null || true

# 5) 复制
cp data/private/activation-public/activation_codes.csv "$DESKTOP/activation_codes.csv"
echo "已复制到：$DESKTOP/activation_codes.csv"
ls -lh "$DESKTOP/activation_codes.csv"

# 6) 公网自检
curl -s -o /dev/null -w 'public health: %{http_code}\n' -m 15 "$PUBLIC/health"
```

预期输出：

```text
PUBLIC=https://xxxx.trycloudflare.com
已复制到：/mnt/c/Users/zangp/Desktop/activation_codes.csv
public health: 200
```

---

## 手机验证

1. 打开桌面上的 `activation_codes.csv`，取自己测试者那一行的 `activation_code`。
2. App 里重新粘贴（旧码的 URL 已随隧道重启失效）。
3. 聊天一轮，确认终端 1 出现 `POST /chat` 的 200 日志。

手机 4G 浏览器可直接验证：

```text
https://<终端 2 的地址>/health
```

返回 JSON 而不是 530，说明公网链路正常。

---

## 停止

```bash
# 终端 1 里 Ctrl+C；终端 2 里 Ctrl+C
# 或者在任意终端强制停：
pkill -f 'uvicorn apps.api.http_server'
pkill -f 'cloudflared tunnel'
```

---

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| App 报 530 | 激活码还是旧隧道 URL。重跑终端 3；确认 `grep trycloudflare /tmp/cloudflared.log` 与码里的地址一致 |
| `public health: 000` | 隧道还没注册完成，等 2–3 秒重试；确认终端 2 有 `Registered tunnel connection` |
| 后端 `Connection refused` | 终端 1 没起或已退出，看终端 1 的报错 |
| 8000 端口占用 | `pkill -f 'uvicorn apps.api.http_server'` 后重跑终端 1 |
| `uv: not found` | 用 `bash /root/aiagent/run_api.sh`（脚本内已加 PATH）；或 `export PATH="$HOME/.local/bin:$PATH"` |
| 桌面复制失败 | 桌面可能被 OneDrive 重定向；脚本会自动回退到 `Downloads`，输出里有实际路径 |
| 手机超时 | 快速隧道在部分移动网络不稳定；换 Wi-Fi/4G 再试，或改用命名隧道 + 域名 |
| WSL 提示 localhost 代理 | 不影响本机 127.0.0.1 访问；如果隧道连不上，检查 Windows 代理是否拦截外网 |

---

## 可选：PowerShell 里看请求日志

如果不想一直开着 WSL 终端 1，可以后台启动 + PowerShell tail：

```powershell
wsl -d sp3-build -- bash -lc "cd /root/aiagent && nohup bash run_api.sh > /tmp/aiagent-api.log 2>&1 & echo started"
wsl -d sp3-build -- tail -f /tmp/aiagent-api.log
```

只看请求：

```powershell
wsl -d sp3-build -- tail -f /tmp/aiagent-api.log | Select-String "request completed|POST /chat|GET /"
```

---

## 安全注意

- `activation_codes.csv` 只私发，不要发群、不要提交仓库。
- `/root/aiagent/.admin_token` 是管理端 token，不要外泄。
- 公网暴露时使用强随机 `CLOUD_ADMIN_TOKEN`；内测结束及时停掉隧道。
- 正式对外请用命名隧道（固定域名 + HTTPS）或云服务器，不要长期用快速隧道。
