#!/usr/bin/env python3
"""BTCUSD Value Area / CPR / Camarilla / ADX / RSI / MACD / VWMA / options.

Run from OpenAlgo with its Python environment. Upload this wrapper at /python
and choose CRYPTO. It follows Analyze/Live mode. See strategies/README.md for funding, live
qualification and commands.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from strategies.confluence.cli import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
