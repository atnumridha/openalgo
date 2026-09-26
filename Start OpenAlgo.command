#!/bin/bash
exec /bin/bash "$(cd -- "$(dirname -- "$0")" && pwd)/scripts/local-stack.sh" start "$@"
