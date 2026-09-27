"""Download/resume official daily NSE options history without broker access."""

import argparse
import os
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from services.research import nse_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=nse_archive.START)
    parser.add_argument(
        "--end", type=date.fromisoformat, default=nse_archive.today() - timedelta(days=1)
    )
    parser.add_argument("--output", type=Path, default=nse_archive.ROOT)
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="Recheck unavailable dates before their daily cache expires",
    )
    parser.add_argument("--requested-at", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    # This isolated process never loads broker credentials or the app's databases.
    os.environ["LOG_FORMAT"] = "%(levelname)s %(message)s"
    from utils.httpx_client import get_httpx_client
    from utils.logging import get_logger

    logger = get_logger(__name__)
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    client = get_httpx_client()
    try:
        logger.info(
            "Downloading NSE daily history from %s through %s. Progress appears in Research.",
            args.start,
            args.end,
        )
        # Finite standalone worker, not the eventlet web process. All threads are joined on exit.
        with ThreadPoolExecutor(max_workers=3) as downloads:
            result = nse_archive.sync(
                args.output,
                args.start,
                args.end,
                client=client,
                should_stop=lambda: stopping,
                retry_missing=args.retry_missing,
                executor=downloads,
                requested_at=args.requested_at,
            )
        logger.info(
            "NSE history: %s; %s sessions, %s unavailable dates, %s errors.",
            result["status"],
            result["session_count"],
            result["unavailable_count"],
            result["error_count"],
        )
        return (
            0
            if result["status"] in ("completed", "completed_with_gaps")
            and not result["error_count"]
            else 1
        )
    except Exception:
        logger.exception("NSE history download stopped; saved sessions can be resumed.")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
