import hashlib
import os
import tempfile
import unittest
from datetime import timedelta

import backend.main as api


class TelefostApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        api.DB_PATH = os.path.join(self.tmp.name, "telefost.sqlite3")
        api.BOT_TOKEN = "test-token"
        api.ADMIN_TOKEN = "test-admin-token"
        api.init_db()
        with api.database() as con:
            con.execute(
                "INSERT INTO users(id, username) VALUES(?, ?)",
                (123456, "test_user"),
            )
            con.execute(
                "INSERT INTO numbers(number, owner, code) VALUES(?, ?, '')",
                ("+79123456789", 123456),
            )
        self.sent = []
        self.original_sender = api.send_bot_message
        api.send_bot_message = lambda chat_id, message: self.sent.append((chat_id, message))

    def tearDown(self):
        api.send_bot_message = self.original_sender
        self.tmp.cleanup()

    def test_only_plus79_format_is_accepted(self):
        self.assertEqual(api.normalize_phone("+79123456789"), "+79123456789")
        with self.assertRaises(Exception):
            api.normalize_phone("+70123456789")

    def test_code_goes_to_number_owner_and_is_single_use(self):
        result = api.request_code(api.CodeRequest(phone="+79123456789"))
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], 123456)
        code = self.sent[0][1].split("Код входа в Telefost: ", 1)[1][:6]
        self.assertEqual(len(code), 6)
        session = api.verify_code(api.CodeVerify(phone="+79123456789", code=code))
        self.assertTrue(session["access_token"])
        self.assertEqual(session["user"]["stars"], 1000)
        with self.assertRaises(Exception):
            api.verify_code(api.CodeVerify(phone="+79123456789", code=code))

    def test_code_hash_is_stored_not_plaintext(self):
        code = "123456"
        with api.database() as con:
            con.execute(
                "INSERT INTO auth_codes(phone, code_hash, expires_at, requested_at) VALUES(?,?,?,?)",
                ("+79123456789", hashlib.sha256(code.encode()).hexdigest(),
                 api.iso(api.now() + timedelta(minutes=5)), api.iso(api.now())),
            )
            row = con.execute("SELECT code_hash FROM auth_codes WHERE phone=?",
                              ("+79123456789",)).fetchone()
        self.assertNotEqual(row["code_hash"], code)


if __name__ == "__main__":
    unittest.main()
