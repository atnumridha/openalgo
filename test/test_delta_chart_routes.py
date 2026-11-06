import importlib.util
import os
import tempfile
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import patch

from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf


class RouteTests(TestCase):
    def setUp(self):
        log_temp = tempfile.TemporaryDirectory()
        self.addCleanup(log_temp.cleanup)
        env_patch = patch.dict(
            os.environ,
            {"LOG_FORMAT": "%(message)s", "LOG_TO_FILE": "false", "LOG_DIR": log_temp.name},
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        source = Path(__file__).resolve().parents[1] / "blueprints/delta_chart.py"
        spec = importlib.util.spec_from_file_location("delta_chart_route_under_test", source)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.saved = []
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="delta-test-only", TESTING=True)
        CSRFProtect(self.app)
        self.app.register_blueprint(self.module.delta_chart_bp)
        self.app.add_url_rule("/csrf", view_func=lambda: jsonify(token=generate_csrf()))
        self.client = self.app.test_client()
        self.fake = SimpleNamespace(
            credentials=SimpleNamespace(save=lambda *args: self.saved.append(args)),
            plans=SimpleNamespace(lock=lambda *args: nullcontext()),
        )
        self.patcher = patch.object(self.module, "service", return_value=self.fake)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def login(self):
        with self.client.session_transaction() as s:
            s["logged_in"] = True
            s["user"] = "alice"
            s["login_time"] = datetime.now(UTC).isoformat()

    def test_connection_rejects_missing_csrf(self):
        self.login()
        response = self.client.post(
            "/delta-chart/api/connection",
            json={"api_key": "test-key", "api_secret": "test-secret"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved, [])

    def test_connection_payload_uses_api_key_and_secret(self):
        self.login()
        token = self.client.get("/csrf").json["token"]
        response = self.client.post(
            "/delta-chart/api/connection",
            json={"api_key": "test-key", "api_secret": "test-secret"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.saved, [("alice", "test-key", "test-secret")])
        self.assertNotIn("test-secret", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_connection_requires_session(self):
        token = self.client.get("/csrf").json["token"]
        response = self.client.post(
            "/delta-chart/api/connection",
            json={"api_key": "test-key", "api_secret": "test-secret"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.saved, [])

    def test_state_surfaces_safe_ip_allowlist_error(self):
        from services.delta_chart.service import exchange_error

        self.login()
        self.fake.state = lambda *args: (_ for _ in ()).throw(
            exchange_error(
                {"error": {"code": "ip_not_whitelisted_for_api_key", "key": "never-print-key"}}
            )
        )
        response = self.client.get(
            "/delta-chart/api/state?symbol=BTCUSD", headers={"Accept": "application/json"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["connected"])
        self.assertIn("server IP", response.json["message"])
        self.assertNotIn("never-print-key", response.text)

    def test_connection_safe_auth_error_is_actionable(self):
        from services.delta_chart.service import exchange_error

        self.login()
        token = self.client.get("/csrf").json["token"]
        self.fake.credentials.save = lambda *args: (_ for _ in ()).throw(
            exchange_error({"error": {"code": "ip_not_whitelisted_for_api_key"}})
        )
        response = self.client.post(
            "/delta-chart/api/connection",
            json={"api_key": "test-key", "api_secret": "secret-never-echo"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("server IP", response.json["message"])
        self.assertNotIn("secret-never-echo", response.text)

    def test_manage_requires_csrf_and_session(self):
        self.login()
        response = self.client.post(
            "/delta-chart/api/manage",
            json={"plan_id": "reviewed", "decision": "sync", "source_time": 123},
        )
        self.assertEqual(response.status_code, 400)

    def test_manage_passes_only_authenticated_user_to_backend(self):
        self.login()
        token = self.client.get("/csrf").json["token"]
        seen = []

        def manage(user, data):
            seen.append((user, data))
            return {
                "status": "pending",
                "message": "Owned entry resting",
                "plan_id": data["plan_id"],
                "plan_status": "awaiting_entry",
            }

        self.fake.manage = manage
        response = self.client.post(
            "/delta-chart/api/manage",
            json={"plan_id": "reviewed", "decision": "sync", "source_time": 123},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen[0][0], "alice")
        self.assertEqual(response.json["plan_status"], "awaiting_entry")

    def test_entry_requires_reviewed_automatic_stop_plan(self):
        self.login()
        token = self.client.get("/csrf").json["token"]
        response = self.client.post(
            "/delta-chart/api/action",
            json={"action": "entry", "request_id": "test"},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("stop", response.json["message"].lower())

    def test_adoption_payload_uses_authenticated_csrf_action_route(self):
        self.login()
        token = self.client.get("/csrf").json["token"]
        received = []
        self.fake.action = lambda user, data: (
            received.append((user, data))
            or {"status": "confirmed", "message": "Registered only", "plan_id": "plan"}
        )
        payload = {
            "action": "adopt",
            "position_version": "reviewed",
            "auto_protection": {"stop": 95, "target": 110},
        }
        response = self.client.post(
            "/delta-chart/api/action", json=payload, headers={"X-CSRFToken": token}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(received, [("alice", payload)])

    def test_ema_is_csrf_protected_and_never_starts_trading_service(self):
        self.login()
        self.assertEqual(
            self.client.post("/delta-chart/api/ema", json={"candles": []}).status_code, 400
        )
        token = self.client.get("/csrf").json["token"]
        response = self.client.post(
            "/delta-chart/api/ema",
            json={"candles": [{"time": i * 60, "close": 100 + i} for i in range(16)]},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["ema"]["9"]["points"][0]["value"], 104)
        self.module.service.assert_not_called()
        response = self.client.post(
            "/delta-chart/api/ema",
            json={"candles": [{"time": 1, "close": -1}]},
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 400)

    def test_ema_route_returns_closed_triple_events_and_rejects_gaps(self):
        from test_delta_three_ema import fixture
        candles, _ = fixture()
        candles = [dict(b, time=b['time']-1_000_000_000) for b in candles]
        self.login()
        token = self.client.get('/csrf').json['token']
        headers = {'X-CSRFToken': token}
        response = self.client.post('/delta-chart/api/ema',
            json={'candles': candles, 'interval_seconds': 60}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['ema']['alignment_crosses']), 1)
        self.assertEqual(response.json['ema']['alignment_crosses'][0]['side'], 'up')
        del candles[30]
        response = self.client.post('/delta-chart/api/ema',
            json={'candles': candles, 'interval_seconds': 60}, headers=headers)
        self.assertEqual(response.status_code, 400)

    def test_ema_route_session_gap_policy_is_explicit_and_boolean(self):
        from test_delta_three_ema import fixture
        candles, _ = fixture()
        candles = [dict(b, time=b['time']-1_000_000_000+(86400 if i >= 60 else 0))
                   for i, b in enumerate(candles)]
        self.login()
        token = self.client.get('/csrf').json['token']
        headers = {'X-CSRFToken': token}
        for policy, expected in [(False, 400), ('true', 400), (True, 200)]:
            response = self.client.post('/delta-chart/api/ema',
                json={'candles': candles, 'interval_seconds': 60, 'allow_session_gaps': policy},
                headers=headers)
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertEqual(len(response.json['ema']['alignment_crosses']), 1)


class AutomationRouteTests(RouteTests):
    def test_automation_requires_session_and_csrf(self):
        self.fake.automation=SimpleNamespace(configure=lambda *a: self.saved.append(a))
        response=self.client.post('/delta-chart/api/automation',json={'enabled':True})
        self.assertIn(response.status_code,(400,401))
        self.assertEqual(self.saved,[])
    def test_automation_is_bound_to_authenticated_user(self):
        self.login();token=self.client.get('/csrf').json['token']
        self.fake.automation=SimpleNamespace(configure=lambda user,data: self.saved.append((user,data)) or {'owner':'backend','enabled':False})
        body={'account':'a','symbol':'BTCUSD','enabled':False,'user':'foreign'}
        response=self.client.post('/delta-chart/api/automation',json=body,headers={'X-CSRFToken':token})
        self.assertEqual(response.status_code,200);self.assertEqual(self.saved[0][0],'alice')
