"""OpenAlgo-hosted transcript-inspired liquidity extra confirmation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strategies.liquidity.runner import main

if __name__ == "__main__":
    main()
