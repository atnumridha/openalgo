"""Run one bounded offline worker: python -m services.research.worker [--once]."""

import argparse
import json
import logging
import os
import signal
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Process at most one queued job, then exit"
    )
    parser.add_argument(
        "--ready-file", type=Path, help="Optional local supervisor readiness file (removed on exit)"
    )
    args = parser.parse_args()
    load_dotenv()
    # Store engines must read configuration after dotenv, including standalone use.
    from database.trading_research_db import ResearchStore
    from services.research.jobs import Cancelled, process_job

    store = ResearchStore()
    store.init_db()
    token = uuid.uuid4().hex
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    published = False
    try:
        if not store.acquire_worker(token):
            raise SystemExit("Another research worker is active.")
        if args.ready_file:
            temporary = args.ready_file.with_suffix(".tmp")
            temporary.write_text(json.dumps({"pid": os.getpid()}))
            temporary.chmod(0o600)
            temporary.replace(args.ready_file)
            published = True
        while not stopping:
            if not store.heartbeat(token):
                raise SystemExit("Research worker lease expired.")
            run = store.claim_job(token)
            if run:
                try:
                    process_job(store, token, run, should_stop=lambda: stopping)
                except Cancelled:
                    pass
                except Exception:
                    logging.exception("Research run %s failed", run["id"])
            if args.once:
                break
            if not run:
                time.sleep(2)
    finally:
        try:
            try:
                if published:
                    args.ready_file.unlink(missing_ok=True)
            finally:
                store.release_worker(token)
        finally:
            store.engine.dispose()


if __name__ == "__main__":
    main()
