#!/bin/bash
# 本地源码方式启动主系统（不使用 Docker）
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo ">>> 停止旧进程"
pkill -f "backend-web/main.py" 2>/dev/null
pkill -f "websocket/main.py" 2>/dev/null
pkill -f "scheduler/main.py" 2>/dev/null
sleep 2

mkdir -p logs

echo ">>> 启动后端（nohup + disown 脱离会话）"
nohup backend-web/.venv/bin/python backend-web/main.py > logs/backend-web.out 2>&1 < /dev/null &
disown
nohup websocket/.venv/bin/python websocket/main.py > logs/websocket.out 2>&1 < /dev/null &
disown
nohup scheduler/.venv/bin/python scheduler/main.py > logs/scheduler.out 2>&1 < /dev/null &
disown

echo ">>> 等待启动 (25s)..."
sleep 25

echo "=== 监听端口 ==="
lsof -nP -iTCP:8089 -iTCP:8090 -iTCP:8091 2>/dev/null | grep LISTEN || echo "无监听"

echo "=== 后端 health ==="
for p in 8089 8090 8091; do
  echo -n "port $p: "
  curl -s -m 5 -w " [HTTP %{http_code}]\n" "http://127.0.0.1:$p/health" || echo " (无响应)"
done

echo "=== 后端启动日志 (tail 8) ==="
for s in backend-web websocket scheduler; do
  echo "----- $s/logs/$s.log -----"
  tail -n 8 "$s/logs/$s.log" 2>/dev/null || echo "(无日志文件)"
done
