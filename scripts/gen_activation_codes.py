r"""生成移动端激活码（批量），以及后端 API_AUTH_TOKEN_SHA256_MAP。

激活码 = base64url(JSON{v, b, ba, t, u, n})，客户端一次粘贴即可完成"服务地址 + 令牌 + 用户身份"三件事。

用法：
    python scripts/gen_activation_codes.py --count 50 --base-urls http://192.168.1.20:8000
    python scripts/gen_activation_codes.py --count 50 --base-urls https://api.example.com --base-urls https://api-b.example.com
    python scripts/gen_activation_codes.py --count 3 --prefix demo --out-dir data/private/activation/demo

产物（默认 data/private/activation/，已被 .gitignore 忽略）：
    activation_codes.csv   每个测试者一行：user_id, username, token, activation_code
    token_map.json         可直接作为 API_AUTH_TOKEN_SHA256_MAP 的值
    tokens.txt             仅 token 列表，便于分发
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import re
import secrets
from pathlib import Path

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43,256}\Z")


def encode_activation(base_urls: list[str], token: str, user_id: str, username: str) -> str:
    payload = {
        "v": 1,
        "b": base_urls[0],
        "ba": base_urls,
        "t": token,
        "u": user_id,
        "n": username,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成移动端激活码与 token 映射")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--base-urls", action="append", required=True, help="可多次传入，第一个为主入口")
    parser.add_argument("--prefix", default="tester")
    parser.add_argument(
        "--reuse-from",
        default="",
        help="复用已有 activation_codes.csv 的 token/user_id/username，只更新服务入口（不换身份）",
    )
    parser.add_argument("--out-dir", default=str(Path("data") / "private" / "activation"))
    args = parser.parse_args()

    if args.count <= 0:
        raise SystemExit("--count 必须大于 0")
    base_urls = [url.rstrip("/") for url in args.base_urls if url.strip()]
    if not base_urls:
        raise SystemExit("--base-urls 不能为空")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    token_map: dict[str, str] = {}

    if args.reuse_from:
        reuse_path = Path(args.reuse_from)
        if not reuse_path.exists():
            raise SystemExit(f"复用文件不存在：{reuse_path}")
        with reuse_path.open(encoding="utf-8-sig", newline="") as handle:
            for item in csv.DictReader(handle):
                token = str(item.get("token") or "").strip()
                user_id = str(item.get("user_id") or "").strip()
                username = str(item.get("username") or "").strip() or user_id
                if not TOKEN_RE.fullmatch(token) or not user_id:
                    raise SystemExit(f"复用文件行无效：{item}")
                token_map[hashlib.sha256(token.encode("ascii")).hexdigest()] = user_id
                rows.append(
                    {
                        "user_id": user_id,
                        "username": username,
                        "token": token,
                        "activation_code": encode_activation(
                            base_urls, token, user_id, username
                        ),
                    }
                )
        if not rows:
            raise SystemExit("复用文件为空")
    else:
        for index in range(1, args.count + 1):
            user_id = f"{args.prefix}-{index:03d}"
            username = f"测试用户{index:02d}"
            token = secrets.token_urlsafe(32)
            if not TOKEN_RE.fullmatch(token):
                raise SystemExit("生成的 token 不符合后端格式要求")
            digest = hashlib.sha256(token.encode("ascii")).hexdigest()
            token_map[digest] = user_id
            rows.append(
                {
                    "user_id": user_id,
                    "username": username,
                    "token": token,
                    "activation_code": encode_activation(
                        base_urls, token, user_id, username
                    ),
                }
            )

    csv_path = out_dir / "activation_codes.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    (out_dir / "token_map.json").write_text(
        json.dumps(token_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "tokens.txt").write_text(
        "\n".join(row["token"] for row in rows) + "\n", encoding="utf-8"
    )

    compact_map = json.dumps(token_map, ensure_ascii=False, separators=(",", ":"))
    print(f"已生成 {len(rows)} 个激活码")
    print(f"  目录      : {out_dir.resolve()}")
    print(f"  CSV       : {csv_path.name}")
    print(f"  token 映射: token_map.json（{len(compact_map)} 字符）")
    print(f"  入口      : {', '.join(base_urls)}")
    print("")
    print("示例激活码（第一个测试者）：")
    print("  " + rows[0]["activation_code"])
    print("")
    print("把 token_map.json 的紧凑内容写入后端 .env：")
    print("  API_AUTH_MODE=bearer")
    print("  API_AUTH_TOKEN_SHA256_MAP=<token_map.json 单行内容>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
