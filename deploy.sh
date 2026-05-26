#!/usr/bin/env bash
# 一键部署脚本 — 在火山云服务器上跑
# 用法:
#   首次部署: bash deploy.sh
#   更新代码: bash deploy.sh update
#   查看日志: bash deploy.sh logs
#   重启:     bash deploy.sh restart
#   停止:     bash deploy.sh stop

set -euo pipefail

APP_DIR="${APP_DIR:-/root/ai-srt-dubbing}"
REPO_URL="${REPO_URL:-git@github-aidubbing:JohnGoner/ai-srt-dubbing.git}"
BRANCH="${BRANCH:-dev}"

cmd="${1:-deploy}"

# Detect docker compose flavor (V2 plugin "docker compose" or V1 "docker-compose")
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "[deploy] ERROR: neither 'docker compose' nor 'docker-compose' is available" >&2
  exit 1
fi

ensure_repo() {
  if [ ! -d "$APP_DIR/.git" ]; then
    echo "[deploy] cloning $REPO_URL into $APP_DIR ..."
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
  else
    echo "[deploy] pulling latest $BRANCH ..."
    git -C "$APP_DIR" fetch origin "$BRANCH"
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" reset --hard "origin/$BRANCH"
  fi
}

check_secrets() {
  cd "$APP_DIR"
  local missing=0
  for f in config.yaml firebase-credentials.json google-credentials.json; do
    if [ ! -f "$f" ]; then
      echo "[deploy] MISSING $APP_DIR/$f"
      missing=1
    fi
  done
  if [ "$missing" -eq 1 ]; then
    echo ""
    echo "Upload secrets from your local machine first, e.g.:"
    echo "  scp config.yaml firebase-credentials.json google-credentials.json root@14.103.86.179:$APP_DIR/"
    exit 1
  fi
}

build_and_up() {
  cd "$APP_DIR"
  echo "[deploy] building image ..."
  $COMPOSE build
  echo "[deploy] starting container ..."
  $COMPOSE up -d
  echo "[deploy] waiting for health ..."
  sleep 6
  $COMPOSE ps
  echo ""
  echo "[deploy] app should be reachable at http://127.0.0.1:8501 (localhost only)"
  echo "[deploy] route via Cloudflare Tunnel to expose publicly."
}

case "$cmd" in
  deploy)
    ensure_repo
    check_secrets
    build_and_up
    ;;
  update)
    ensure_repo
    check_secrets
    cd "$APP_DIR"
    $COMPOSE build
    $COMPOSE up -d
    $COMPOSE ps
    ;;
  restart)
    cd "$APP_DIR" && $COMPOSE restart
    ;;
  stop)
    cd "$APP_DIR" && $COMPOSE down
    ;;
  logs)
    cd "$APP_DIR" && $COMPOSE logs -f --tail=200
    ;;
  status)
    cd "$APP_DIR" && $COMPOSE ps && echo "---" && curl -sS http://127.0.0.1:8501/_stcore/health || true
    ;;
  *)
    echo "Usage: $0 {deploy|update|restart|stop|logs|status}"
    exit 1
    ;;
esac
