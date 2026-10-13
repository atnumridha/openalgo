"""Read-only source migration, private backups and public reconciliation metadata."""

from pathlib import Path
from hashlib import sha256
import json, sqlite3, shutil
from .history import ingest_fills, history_page
from .history_accounting import _normalized, TradeArchive


def migrate_archive(source, owner_id, dry_run=False):
    source = Path(source).resolve()
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        version = c.execute("PRAGMA user_version").fetchone()[0]
        raw = [dict(row) for row in c.execute("SELECT * FROM fills")]
    accounts = {f.get("account_key") for f in raw if f.get("account_key")}
    if len(accounts) > 1:
        raise ValueError(
            "Multiple source accounts require an explicit partition; nothing imported."
        )
    rows = [
        _normalized(f, True)
        | {
            "provenance": json.loads(f["provenance"])
            if isinstance(f.get("provenance"), str)
            else f.get("provenance", [])
        }
        for f in raw
    ]
    manifest = dict(
        schema_version=1,
        source_sha256=sha256(source.read_bytes()).hexdigest(),
        source_schema=version,
        source_fills=len(rows),
        source_quantity=sum(f["quantity"] for f in rows),
        dry_run=dry_run,
    )
    if not dry_run:
        manifest.update(ingest_fills(owner_id, rows, source="preserved_archive"))
    manifest["destination_fills"] = history_page(owner_id)["coverage"]["fill_count"]
    return manifest


def backup_runtime(source, destination):
    source = Path(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    manifest = []
    for name in ("journal.sqlite", "broker-trades.sqlite"):
        original = source / name
        target = destination / name
        if not original.exists():
            continue
        with (
            sqlite3.connect(original.as_uri() + "?mode=ro", uri=True) as src,
            sqlite3.connect(target) as dst,
        ):
            src.backup(dst)
        target.chmod(0o600)
        manifest.append(
            dict(
                path=name,
                sha256=sha256(target.read_bytes()).hexdigest(),
                size=target.stat().st_size,
            )
        )
    for name in ("data", "reports"):
        if (source / name).exists():
            shutil.copytree(source / name, destination / name, dirs_exist_ok=True)
    for name in ("data", "reports"):
        for file in (destination / name).rglob("*"):
            if file.is_file():
                file.chmod(0o600)
                manifest.append(
                    dict(
                        path=str(file.relative_to(destination)),
                        sha256=sha256(file.read_bytes()).hexdigest(),
                        size=file.stat().st_size,
                    )
                )
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (destination / "manifest.json").chmod(0o600)
    return dict(files=len(manifest), bytes=sum(f["size"] for f in manifest))
