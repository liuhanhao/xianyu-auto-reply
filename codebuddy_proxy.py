#!/usr/bin/env python3
"""
CodeBuddy CLI → OpenAI-compatible /v1/chat/completions proxy

改造说明（消除每次请求的冷启动）：
    原实现每个请求都 subprocess 拉起一次 `codebuddy --print`，要付一遍 CLI 启动开销。
    现在改为：你先手动启动一个常驻实例，本脚本以 HTTP 客户端方式连上去复用它。

        codebuddy --serve --port 3300 --host 127.0.0.1 --auth none

    然后本脚本通过官方 REST 接口取结果：
        POST /api/v1/runs                发起 Agent 执行，返回 runId
        GET  /api/v1/runs/{runId}/stream  SSE 流式取结果，content.markdown 即回复正文

    注意：所有 /api/v1/* 请求都必须带 `X-CodeBuddy-Request: 1` 头，缺失会被服务端
    返回 403（这是官方强制的安全头，用于触发 CORS preflight）。

    常驻实例不可达时，自动回退到原来的 `codebuddy --print` 冷启动，保证回复不断。

启动顺序（三步，依次在三个终端里执行，都保持前台运行）:

    1) codebuddy login
       首次使用或登录过期后必须执行。未登录时 CLI 只会返回
       "Authentication required. Please use /login command to sign in to your account"，
       此时无论冷启动还是常驻实例都拿不到正常回复。

    2) codebuddy --serve --port 3300 --host 127.0.0.1 --auth none
       启动常驻实例，复用它即可免去每个请求的 CLI 冷启动。

    3) python3 codebuddy_proxy.py --serve-url http://127.0.0.1:3300
       启动本代理，监听 127.0.0.1:3200。

用法:
    python3 codebuddy_proxy.py                    # 默认监听 127.0.0.1:3200，连 3300 的 serve
    python3 codebuddy_proxy.py --serve-url http://127.0.0.1:3300

在 xianyu-auto-reply AI 设置里填:
    服务商类型: OpenAI 兼容
    Base URL:  http://127.0.0.1:3200/v1
    API Key:   local（随便填）
    模型名:    hy3（或其他 codebuddy 支持的模型）

风控说明:
    1. 每个请求使用独立的 source.conversation.id —— 不同闲鱼客户之间不会共享服务端
       上下文（否则 A 客户的历史会被 B 客户看到，属于隐私泄漏 + 回复串味）。
       历史上下文由调用方通过 messages 全量传入，服务端侧不保留。
    2. source.sender.id 固定，服务端按 sender 做限流统计。
    3. HTTPServer 本身单线程，天然串行处理请求；每次调用前随机等待
       [--min-delay, --max-delay] 秒，避免回复过快触发平台侧风控。
    4. 常驻实例不可达时回退到冷启动 --print，避免回复彻底中断。
"""
import argparse
import json
import random
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Optional

# 官方要求的安全头，缺了会 403
SECURITY_HEADER = "X-CodeBuddy-Request"

SENDER_ID = "xianyu-auto-reply"


def call_print(prompt: str, model: str = "hy3") -> str:
    """回退路径：调用 codebuddy --print 拿回复（每个请求都要付一遍启动开销）。"""
    cmd = ["codebuddy", "--print", "--tools", "", "--model", model, prompt]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()
        if not output and result.stderr.strip():
            output = result.stderr.strip()
        return output or "（CodeBuddy 无回复）"
    except subprocess.TimeoutExpired:
        return "（CodeBuddy 超时）"
    except FileNotFoundError:
        return "（找不到 codebuddy 命令，请确认已安装并在 PATH 中）"


def _request(method: str, url: str, password: str,
             body: Optional[dict[str, Any]] = None, timeout: float = 20):
    headers = {SECURITY_HEADER: "1"}
    if password:
        headers["Authorization"] = f"Bearer {password}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def health_ok(base: str, password: str) -> bool:
    try:
        with _request("GET", f"{base}/api/v1/health", password, timeout=5) as r:
            return json.loads(r.read().decode())["data"]["status"] == "ok"
    except Exception:
        return False


