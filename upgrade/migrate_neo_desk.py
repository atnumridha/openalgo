"""Idempotent additive native Neo Desk provider tables."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv()
from database.neo_desk_db import init_db

from database.neo_history_db import init_db as init_history

if __name__ == "__main__":
    init_db()
    init_history()
