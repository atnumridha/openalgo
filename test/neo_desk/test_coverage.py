import json
from hashlib import sha256

import pytest

from services.neo_desk.datasets import list_datasets, load_dataset


@pytest.fixture(autouse=True)
def isolated_download_archive(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ARCHIVE_ROOT", tmp_path / "downloaded")


def archive(tmp_path, name="valid", index_kind="index_15m", missing_options=False):
    folder = tmp_path / name
    folder.mkdir()
    index = "time,open,high,low,close\n2026-09-16T09:15:00+05:30,100,101,99,100\n"
    option = "instrument_id,time,open,high,low,close\nc0,2026-09-16T09:15:00+05:30,50,51,49,50\n"
    (folder / "index.csv").write_text(index)
    if not missing_options:
        (folder / "options.csv").write_text(option)
    manifest = {
        "kind": "ohlc_1m",
        "source": {"synthetic": False},
        "calendar_start": "2026-09-10",
        "calendar_end": "2026-10-09",
        "calendar": ["2026-09-16"],
        "expiry_calendar": ["2026-10-13"],
        "contracts": [
            {
                "id": "c0",
                "symbol": "NIFTY26O1322500CE",
                "exchange": "nse_fo",
                "expiry": "2026-10-13",
                "strike": "22500",
                "option_type": "CE",
                "lot_size": 65,
                "tick_size": "0.05",
                "valid_from": "2026-09-10",
                "valid_to": "2026-10-09",
            }
        ],
        "files": [
            {"kind": index_kind, "path": "index.csv", "sha256": sha256(index.encode()).hexdigest()},
            {
                "kind": "option_1m",
                "path": "options.csv",
                "sha256": sha256(option.encode()).hexdigest(),
            },
        ],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder, manifest


def test_unknown_dataset_and_traversal_are_refused():
    with pytest.raises(ValueError):
        load_dataset("../../.env")


def test_real_registry_never_advertises_synthetic_profit_fixtures():
    assert all(not x["source"].get("synthetic", False) for x in list_datasets())


def test_registry_requires_supported_timeframes_with_a_valid_control(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path)
    archive(tmp_path)
    archive(tmp_path, "wrong-frame", "index_5m")
    folder, m = archive(tmp_path, "no-options")
    m["files"] = m["files"][:1]
    (folder / "manifest.json").write_text(json.dumps(m))
    assert [x["id"] for x in list_datasets()] == ["valid"]


def test_registry_does_not_offer_a_manifest_with_missing_actual_files(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path)
    archive(tmp_path)
    archive(tmp_path, "missing-file", missing_options=True)
    assert [x["id"] for x in list_datasets()] == ["valid"]


def test_checksum_mismatch_refuses_loading(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path)
    folder, _ = archive(tmp_path)
    (folder / "options.csv").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_dataset("valid")


def test_contract_observations_respect_historical_validity(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path)
    folder, m = archive(tmp_path)
    m["contracts"][0]["valid_from"] = "2026-09-17"
    (folder / "manifest.json").write_text(json.dumps(m))
    dataset = load_dataset("valid")
    assert dataset.options["NIFTY26O1322500CE"] == {}


def test_new_broker_archive_loads_without_modifying_migration_backup(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path / "backup")
    monkeypatch.setattr(
        "services.neo_desk.datasets.ARCHIVE_ROOT", tmp_path / "current", raising=False
    )
    (tmp_path / "backup").mkdir()
    (tmp_path / "current").mkdir()
    archive(tmp_path / "backup", "older")
    archive(tmp_path / "current", "newer")
    assert {d["id"] for d in list_datasets()} == {"older", "newer"}
    assert len(load_dataset("newer").index) == 1


def test_duplicate_archive_identity_is_not_silently_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr("services.neo_desk.datasets.ROOT", tmp_path / "backup")
    monkeypatch.setattr(
        "services.neo_desk.datasets.ARCHIVE_ROOT", tmp_path / "current", raising=False
    )
    (tmp_path / "backup").mkdir()
    (tmp_path / "current").mkdir()
    archive(tmp_path / "backup", "same")
    archive(tmp_path / "current", "same")
    assert list_datasets() == []
    with pytest.raises(ValueError):
        load_dataset("same")
