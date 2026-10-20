#!/bin/zsh
# Double-click to stop the OpenAlgo process started by start.command.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/log/mac"
PID_FILE="$RUN_DIR/openalgo.pid"

stop_pid() {
  local pid="$1"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  # uv run app.py spawns a child; stop the whole process group.
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  local _
  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  return 0
}

# A listener we started is either uv or its python child.
is_openalgo_cmd() {
  case "$1" in
    *openalgo*|*app.py*|*"uv run"*) return 0 ;;
    *) return 1 ;;
  esac
}

STOPPED=0
if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if stop_pid "${PID:-}"; then
    echo "Stopped OpenAlgo (pid $PID)."
    STOPPED=1
  fi
  rm -f "$PID_FILE"
fi

# Catch a server that was started earlier but lost its pid file.
if lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
  PIDS="$(lsof -nP -t -iTCP:5050 -sTCP:LISTEN | sort -u)"
  for PID in ${(f)PIDS}; do
    CMD="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    if is_openalgo_cmd "$CMD"; then
      stop_pid "$PID" || true
      echo "Stopped leftover OpenAlgo listener (pid $PID)."
      STOPPED=1
    else
      echo "Left pid $PID alone; it is listening on 5050 but is not OpenAlgo."
      echo "  $CMD"
    fi
  done
fi

if [[ "$STOPPED" -eq 0 ]]; then
  echo "OpenAlgo is not running."
else
  echo "OpenAlgo is stopped."
fi

echo
read -r "?Press Enter to close..."
