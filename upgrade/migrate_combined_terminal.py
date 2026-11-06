#!/usr/bin/env python3
"""Add combined-terminal tables without changing broker/account records."""
import argparse
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def migrate(engine,status=False):
    from sqlalchemy import inspect
    from database.combined_terminal_db import Base
    missing=[name for name in Base.metadata.tables if not inspect(engine).has_table(name)]
    if not status:Base.metadata.create_all(engine)
    return missing


def main():
    from dotenv import load_dotenv
    from database.engine_factory import create_db_engine
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status',action='store_true')
    args=parser.parse_args()
    url=os.getenv('DATABASE_URL','')
    if url.startswith('sqlite:///') and not url.startswith('sqlite:////'):
        url='sqlite:///'+str(ROOT/url[len('sqlite:///'):])
    engine=create_db_engine(url)
    try:
        missing=migrate(engine,args.status)
        print('Combined terminal tables required: '+str(len(missing)) if args.status else 'Combined terminal tables ready')
    finally:engine.dispose()

if __name__=='__main__':main()
