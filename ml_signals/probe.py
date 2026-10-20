"""Run a low-volume historical-coverage probe, saving each source as it finishes.

Usage: uv run python -m ml_signals.probe [--probes 10] [--spacing-days 40]
This asks for a few small windows per source; it does NOT download a year's
full minute bars.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ml_signals.data import DATA_DIR, probe_source_coverage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes", type=int, default=10)
    parser.add_argument("--spacing-days", type=int, default=40)
    parser.add_argument(
        "--source", action="append", default=None, help="probe only these source names"
    )
    args = parser.parse_args()
    out = DATA_DIR / "coverage_probe.json"
    result: dict = {}

    def save(name, record):
        result[name] = record
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp = out.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2))
        temp.replace(out)
        rows = ", ".join(str(p.get("rows", 0)) for p in record["probes"])
        print(
            f"{name}: {record.get('oldest_nonempty') or 'unavailable'} | probe rows newest->oldest: {rows}",
            flush=True,
        )

    probe_source_coverage(
        probes=max(2, min(args.probes, 16)),
        spacing_seconds=max(1, args.spacing_days) * 86400,
        progress=save,
        sources=args.source,
    )
    print(f"saved {len(result)} source results to {out}", flush=True)


if __name__ == "__main__":
    main()
