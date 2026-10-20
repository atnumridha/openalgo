#!/bin/zsh
# Double-click to start OpenAlgo on this Mac.
set -euo pipefail

# macOS opens .command files with a login shell that does not see ~/.local/bin.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/log/mac"
PID_FILE="$RUN_DIR/openalgo.pid"
LOG_FILE="$RUN_DIR/openalgo.log"
URL="http://127.0.0.1:5050"
mkdir -p "$RUN_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "OpenAlgo is already running (pid $OLD_PID)."
    echo "Open $URL"
    open "$URL" || true
    echo
    echo "This window can be closed. Use Stop OpenAlgo.command to shut it down."
    read -r "?Press Enter to close..."
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 5050 is already in use, but it is not the OpenAlgo process this script started."
  echo "Stop that process, or change FLASK_PORT in .env, then try again."
  lsof -nP -iTCP:5050 -sTCP:LISTEN || true
  echo
  read -r "?Press Enter to close..."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (Python package runner)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not on PATH. Open a new terminal, or add ~/.local/bin to PATH, then retry."
  read -r "?Press Enter to close..."
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Installing Python dependencies (first run only, this can take a few minutes)..."
  uv sync
fi

echo "Starting OpenAlgo..."
echo "Log: $LOG_FILE"
# Own process group so Stop can signal uv and the Flask child together.
# Closing this window does not kill the server.
uv run app.py >>"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
disown

READY=0
for _ in {1..90}; do
  if curl -fsS -o /dev/null --max-time 2 "$URL" 2>/dev/null; then
    READY=1
    break
  fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "OpenAlgo exited during startup. Last log lines:"
    tail -n 40 "$LOG_FILE" || true
    rm -f "$PID_FILE"
    echo
    read -r "?Press Enter to close..."
    exit 1
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  echo "OpenAlgo is still starting. Check the log if the page does not load:"
  echo "  $LOG_FILE"
else
  echo "OpenAlgo is ready at $URL"
fi

open "$URL" || true
echo
echo "This window can be closed. The server keeps running."
echo "Double-click Stop OpenAlgo.command when you want to shut it down."
read -r "?Press Enter to close..."
