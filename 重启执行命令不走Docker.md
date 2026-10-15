# 启动执行命令（不走 Docker）

适用于本机已用 Homebrew 安装并运行 MySQL / Redis，不使用 Docker 构建镜像，直接在宿主机运行各服务。

> 本机现状（已确认）：
> - MySQL 9.6.0 运行中，已创建 `xianyu_data` 库与 `xianyu` 用户（密码 `xianyu@2026`，授权 `%`，允许 `127.0.0.1` TCP 连接）
> - Redis 8.6.1 运行中，未设密码（`REDIS_PASSWORD` 留空即可）
>
> 换机器时，请先自行准备 MySQL/Redis，并创建库与用户：
> ```sql
> CREATE DATABASE xianyu_data CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
> CREATE USER 'xianyu'@'%' IDENTIFIED BY 'xianyu@2026';
> GRANT ALL PRIVILEGES ON xianyu_data.* TO 'xianyu'@'%';
> FLUSH PRIVILEGES;
> ```

## 一、首次部署（只需做一次）

### 1. 启动基础设施（已运行可跳过，重复执行无害）
```bash
brew services start mysql redis
```

### 2. 创建 .env 配置
每个服务通过**自身目录下的 `.env`** 读取配置（相对工作目录），需在 `backend-web/`、`websocket/`、`scheduler/` 三个目录各放一份。

`backend-web/.env`：
```
ENVIRONMENT=development
HOST=0.0.0.0
LOG_LEVEL=INFO
SQL_ECHO=false

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=xianyu
MYSQL_PASSWORD=xianyu@2026
MYSQL_DATABASE=xianyu_data

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

BACKEND_WEB_PORT=8089
CORS_ORIGINS=*
WEBSOCKET_SERVICE_URL=http://127.0.0.1:8090
SCHEDULER_SERVICE_URL=http://127.0.0.1:8091
BACKEND_WEB_PUBLIC_URL=http://127.0.0.1:8089
STATIC_DIR=static
BACKUP_DIR=backups
INTERNAL_API_TOKEN=
```

`websocket/.env`：
```
ENVIRONMENT=development
HOST=0.0.0.0
LOG_LEVEL=INFO
SQL_ECHO=false

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=xianyu
MYSQL_PASSWORD=xianyu@2026
MYSQL_DATABASE=xianyu_data

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

WEBSOCKET_PORT=8090
BROWSER_HEADLESS=true
AUTO_START_WEBSOCKET=true
MAX_CAPTCHA_CONCURRENT=3
BACKEND_WEB_SERVICE_URL=http://127.0.0.1:8089
STATIC_DIR=static
INTERNAL_API_TOKEN=
```

`scheduler/.env`：
```
ENVIRONMENT=development
HOST=0.0.0.0
LOG_LEVEL=INFO
SQL_ECHO=false

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=xianyu
MYSQL_PASSWORD=xianyu@2026
MYSQL_DATABASE=xianyu_data

REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

SCHEDULER_PORT=8091
WEBSOCKET_SERVICE_URL=http://127.0.0.1:8090
BACKEND_WEB_SERVICE_URL=http://127.0.0.1:8089
STATIC_DIR=static
BACKUP_DIR=backups
INTERNAL_API_TOKEN=
```

> 若改用本机 root 直连：将三份里的 `MYSQL_USER` 改为 `root`、`MYSQL_PASSWORD` 留空，并确保 root 允许 `127.0.0.1` 连接。

### 3. 安装后端依赖（三个服务各自独立虚拟环境）
分别进入三个目录，建 venv、装依赖、装浏览器：
```bash
# backend-web
cd backend-web && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install chromium
python -m patchright install chromium
deactivate

# websocket
cd ../websocket && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install chromium
python -m patchright install chromium
deactivate

# scheduler
cd ../scheduler && python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m playwright install chromium
python -m patchright install chromium
deactivate
```
首次安装会联网下载 Playwright / Patchright 的 Chromium，耗时较长。

> 浏览器二进制是**用户级缓存**（`~/.cache/ms-playwright`），跨 venv 共享，只需装一次。
> 若 `~/.cache/ms-playwright` 已存在对应的 chromium，两个 `install chromium` 步骤可跳过（只需 `pip install -e .`）。
> 注意：系统里另装的 Chromium（如 `brew install chromium`）**不能**替代，Playwright 只认自己下载的那个。

### 4. 安装前端依赖
```bash
cd frontend && npm install
```

