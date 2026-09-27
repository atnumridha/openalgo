#!/bin/bash
set -u
archive_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$archive_root" || exit 1
if [ -x "$archive_root/.venv/bin/python" ]; then
    "$archive_root/.venv/bin/python" -m services.research.nse_download "$@"
    archive_result=$?
else
    printf 'Start OpenAlgo once to prepare its Python environment, then try again.\n'
    archive_result=1
fi
if [ -t 0 ] && [ "${OPENALGO_NO_PAUSE:-0}" != "1" ]; then
    printf '\nPress Return to close. Downloaded history remains saved.\n'
    read -r archive_reply
fi
exit "$archive_result"
