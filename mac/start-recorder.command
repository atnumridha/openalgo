#!/bin/zsh
# Double-click to start recording Delta BTCUSD order book and trades.
# Keeps the Mac awake while it runs (the display can still sleep).
set -u
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/workspace/backtests/btc_scalp"
PID_FILE="$DIR/ticks/recorder.pid"
LOG="$DIR/ticks/recorder.log"
mkdir -p "$DIR/ticks"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "The recorder is already running (pid $(cat "$PID_FILE"))."
  echo "Data: $DIR/ticks"
  read -r "?Press Enter to close..."
  exit 0
fi

echo "Recording Delta BTCUSD order book (top 10 levels) and every trade."
echo "Data: $DIR/ticks  (about 25 MB a day)"
echo "Log:  $LOG"
echo "Leave this window open. Double-click Stop Recorder.command to stop."
echo
cd "$DIR"
# caffeinate -i: no idle sleep while the recorder runs. Closing the lid still sleeps the Mac.
exec caffeinate -i "$ROOT/.venv/bin/python" -u record_book.py 2>&1 | tee -a "$LOG"
