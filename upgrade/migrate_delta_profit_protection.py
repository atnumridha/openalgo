#!/usr/bin/env python3
"""Idempotent Delta protection table migration; --status never changes data."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def migrate(engine, status=False):
    from sqlalchemy import inspect
    from services.delta_profit_guard import Protection
    exists = inspect(engine).has_table(Protection.__tablename__)
    if not exists and not status:
        Protection.__table__.create(engine, checkfirst=True)
    return exists


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    from database.engine_factory import create_db_engine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    url = os.getenv('DATABASE_URL', '')
    if url.startswith('sqlite:///') and not url.startswith('sqlite:////'):
        url = 'sqlite:///' + str(ROOT / url[len('sqlite:///'):])
    engine = create_db_engine(url)
    try:
        existed = migrate(engine, args.status)
        print('Delta protection table present' if existed else 'Delta protection table required' if args.status else 'Delta protection table created')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
