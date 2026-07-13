#!/usr/bin/env bash
# Local dev bootstrap for ufdr-analyzer (no Docker required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy env.example and fill in secrets."
  exit 1
fi

# shellcheck disable=SC1091
set -a && source .env && set +a

mkdir -p .local/data/meili backend/storage/{json,reports,tmp}

start_meili() {
  if curl -fsS "http://127.0.0.1:7700/health" >/dev/null 2>&1; then
    echo "Meilisearch already running on :7700"
    return
  fi
  echo "Starting Meilisearch..."
  MEILI_MASTER_KEY="${MEILI_MASTER_KEY:?set MEILI_MASTER_KEY in .env}" \
    nohup "$ROOT/.local/bin/meilisearch" \
      --db-path "$ROOT/.local/data/meili" \
      --http-addr 127.0.0.1:7700 \
      > "$ROOT/.local/meilisearch.log" 2>&1 &
  echo $! > "$ROOT/.local/meilisearch.pid"
  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:7700/health" >/dev/null 2>&1 && break
    sleep 0.5
  done
  echo "Meilisearch ready"
}

start_backend() {
  if curl -fsS "http://127.0.0.1:8000/health/" >/dev/null 2>&1; then
    echo "Backend already running on :8000"
    return
  fi
  echo "Starting backend..."
  source "$ROOT/.venv/bin/activate"
  cd "$ROOT/backend"
  nohup python server.py > "$ROOT/.local/backend.log" 2>&1 &
  echo $! > "$ROOT/.local/backend.pid"
  cd "$ROOT"
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:8000/health/" >/dev/null 2>&1 && break
    sleep 0.5
  done
  echo "Backend ready at http://localhost:8000"
}

start_frontend() {
  if curl -fsS "http://127.0.0.1:3000" >/dev/null 2>&1; then
    echo "Frontend already running on :3000"
    return
  fi
  echo "Starting frontend..."
  cd "$ROOT/frontend"
  nohup npm run dev > "$ROOT/.local/frontend.log" 2>&1 &
  echo $! > "$ROOT/.local/frontend.pid"
  cd "$ROOT"
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:3000" >/dev/null 2>&1 && break
    sleep 0.5
  done
  echo "Frontend ready at http://localhost:3000"
}

case "${1:-all}" in
  meili) start_meili ;;
  backend) start_meili; start_backend ;;
  frontend) start_frontend ;;
  all) start_meili; start_backend; start_frontend ;;
  stop)
    for f in frontend backend meilisearch; do
      pidfile="$ROOT/.local/${f}.pid"
      if [[ -f "$pidfile" ]]; then
        kill "$(cat "$pidfile")" 2>/dev/null || true
        rm -f "$pidfile"
      fi
    done
    echo "Stopped local services"
    ;;
  *)
    echo "Usage: $0 [all|meili|backend|frontend|stop]"
    exit 1
    ;;
esac
