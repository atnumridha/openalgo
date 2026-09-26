#!/bin/bash
# Shared Finder/terminal entry point. Never source .env as shell code.
set -u
launcher_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$launcher_root" || exit 1

if [ ! -x "$launcher_root/.venv/bin/python" ]; then
    printf 'OpenAlgo needs its Python environment.\nIn this folder, run: uv sync --frozen\nFolder: %s\n' "$launcher_root"
    launcher_result=1
else
    "$launcher_root/.venv/bin/python" "$launcher_root/scripts/local_stack.py" "$@"
    launcher_result=$?
fi

# Keep Finder's Terminal window readable. CLI automation never waits for input.
if [ -t 0 ] && [ "${OPENALGO_NO_PAUSE:-0}" != "1" ]; then
    printf '\nPress Return to close this launcher window. Services started successfully remain running.\n'
    read -r launcher_reply
fi
exit "$launcher_result"
