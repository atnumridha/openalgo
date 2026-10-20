#!/bin/zsh
# Double-click to stop the Delta BTCUSD order book recorder.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/workspace/backtests/btc_scalp"
PID_FILE="$DIR/ticks/recorder.pid"

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
  kill -TERM "$PID"
  for _ in {1..20}; do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.25
  done
  echo "Recorder stopped (pid $PID). Data kept in $DIR/ticks"
else
  echo "The recorder is not running."
fi
echo
read -r "?Press Enter to close..."
