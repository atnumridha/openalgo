"""Review a bounded local JSON evidence file without account or broker access."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.kotak_assistant.setup_review import review_setups

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = {
    "one": 20000,
    "five": 20000,
    "events": 250000,
    "option_history": 100000,
    "roundtrips": 20000,
    "baseline_roundtrips": 20000,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="Local JSON with one/five/events, now and session coordinates"
    )
    args = parser.parse_args(argv)
    try:
        with args.input.open("rb") as source:
            content = source.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("The review file must be at most 20 MiB")
        values = json.loads(content)
        if not isinstance(values, dict):
            raise ValueError("The review file must contain an evidence object")
        for key, limit in MAX_ROWS.items():
            rows = values.get(key, [])
            if (
                not isinstance(rows, list)
                or len(rows) > limit
                or any(not isinstance(row, dict) for row in rows)
            ):
                raise ValueError(f"{key} must be a bounded list of observation objects")
        required = ("one", "five", "events", "now", "session_start", "session_id")
        if any(key not in values for key in required):
            raise ValueError(
                "The review file requires candles, events, cursor and session coordinates"
            )
        allowed = (*required, "option_history", "roundtrips", "baseline_roundtrips")
        result = review_setups(**{key: values[key] for key in allowed if key in values})
        sys.stdout.write(json.dumps(result, allow_nan=False, indent=2) + "\n")
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
