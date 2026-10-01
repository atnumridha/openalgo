"""Offline CLI regressions; no application, credentials, or broker calls."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ema_3m_scalper.py"


def invoke(*args):
    env = os.environ.copy()
    env.pop("OPENALGO_API_KEY", None)
    env.pop("OPENALGO_HOST", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )


@pytest.fixture
def inputs(tmp_path):
    index = pd.date_range("2026-01-02 09:15", periods=375, freq="min", tz="Asia/Kolkata")
    candles = tmp_path / "minutes.csv"
    pd.DataFrame(
        {"timestamp": index, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
    ).to_csv(candles, index=False)
    costs = tmp_path / "costs.json"
    costs.write_text(
        json.dumps(
            {
                "schedule_id": "Explicit offline fixture",
                "source": "Synthetic fees, not broker charges",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "broker": "kotak",
                "exchange": "NFO",
                "slippage_bps": 10,
                "brokerage_per_order": 20,
                "exchange_rate": 0.00035,
                "sebi_rate": 0.000001,
                "gst_rate": 0.18,
                "stamp_buy_rate": 0.00003,
                "stt_sell_rate": 0.001,
            }
        )
    )
    return candles, costs


def arguments(inputs, output, *, as_of=True):
    candles, costs = inputs
    args = [
        "--candles",
        candles,
        "--lot-size",
        "65",
        "--tick-size",
        "0.05",
        "--costs",
        costs,
        "--output",
        output,
    ]
    if as_of:
        args.extend(["--as-of", "2026-01-02T15:40:00+05:30"])
    return args


def test_help_explains_paper_only_and_needs_no_credentials():
    result = invoke("--help")
    assert result.returncode == 0, result.stderr
    assert "PAPER" in result.stdout
    assert "--as-of" in result.stdout and "--fetch-openalgo" in result.stdout


def test_compare_writes_valid_empty_research_reports(inputs, tmp_path):
    output = tmp_path / "report"
    result = invoke(*arguments(inputs, output))
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["mode"] == "PAPER" and report["live_eligible"] is False
    assert set(report["variants"]) == {"crossover", "pullback"}
    for replay in report["variants"].values():
        assert replay["trades"] == []
        assert replay["summary"]["trade_count"] == 0
        assert replay["summary"]["net_pnl"] == 0
    assert result.stdout.count("PAPER ") == 2
    assert pd.read_csv(output / "trades.csv").empty
    assert pd.read_csv(output / "rejections.csv").empty
    assert report["costs"]["brokerage_per_order"] == 20
    assert report["config"]["max_trade_loss"] == 500
    for filename in ("report.json", "trades.csv", "rejections.csv"):
        assert ((output / filename).stat().st_mode & 0o777) == 0o600


def test_csv_requires_explicit_aware_as_of(inputs, tmp_path):
    missing = invoke(*arguments(inputs, tmp_path / "missing", as_of=False))
    assert missing.returncode != 0 and "--as-of" in missing.stderr
    args = arguments(inputs, tmp_path / "naive", as_of=False)
    naive = invoke(*args, "--as-of", "2026-01-02T15:40:00")
    assert naive.returncode != 0 and "timezone" in naive.stderr.lower()


@pytest.mark.parametrize(
    "change, expected",
    [
        ("naive_timestamp", "timezone"),
        ("missing_close", "close"),
        ("bad_ohlc", "OHLC"),
    ],
)
def test_malformed_candles_fail_without_writing_report(inputs, tmp_path, change, expected):
    candles, _ = inputs
    data = pd.read_csv(candles)
    if change == "naive_timestamp":
        data["timestamp"] = pd.to_datetime(data.timestamp).dt.tz_localize(None)
    elif change == "missing_close":
        data = data.drop(columns="close")
    else:
        data.loc[0, "high"] = 1
    data.to_csv(candles, index=False)
    output = tmp_path / "bad-report"
    result = invoke(*arguments(inputs, output))
    assert result.returncode != 0 and expected.lower() in result.stderr.lower()
    assert not output.exists()


@pytest.mark.parametrize("change", ["missing_rate", "expired_dates", "wrong_exchange"])
def test_invalid_cost_evidence_is_rejected(inputs, tmp_path, change):
    _, path = inputs
    costs = json.loads(path.read_text())
    if change == "missing_rate":
        del costs["stt_sell_rate"]
    elif change == "expired_dates":
        costs["effective_to"] = "2026-01-01"
    else:
        costs["exchange"] = "BFO"
    path.write_text(json.dumps(costs))
    output = tmp_path / "bad-costs"
    result = invoke(*arguments(inputs, output))
    assert result.returncode != 0 and "cost" in result.stderr.lower()
    assert not output.exists()


def test_single_variant_and_overrides_are_reported(inputs, tmp_path):
    output = tmp_path / "single"
    result = invoke(
        *arguments(inputs, output),
        "--variant",
        "pullback",
        "--capital",
        "12000",
        "--max-trade-loss",
        "300",
        "--max-daily-loss",
        "900",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "report.json").read_text())
    assert set(report["variants"]) == {"pullback"}
    assert report["config"]["capital"] == 12000
    assert report["config"]["max_trade_loss"] == 300
    assert report["config"]["max_daily_loss"] == 900


def test_required_contract_metadata_cannot_be_silently_defaulted(inputs, tmp_path):
    candles, costs = inputs
    result = invoke(
        "--candles",
        candles,
        "--as-of",
        "2026-01-02T15:40:00+05:30",
        "--costs",
        costs,
        "--output",
        tmp_path / "no-lot",
    )
    assert result.returncode != 0
    assert "--lot-size" in result.stderr and "--tick-size" in result.stderr


def test_output_cannot_overwrite_code_or_an_existing_report(inputs, tmp_path):
    within_code = invoke(*arguments(inputs, ROOT / "reports/unsafe-cli-test"))
    assert within_code.returncode != 0 and "outside" in within_code.stderr.lower()
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep")
    existing = invoke(*arguments(inputs, output))
    assert existing.returncode != 0 and sentinel.read_text() == "keep"


def load_script():
    spec = importlib.util.spec_from_file_location("ema_3m_scalper_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remote_host_rejected_before_sdk_or_credential_access(monkeypatch):
    module = load_script()
    monkeypatch.setenv("OPENALGO_HOST", "https://remote.example")
    monkeypatch.setenv("OPENALGO_API_KEY", "test-secret-never-disclose")
    with pytest.raises(ValueError, match="loopback"):
        module.fetch_history("NIFTY_TEST_PE", "NFO", "2026-01-01", "2026-01-02")


def test_fetch_uses_only_history_and_captures_cutoff_before_request(monkeypatch):
    module = load_script()
    monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5001")
    monkeypatch.setenv("OPENALGO_API_KEY", "test-secret-never-disclose")
    before = pd.Timestamp.now(tz="UTC")
    request_at = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def history(self, **kwargs):
            assert kwargs == {
                "symbol": "NIFTY_TEST_PE",
                "exchange": "NFO",
                "interval": "1m",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
            request_at.append(pd.Timestamp.now(tz="UTC"))
            return pd.DataFrame(
                {"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]},
                index=pd.DatetimeIndex(["2026-01-02T09:15:00+05:30"]),
            )

        def __getattr__(self, name):
            raise AssertionError(f"Unexpected SDK method {name}")

    def client_factory(**kwargs):
        assert kwargs["host"] == "http://127.0.0.1:5001"
        return Client()

    monkeypatch.setitem(sys.modules, "openalgo", SimpleNamespace(api=client_factory))
    frame, as_of = module.fetch_history("NIFTY_TEST_PE", "NFO", "2026-01-01", "2026-01-02")
    assert len(frame) == 1 and frame.index.tz is not None
    assert before <= as_of <= request_at[0]


def test_fetch_failure_does_not_echo_api_key(monkeypatch):
    module = load_script()
    secret = "test-secret-never-disclose"
    monkeypatch.setenv("OPENALGO_HOST", "http://localhost:5001")
    monkeypatch.setenv("OPENALGO_API_KEY", secret)

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def history(self, **kwargs):
            raise RuntimeError(f"upstream contained {secret}")

    monkeypatch.setitem(sys.modules, "openalgo", SimpleNamespace(api=lambda **kwargs: Client()))
    with pytest.raises(ValueError) as caught:
        module.fetch_history("NIFTY_TEST_PE", "NFO", "2026-01-01", "2026-01-02")
    assert secret not in str(caught.value)


@pytest.mark.parametrize("fail", [False, True])
def test_real_sdk_http_client_is_closed_after_history_on_every_path(monkeypatch, fail):
    # Stub only the external history call; the SDK allocates/closes its real pool.
    from openalgo import api

    module = load_script()
    monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5001")
    monkeypatch.setenv("OPENALGO_API_KEY", "offline-resource-test-key")
    allocated = []

    def history(client, **kwargs):
        allocated.append(client.client)
        assert not client.client.is_closed
        if fail:
            raise RuntimeError("offline history failure")
        return pd.DataFrame(
            {"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]},
            index=pd.DatetimeIndex(["2026-01-02T09:15:00+05:30"]),
        )

    monkeypatch.setattr(api, "history", history)
    try:
        if fail:
            with pytest.raises(ValueError, match="history request failed"):
                module.fetch_history("NIFTY_TEST_PE", "NFO", "2026-01-01", "2026-01-02")
        else:
            frame, _ = module.fetch_history("NIFTY_TEST_PE", "NFO", "2026-01-01", "2026-01-02")
            assert len(frame) == 1
        assert len(allocated) == 1 and allocated[0].is_closed
    finally:
        for client in allocated:
            client.close()
