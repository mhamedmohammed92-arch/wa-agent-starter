"""Verification of Meta's X-Hub-Signature-256 header.

Meta signs every webhook delivery with:

    X-Hub-Signature-256: sha256=HMAC_SHA256(app_secret, RAW_REQUEST_BODY)

The signature is computed over the *raw bytes* Meta sent. Re-serialising the
parsed JSON and hashing that will not match: key order, spacing and unicode
escaping all differ. Always hash `await request.body()`.

Without this check the webhook is a public remote control: anyone who learns the
URL can POST a forged payload, choose the `from` number, drive the agent and
spend your model budget.

This module is deliberately free of framework imports so it can be unit-tested
on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

log = logging.getLogger("wa_agent.signature")

_PREFIX = "sha256="
_HEX_DIGEST_LEN = 64
_HEX_CHARS = frozenset("0123456789abcdef")


def expected_signature(secret: str, raw: bytes) -> str:
    """Build the header value Meta would send for this body. Used by tests and
    by the local simulator script."""
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(raw: bytes, header: str | None, secret: str) -> bool:
    """True only when `header` is a valid signature of `raw` under `secret`.

    Fails closed on every uncertainty: no secret configured, missing header,
    wrong prefix, or a digest that is not 64 lowercase hex characters. An empty
    secret returning False is intentional - an unconfigured deployment must not
    silently accept unsigned traffic.
    """
    if not secret:
        log.error(
            "META_APP_SECRET is not set - every webhook POST will be rejected. "
            "Copy the App Secret from the Meta app dashboard into your .env."
        )
        return False
    if not header:
        return False

    header = header.strip()
    if not header.startswith(_PREFIX):
        return False

    supplied = header[len(_PREFIX):].strip().lower()
    # compare_digest raises TypeError on non-ASCII str input, and a wrong length
    # can never be a match anyway, so screen the shape before comparing.
    if len(supplied) != _HEX_DIGEST_LEN or not set(supplied) <= _HEX_CHARS:
        return False

    computed = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    # Constant time: a plain `==` leaks how many leading bytes were right, which
    # is enough to forge a signature one byte at a time.
    return hmac.compare_digest(computed, supplied)
