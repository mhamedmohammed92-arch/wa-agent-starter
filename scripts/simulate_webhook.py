"""Send a correctly signed fake WhatsApp message to a running instance.

Lets you exercise the whole path - signature, language detection, intent match,
RTL preparation - before any Meta account exists. Standard library only.

Usage (PowerShell on Windows, one line):

    python scripts/simulate_webhook.py --text "what are your opening hours?"

The app secret is read from the environment or a local .env file, so it matches
whatever the running container is using. Nothing is sent to Meta: with no
WhatsApp token configured the app logs the reply instead of delivering it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_env_file(name: str) -> str:
    """Read one key from .env, so this script needs no extra dependency."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def build_payload(text: str, sender: str, message_id: str) -> dict:
    """The shape Meta actually posts for one inbound text message."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550000000",
                                "phone_number_id": "0",
                            },
                            "contacts": [
                                {"profile": {"name": "Simulator"}, "wa_id": sender}
                            ],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": message_id,
                                    "timestamp": "0",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True, help="message body to send")
    parser.add_argument("--url", default="http://127.0.0.1:8000/webhook")
    parser.add_argument("--sender", default="972500000000")
    parser.add_argument(
        "--message-id",
        default="wamid.simulated.1",
        help="change it between runs, or the duplicate guard will skip the message",
    )
    parser.add_argument(
        "--secret",
        default="",
        help="app secret; defaults to META_APP_SECRET from the environment or .env",
    )
    args = parser.parse_args()

    secret = args.secret or os.getenv("META_APP_SECRET") or read_env_file("META_APP_SECRET")
    if not secret:
        print(
            "No app secret found. Set META_APP_SECRET in .env, or pass --secret.\n"
            "(Or set ALLOW_UNSIGNED_WEBHOOK=true for local testing and pass "
            "--secret anything.)",
            file=sys.stderr,
        )
        return 2

    # Sign the EXACT bytes that go on the wire. Re-encoding the dict here and
    # again below would produce two different byte strings and a failing check.
    raw = json.dumps(
        build_payload(args.text, args.sender, args.message_id)
    ).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()

    request = urllib.request.Request(
        args.url,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        print(error.code, error.read().decode("utf-8", "replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"could not reach {args.url}: {error.reason}", file=sys.stderr)
        return 1

    print("Sent. The reply is in the app log (docker compose logs -f agent).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
