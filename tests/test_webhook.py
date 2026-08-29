"""The webhook endpoints, driven through the real FastAPI app.

Only dependencies already in requirements.txt are used (fastapi + httpx supply
TestClient), so this still runs with `python -m unittest` and nothing to install.

Configuration is read once at import time, so the environment has to be set
before `app.main` is imported - hence the assignments above the app import.
"""

import hashlib
import hmac
import json
import os
import unittest

SECRET = "unit-test-app-secret"
VERIFY_TOKEN = "unit-test-verify-token"

os.environ["META_APP_SECRET"] = SECRET
os.environ["WHATSAPP_VERIFY_TOKEN"] = VERIFY_TOKEN
os.environ["ALLOW_UNSIGNED_WEBHOOK"] = "false"
os.environ["DEFAULT_LANGUAGE"] = "he"
# No WHATSAPP_TOKEN / WHATSAPP_PHONE_ID: the app stays in dry-run and these
# tests never touch the network.

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def start_client(test_class) -> TestClient:
    """A TestClient entered as a context manager, torn down with the class.

    Entering it is what runs the app lifespan, and the lifespan is what loads
    the answer book into app.state. A bare TestClient(app) skips it, so every
    inbound message would fail on a missing app.state.faq - a 500 that says
    nothing about the code under test.

    raise_server_exceptions=False so an unhandled exception surfaces as the 500
    a real client would see, rather than a traceback that hides the request.
    """
    context = TestClient(app, raise_server_exceptions=False)
    client = context.__enter__()
    test_class.addClassCleanup(context.__exit__, None, None, None)
    return client


def sign(raw: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def message_payload(text: str, message_id: str) -> bytes:
    body = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "0", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "messages": [{"from": "972500000000", "id": message_id,
                          "timestamp": "0", "type": "text",
                          "text": {"body": text}}],
        }}]}],
    }
    return json.dumps(body).encode("utf-8")


class VerificationHandshakeTest(unittest.TestCase):
    """Meta's GET handshake, and what a stranger poking the URL gets."""

    @classmethod
    def setUpClass(cls):
        cls.client = start_client(cls)

    def _get(self, token, mode="subscribe", challenge="1158201444"):
        return self.client.get("/webhook", params={
            "hub.mode": mode, "hub.verify_token": token, "hub.challenge": challenge})

    def test_correct_token_echoes_the_challenge_as_plain_text(self):
        response = self._get(VERIFY_TOKEN)
        self.assertEqual(response.status_code, 200)
        # Not '"1158201444"' - a JSON-wrapped body fails Meta's check with an
        # error message that does not say why.
        self.assertEqual(response.text, "1158201444")
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))

    def test_wrong_token_is_rejected(self):
        self.assertEqual(self._get("not-the-token").status_code, 403)

    def test_wrong_mode_is_rejected(self):
        self.assertEqual(self._get(VERIFY_TOKEN, mode="unsubscribe").status_code, 403)

    def test_non_ascii_token_is_rejected_not_a_server_error(self):
        # Regression: hmac.compare_digest raises TypeError on a str containing
        # non-ASCII, and this parameter comes from whoever calls the URL. As a
        # str comparison, one curl with a Hebrew token turned a public endpoint
        # into a 500. It must be an ordinary 403.
        #
        # Written as escapes, like the other test data here: Hebrew and Arabic
        # literals flip the direction of a source line in most editors, and a
        # failure message printed on a terminal without those fonts is
        # unreadable. In order: Hebrew "abg", "cafe" with an accent, Arabic
        # "ahlan".
        tokens = {
            "hebrew": "\u05D0\u05D1\u05D2",
            "accented_latin": "caf\u00E9",
            "arabic": "\u0623\u0647\u0644\u0627",
        }
        for name, token in tokens.items():
            with self.subTest(token=name):
                self.assertEqual(self._get(token).status_code, 403)


class InboundPostTest(unittest.TestCase):
    """Signature enforcement and the reply path, without sending anything."""

    @classmethod
    def setUpClass(cls):
        cls.client = start_client(cls)

    def test_unsigned_post_is_refused(self):
        raw = message_payload("hours", "wamid.unsigned")
        self.assertEqual(self.client.post("/webhook", content=raw).status_code, 403)

    def test_post_signed_with_the_wrong_secret_is_refused(self):
        raw = message_payload("hours", "wamid.wrongsecret")
        response = self.client.post(
            "/webhook", content=raw,
            headers={"X-Hub-Signature-256": sign(raw, "someone-elses-secret")})
        self.assertEqual(response.status_code, 403)

    def test_non_ascii_signature_header_is_refused_not_a_server_error(self):
        # Header bytes are decoded as latin-1 before they reach the app, so a
        # high-byte header arrives as a non-ASCII str.
        raw = message_payload("hours", "wamid.badheader")
        response = self.client.post(
            "/webhook", content=raw,
            headers={b"X-Hub-Signature-256": b"sha256=" + b"\xd7\x90" * 32})
        self.assertEqual(response.status_code, 403)

    def test_correctly_signed_message_is_accepted(self):
        raw = message_payload("what are your opening hours?", "wamid.signed.1")
        response = self.client.post(
            "/webhook", content=raw, headers={"X-Hub-Signature-256": sign(raw)})
        self.assertEqual(response.status_code, 200)

    def test_signed_but_unparseable_body_is_acknowledged(self):
        # Never a non-200 on an authentic delivery: Meta would retry it for
        # hours and eventually disable the webhook.
        raw = b"this is not json"
        response = self.client.post(
            "/webhook", content=raw, headers={"X-Hub-Signature-256": sign(raw)})
        self.assertEqual(response.status_code, 200)

    def test_status_only_delivery_is_acknowledged(self):
        body = {"object": "whatsapp_business_account", "entry": [{"id": "0",
                "changes": [{"field": "messages", "value": {
                    "messaging_product": "whatsapp",
                    "statuses": [{"id": "wamid.s", "status": "delivered"}]}}]}]}
        raw = json.dumps(body).encode("utf-8")
        response = self.client.post(
            "/webhook", content=raw, headers={"X-Hub-Signature-256": sign(raw)})
        self.assertEqual(response.status_code, 200)


class HealthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = start_client(cls)

    def test_health_reports_configuration_without_revealing_it(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["signature_enforced"])
        self.assertTrue(payload["app_secret_set"])
        # Booleans only - no secret value may appear in the body.
        self.assertNotIn(SECRET, response.text)
        self.assertNotIn(VERIFY_TOKEN, response.text)


if __name__ == "__main__":
    unittest.main()
