#!/usr/bin/env python3
"""
Kiro CLI → OpenAI-compatible /v1/chat/completions proxy

用法:
    python3 kiro_proxy.py          # 默认监听 127.0.0.1:3200
    python3 kiro_proxy.py --port 3200 --host 127.0.0.1

在 xianyu-auto-reply AI 设置里填:
    服务商类型: OpenAI 兼容
    Base URL:  http://127.0.0.1:3200/v1
    API Key:   local（随便填）
    模型名:    auto（或 claude-haiku-4.5 最快最省）
"""
import argparse
import json
import subprocess
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


def call_kiro(prompt: str, model: str = "auto") -> str:
    """调用 kiro-cli chat --no-interactive 拿回复，同步阻塞。"""
    cmd = ["kiro-cli", "chat", "--no-interactive", "--trust-tools", ""]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip()
        if not output and result.stderr.strip():
            output = result.stderr.strip()
        return output or "（Kiro 无回复）"
    except subprocess.TimeoutExpired:
        return "（Kiro 超时）"
    except FileNotFoundError:
        return "（找不到 kiro-cli 命令，请确认已安装）"


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
    def log_message(self, fmt, *args):
        print(f"[kiro-proxy] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        if self.path.rstrip("/") in ("/v1/models", "/v1/model"):
            body = json.dumps({"object": "list", "data": [
                {"id": "auto", "object": "model"},
                {"id": "claude-haiku-4.5", "object": "model"},
                {"id": "claude-sonnet-4.6", "object": "model"},
                {"id": "deepseek-3.2", "object": "model"},
            ]}).encode()
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
        model = data.get("model", "auto")
        prompt = build_messages_prompt(messages)
        print(f"[kiro-proxy] → model={model} prompt_len={len(prompt)}")
        reply = call_kiro(prompt, model)
        print(f"[kiro-proxy] ← reply={reply[:60]!r}")
        body = json.dumps(make_response(reply, model), ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Kiro CLI → OpenAI proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3200)
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), ProxyHandler)
    print(f"Kiro proxy 已启动: http://{args.host}:{args.port}/v1")
    print("在 xianyu-auto-reply AI 设置里填:")
    print(f"  Base URL : http://{args.host}:{args.port}/v1")
    print("  API Key  : local")
    print("  模型名   : auto（或 claude-haiku-4.5 最快最省）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
