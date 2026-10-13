from datetime import timedelta

from conftest import when

from services.neo_desk.runner import closed_bars, should_evaluate


def test_runner_uses_closed_bars_and_never_catches_up():
    data = [
        {"timestamp": when("09:15").timestamp(), "open": 100, "high": 101, "low": 99, "close": 100},
        {"timestamp": when("09:30").timestamp(), "open": 100, "high": 104, "low": 99, "close": 103},
    ]
    assert len(closed_bars(data, when("09:40"))) == 1
    assert len(closed_bars(data, when("09:45"))) == 2
    assert should_evaluate(when("09:45"), None)
    assert not should_evaluate(when("09:45") + timedelta(seconds=6), None)
    assert not should_evaluate(when("09:45"), when("09:45"))
    assert not should_evaluate(when("15:30"), None)


def test_unordered_or_uncertain_history_is_refused():
    data = [
        {
            "timestamp": when("09:30").timestamp(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "repaired": True,
        }
    ]
    assert closed_bars(data, when("09:45")) == []


def test_hosted_runner_defaults_to_the_configured_instance_not_port_5000():
    from pathlib import Path
    import ast

    tree = ast.parse(Path("blueprints/python_strategy.py").read_text())
    # Exercise the actual host-environment expression without starting a subprocess.
    import os
    from unittest.mock import patch

    expression = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setdefault"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "OPENALGO_HOST"
    )
    namespace = {"strategy_env": {}, "os": os}
    with patch.dict(os.environ, {"HOST_SERVER": "http://127.0.0.1:5001"}, clear=True):
        exec(compile(ast.Expression(expression), "<native-host-env>", "eval"), namespace)
    assert namespace["strategy_env"]["OPENALGO_HOST"] == "http://127.0.0.1:5001"


def test_dead_runner_registry_record_does_not_report_running(monkeypatch):
    from blueprints import python_strategy as host
    from services.neo_desk.runner_host import NativeRunnerHost

    runner = NativeRunnerHost()
    sid = runner.identity("dead-fixture")

    class Dead:
        def poll(self):
            return 1

    monkeypatch.setitem(host.RUNNING_STRATEGIES, sid, {"process": Dead(), "pid": 0})
    assert not runner.status("dead-fixture")["running"]