## 二、启动 / 重启（每次开机或重启服务）

**推荐使用一键脚本**（详见第六节），一条命令搞定全部服务与启动顺序：

```bash
bash local_start.sh start     # 启动全部（含 mysql/redis）
bash local_start.sh status    # 查看健康
bash local_start.sh stop      # 停止全部
bash local_start.sh restart   # 重启
```

### 手动方式（不使用脚本时）

> 建议顺序：基础设施 → backend-web → websocket → scheduler → frontend。
> 每个服务开一个终端（或用 `nohup ... &` 后台运行）。

```bash
# 0) 基础设施（如未运行）
brew services start mysql redis

# 1) backend-web（终端1）
cd /Users/liuhanhao/Desktop/xianyu-auto-reply/backend-web && .venv/bin/python main.py

# 2) websocket（终端2）
cd /Users/liuhanhao/Desktop/xianyu-auto-reply/websocket && .venv/bin/python main.py

# 3) scheduler（终端3）
cd /Users/liuhanhao/Desktop/xianyu-auto-reply/scheduler && .venv/bin/python main.py

# 4) frontend（终端4）
cd /Users/liuhanhao/Desktop/xianyu-auto-reply/frontend && npm run dev
```

> **手动方式必须依次启动**：等 backend-web 的 `/health` 返回 200 后再起 websocket，再起 scheduler。
> 若同时启动，backend-web 尚未完成建表，websocket / scheduler 查询系统表会报
> `Table 'xianyu_data.xy_system_settings' doesn't exist` 然后退出。

## 三、验证

各后端均提供 `/health`：
```bash
curl http://127.0.0.1:8089/health   # backend-web
curl http://127.0.0.1:8090/health   # websocket
curl http://127.0.0.1:8091/health   # scheduler
```
返回 `"status": "running"` 且 `"database": "connected"` 即正常。

## 四、访问

- 前端：`http://localhost:9000/`（本项目 vite 端口固定 9000，启动后 `frontend/logs/run.log` 也会打印）
- 后端 API 文档：`http://127.0.0.1:8089/docs`
- 默认管理员：`admin` / `admin123`（首次启动自动初始化）

## 五、注意事项

- **服务间地址用本机 IP**：`WEBSOCKET_SERVICE_URL`、`SCHEDULER_SERVICE_URL`、`BACKEND_WEB_SERVICE_URL` 必须填 `http://127.0.0.1:<端口>`，不要照抄 Docker 里的容器名（`mysql` / `websocket` 等）。
- **`.env` 位置**：三个服务各读各自目录下的 `.env`（相对工作目录），不要只放在根目录。
- **MySQL 用户**：应用通过 TCP `127.0.0.1` 连接，授权用户需允许 `127.0.0.1` 或 `%`（不能是仅 `localhost`）。
- **日志**：各服务日志在各自目录的 `logs/` 下（脚本启动时为 `logs/run.log`）。
- **停止**：直接 `Ctrl+C` 结束各终端进程；或 `pkill -f main.py`；用脚本则 `bash local_start.sh stop`。

## 六、一键脚本 `local_start.sh`

项目根目录已提供 `local_start.sh`，封装了「基础设施 → backend-web → websocket → scheduler → frontend」的完整启动/停止流程，脚本已内置下面两个坑的修复，日常直接用它即可。

脚本做的两件关键事（都是实测踩坑后的修复）：

1. **启动前 `source .env` 注入进程环境**
   pydantic-settings 中环境变量优先级高于 `.env` 文件。若不注入，`.env` 里的 `HOST=0.0.0.0` 可能读不到，
   服务会按默认值监听 `[::]`。而 **macOS 默认 `IPV6_V6ONLY=1`**，监听 `[::]` 不接收 IPv4 连接，
   导致本机 `127.0.0.1` 全部连不上（`/health` 返回 `000`），其它服务也会因回调 backend-web 失败而启动异常。
   注入 `HOST=0.0.0.0` 后服务监听 IPv4，本机访问正常
   （可在日志确认：`Uvicorn running on http://0.0.0.0:8089`，而不是 `[::]:8089`）。
2. **按顺序启动并等待健康检查**
   backend-web 负责建库建表，必须等它 `/health` 返回 200 后再起 websocket、scheduler，
   否则两者会查到「表不存在」而退出（首次启动时尤其明显）。

脚本内容（与项目根目录 `local_start.sh` 一致，修改请同步）：

```bash
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
```
