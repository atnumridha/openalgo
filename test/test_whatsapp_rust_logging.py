"""Regression coverage for WhatsApp Rust logging during application startup."""

from pathlib import Path

from utils import env_check


def test_whatsapp_rust_logging_uses_quiet_default(monkeypatch):
    monkeypatch.delenv("RUST_LOG", raising=False)

    env_check.configure_whatsapp_rust_logging()

    value = env_check.WHATSAPP_RUST_LOG_DEFAULT
    assert "whatsapp_rust::message=off" in value
    assert "wacore_libsignal::protocol::session_cipher=off" in value
    assert value == env_check.os.environ["RUST_LOG"]


def test_whatsapp_rust_logging_preserves_operator_override(monkeypatch):
    monkeypatch.setenv("RUST_LOG", "debug")

    env_check.configure_whatsapp_rust_logging()

    assert env_check.os.environ["RUST_LOG"] == "debug"


def test_application_configures_rust_logging_before_heavy_imports():
    source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")

    configured = source.index("configure_whatsapp_rust_logging()")
    flask_import = source.index("from flask import Flask")

    assert configured < flask_import


def test_wars_client_defaults_to_silent_native_logging(monkeypatch):
    from services import whatsapp_bot_service

    monkeypatch.delenv("WHATSAPP_RUST_LOG_LEVEL", raising=False)

    assert whatsapp_bot_service._wars_log_level() == "off"


def test_wars_client_allows_explicit_diagnostic_level(monkeypatch):
    from services import whatsapp_bot_service

    monkeypatch.setenv("WHATSAPP_RUST_LOG_LEVEL", "debug")
    assert whatsapp_bot_service._wars_log_level() == "debug"

    monkeypatch.setenv("WHATSAPP_RUST_LOG_LEVEL", "not-a-level")
    assert whatsapp_bot_service._wars_log_level() == "off"