def call_serve(base: str, password: str, prompt: str, timeout_ms: int = 90000) -> str:
    """走常驻实例取回复：POST /api/v1/runs 后立刻开 SSE 流读 content.markdown。

    SSE 是一次性回放窗口：run 执行完再拉 /stream 会返回 RUN_NOT_FOUND，
    所以必须在 POST 之后马上开流。
    """
    run_id = "run-" + uuid.uuid4().hex[:12]
    # 风控点：每次请求用全新的 conversation id，避免不同客户之间共享服务端上下文
    conv_id = "conv-" + uuid.uuid4().hex[:12]
    payload = {
        "id": run_id,
        "type": "message",
        "timeoutMs": timeout_ms,
        "payload": {"text": prompt},
        "source": {
            "platform": "generic",
            "sender": {"id": SENDER_ID, "name": SENDER_ID},
            "conversation": {"id": conv_id, "type": "direct"},
        },
    }

    with _request("POST", f"{base}/api/v1/runs", password, payload, timeout=20) as r:
        created = json.loads(r.read().decode("utf-8"))
    real_run_id = created["data"]["runId"]

    parts = []
    event = None
    with _request("GET", f"{base}/api/v1/runs/{real_run_id}/stream",
                  password, timeout=timeout_ms / 1000 + 10) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
                if event == "done":
                    break
                continue
            if not line.startswith("data:"):
                continue
            try:
                msg = json.loads(line[len("data:"):].strip())
            except ValueError:
                continue
            markdown = (msg.get("content") or {}).get("markdown")
            if markdown:
                parts.append(markdown)
    return "".join(parts).strip() or "（CodeBuddy 无回复）"


def build_messages_prompt(messages: list) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
            )
        if role == "system":
            parts.append(f"[系统指令]\n{content}")
        elif role == "assistant":
            parts.append(f"[助手]\n{content}")
        else:
            parts.append(f"[用户]\n{content}")
    return "\n\n".join(parts)


def make_response(content: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": len(content), "total_tokens": len(content)},
    }


class ProxyHandler(BaseHTTPRequestHandler):
    serve_base = "http://127.0.0.1:3300"
    password = ""
    min_delay = 0.5
    max_delay = 2.0

    def log_message(self, fmt, *args):
        print(f"[codebuddy-proxy] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/v1/model"):
            body = json.dumps({"object": "list", "data": [{"id": "hy3", "object": "model"}, {
                              "id": "hy4-preview", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length))
        except Exception:
            self.send_error(400, "Invalid JSON")
            return
        messages = data.get("messages", [])
        model = data.get("model", "hy3")
        prompt = build_messages_prompt(messages)
        print(f"[codebuddy-proxy] → model={model} prompt_len={len(prompt)}")

        reply = self.ask(prompt, model)

        print(f"[codebuddy-proxy] ← reply={reply[:60]!r}")
        body = json.dumps(make_response(reply, model),
                          ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def ask(self, prompt: str, model: str) -> str:
        """风控：随机错峰；常驻实例优先，不可达时回退冷启动。"""
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        try:
            return call_serve(self.serve_base, self.password, prompt)
        except urllib.error.URLError as exc:
            print(f"[codebuddy-proxy] 常驻实例不可达（{exc}），回退冷启动")
        except Exception as exc:
            print(f"[codebuddy-proxy] 常驻实例调用失败（{exc}），回退冷启动")
        return call_print(prompt, model)


def main():
    parser = argparse.ArgumentParser(description="CodeBuddy CLI → OpenAI proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3200)
    parser.add_argument("--serve-url", default="http://127.0.0.1:3300",
                        help="常驻 codebuddy --serve 实例地址")
    parser.add_argument("--password", default="",
                        help="serve 的网关密码；启动时未加 --auth none 才需要")
    parser.add_argument("--min-delay", type=float, default=0.5,
                        help="每次调用前随机等待的下界（秒），用于错峰防风控")
    parser.add_argument("--max-delay", type=float, default=2.0,
                        help="每次调用前随机等待的上界（秒）")
    args = parser.parse_args()

    ProxyHandler.serve_base = args.serve_url.rstrip("/")
    ProxyHandler.password = args.password
    ProxyHandler.min_delay = args.min_delay
    ProxyHandler.max_delay = args.max_delay

    reachable = health_ok(ProxyHandler.serve_base, args.password)
    print(f"CodeBuddy proxy 已启动: http://{args.host}:{args.port}/v1")
    if reachable:
        print(f"  常驻实例已连接 : {ProxyHandler.serve_base}（复用实例，无冷启动）")
    else:
        print(f"  常驻实例不可达 : {ProxyHandler.serve_base}")
        print("  将回退到 codebuddy --print 冷启动。请先执行：")
        print("    codebuddy --serve --port 3300 --host 127.0.0.1 --auth none")
    print("  注意：模型由常驻实例决定（启动时的 --model），/api/v1/runs 不支持按请求切模型")
    print("在 xianyu-auto-reply AI 设置里填:")
    print(f"  Base URL : http://{args.host}:{args.port}/v1")
    print("  API Key  : local")
    print("  模型名   : hy3（或 hy4-preview）")
    server = HTTPServer((args.host, args.port), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
