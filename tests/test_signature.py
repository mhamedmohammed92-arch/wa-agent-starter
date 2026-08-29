"""Webhook signature verification.

The point of these tests: a request that is NOT signed with the app secret must
never be accepted. An unauthenticated webhook is a public remote control for the
agent - anyone who learns the URL can forge a payload, choose the `from` number
and drive it.
"""

import hashlib
import hmac
import unittest

from app.signature import expected_signature, verify_signature

SECRET = "test-app-secret"
OTHER_SECRET = "someone-elses-app-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


class RejectsBadSignatureTest(unittest.TestCase):
    """Every way a signature can be wrong, and all of them must be refused."""

    def test_tampered_body_is_rejected(self):
        header = expected_signature(SECRET, BODY)
        tampered = BODY.replace(b"entry", b"ENTRY")
        self.assertFalse(verify_signature(tampered, header, SECRET))

    def test_signature_from_another_secret_is_rejected(self):
        header = expected_signature(OTHER_SECRET, BODY)
        self.assertFalse(verify_signature(BODY, header, SECRET))

    def test_garbage_digest_is_rejected(self):
        self.assertFalse(verify_signature(BODY, "sha256=" + "0" * 64, SECRET))

    def test_missing_header_is_rejected(self):
        self.assertFalse(verify_signature(BODY, None, SECRET))
        self.assertFalse(verify_signature(BODY, "", SECRET))

    def test_missing_prefix_is_rejected(self):
        bare = hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
        self.assertFalse(verify_signature(BODY, bare, SECRET))

    def test_sha1_prefix_is_rejected(self):
        # Meta also offers the legacy X-Hub-Signature (SHA-1). We accept SHA-256
        # only, so a downgrade attempt must not pass.
        digest = hmac.new(SECRET.encode(), BODY, hashlib.sha1).hexdigest()
        self.assertFalse(verify_signature(BODY, "sha1=" + digest, SECRET))

    def test_truncated_digest_is_rejected(self):
        header = expected_signature(SECRET, BODY)
        self.assertFalse(verify_signature(BODY, header[:-4], SECRET))

    def test_non_ascii_digest_is_rejected_without_raising(self):
        # hmac.compare_digest raises TypeError on non-ASCII str, so the shape is
        # screened first. A crash here would be a 500 on a forged request.
        self.assertFalse(verify_signature(BODY, "sha256=" + "\u05D0" * 64, SECRET))

    def test_unset_secret_rejects_everything(self):
        # Fail closed: a deployment that forgot META_APP_SECRET must not accept
        # traffic, not even correctly signed traffic.
        header = expected_signature(SECRET, BODY)
        self.assertFalse(verify_signature(BODY, header, ""))
        self.assertFalse(verify_signature(BODY, header, "   ".strip()))


class AcceptsRealSignatureTest(unittest.TestCase):
    """The genuine Meta delivery still has to get through."""

    def test_valid_signature_is_accepted(self):
        header = expected_signature(SECRET, BODY)
        self.assertTrue(verify_signature(BODY, header, SECRET))

    def test_uppercase_hex_is_accepted(self):
        header = expected_signature(SECRET, BODY).upper().replace("SHA256=", "sha256=")
        self.assertTrue(verify_signature(BODY, header, SECRET))

    def test_surrounding_whitespace_is_tolerated(self):
        header = "  " + expected_signature(SECRET, BODY) + "  "
        self.assertTrue(verify_signature(BODY, header, SECRET))

    def test_empty_body_signs_and_verifies(self):
        header = expected_signature(SECRET, b"")
        self.assertTrue(verify_signature(b"", header, SECRET))
        self.assertFalse(verify_signature(b"x", header, SECRET))


if __name__ == "__main__":
    unittest.main()
