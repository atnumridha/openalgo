import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from services.delta_chart.connection import Connections
from services.delta_chart.service import DeltaError, Store


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "connection.db")
        self.cipher = Fernet(Fernet.generate_key())
        auth = SimpleNamespace(
            encrypt_token=lambda text: self.cipher.encrypt(text.encode()).decode()
        )
        self.patch = patch.dict("sys.modules", {"database.auth_db": auth})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_candidate_is_verified_before_encrypted_save(self):
        with patch("services.delta_chart.service.Client") as client:
            client.return_value.request.return_value = {"id": 1}
            Connections(self.store).save("alice", "test-api-key", "test-api-secret")
        with self.store.db() as db:
            value = db.execute("SELECT value FROM credentials WHERE user=?", ("alice",)).fetchone()[
                "value"
            ]
        self.assertNotIn("test-api-secret", value)
        self.assertIn("test-api-secret", self.cipher.decrypt(value).decode())

    def test_failed_candidate_preserves_previous_credentials(self):
        with self.store.db() as db:
            db.execute(
                "INSERT INTO credentials VALUES(?,?)", ("alice", "previous-encrypted-credential")
            )
        with patch("services.delta_chart.service.Client") as client:
            client.return_value.request.side_effect = DeltaError("Safe verification failure")
            with self.assertRaises(DeltaError):
                Connections(self.store).save("alice", "test-api-key", "test-api-secret")
        with self.store.db() as db:
            self.assertEqual(
                db.execute("SELECT value FROM credentials WHERE user=?", ("alice",)).fetchone()[
                    "value"
                ],
                "previous-encrypted-credential",
            )
