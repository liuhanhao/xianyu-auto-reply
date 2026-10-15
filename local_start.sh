#!/usr/bin/env bash
# 本地源码一键启动 / 停止（不走 Docker）
# 用法: bash local_start.sh {start|stop|restart|status}
#
# 关键修复（macOS 兼容）:
#   - 启动前 source 各服务 .env，把配置注入进程环境（pydantic-settings 环境变量优先级最高，
#     确保 HOST=0.0.0.0 生效，避免 macOS 上监听 [::] 变成 IPv6-only 导致 127.0.0.1 连不上）
#   - 启动顺序：backend-web 健康检查通过后再起 websocket，再起 scheduler（避免并发建表竞态）
#
# 前置（首次只需一次）:
#   1) 三个后端装依赖: 各目录 python3 -m venv .venv && source .venv/bin/activate && pip install -e .
#   2) 前端装依赖:     cd frontend && npm install
#   本脚本会检测 .venv / node_modules，缺失则跳过并提示。

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

wait_health() {
  local port="$1" i code
  for i in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:$port/health" 2>/dev/null || true)
    if [ "$code" = "200" ]; then echo "  port $port ready"; return 0; fi
    sleep 2
  done
  echo "  WARN: port $port 未在 80s 内就绪，请查 $1 日志"
}

start_one() {
  local dir="$1" name="$2"
  if [ -x "$dir/.venv/bin/python" ]; then
    mkdir -p "$dir/logs"
    ( set -a; source "$dir/.env"; set +a; nohup "$dir/.venv/bin/python" "$dir/main.py" > "$dir/logs/run.log" 2>&1 & echo $! > "$dir/.pid" )
    echo "  started $name (pid $(cat "$dir/.pid"))"
  else
    echo "  SKIP $name: $dir/.venv 不存在，请先装依赖 (pip install -e .)"
  fi
}

start() {
  echo "==> 启动基础设施 mysql / redis"
  brew services start mysql redis 2>/dev/null || true

  start_one backend-web backend-web
  wait_health 8089
  start_one websocket websocket
  wait_health 8090
  start_one scheduler scheduler
  wait_health 8091

  if [ -d frontend/node_modules ]; then
    mkdir -p frontend/logs
    nohup npm --prefix frontend run dev > frontend/logs/run.log 2>&1 &
    echo $! > frontend/.pid
    echo "  started frontend (pid $(cat frontend/.pid))"
  else
    echo "  SKIP frontend: frontend/node_modules 不存在，请先 'cd frontend && npm install'"
  fi
  echo "==> 启动完成。可用: bash $0 status ; 日志在各服务 logs/run.log"
}

stop() {
  echo "==> 停止服务"
  for d in backend-web websocket scheduler frontend; do
    if [ -f "$d/.pid" ]; then
      pid=$(cat "$d/.pid")
      if kill "$pid" 2>/dev/null; then echo "  stopped $d (pid $pid)"; else echo "  $d 进程不在 (pid $pid)"; fi
      rm -f "$d/.pid"
    fi
  done
  pkill -f "main.py" 2>/dev/null || true
  pkill -f "vite" 2>/dev/null || true
  echo "==> 已尝试停止全部服务"
}

status() {
  echo "==> 后端健康检查 (200 即正常)"
  for p in 8089 8090 8091; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:$p/health" 2>/dev/null || echo ERR)
    echo "  port $p -> $code"
  done
  echo "==> 前端 (vite):"
  pgrep -fl vite || echo "  未运行"
}

case "${1:-}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; sleep 2; start ;;
  status)  status ;;
  *) echo "用法: bash $0 {start|stop|restart|status}"; exit 1 ;;
esac
