"""Run from the installation root with its private environment loaded."""

import argparse, json
from pathlib import Path
from services.neo_desk.migration import migrate_archive, backup_runtime

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.backup:
        backup_runtime(args.source.parent, args.backup)
    print(json.dumps(migrate_archive(args.source, args.owner, args.dry_run), indent=2))
