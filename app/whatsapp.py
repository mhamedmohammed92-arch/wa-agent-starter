"""Outbound messages to the WhatsApp Cloud API.

Dry-run by default: with no token or phone id configured, the reply is computed
and logged but never sent. That keeps the first run of this project free of any
Meta setup, and keeps the tests offline.
"""

from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger("wa_agent.whatsapp")

_TIMEOUT_SECONDS = 15


async def send_text(to: str, body: str) -> dict:
    """Send one text message. Raises on any non-2xx answer from Meta.

    Meta returns HTTP 4xx with a JSON error body for the failures you will
    actually hit - expired token, recipient not on the test number's allow-list
    (error 131030), a session older than 24 hours. httpx does not raise on those
    by itself, so without this check the message silently never arrives.
    """
    if not settings.send_configured:
        log.warning(
            "DRY RUN (WHATSAPP_TOKEN / WHATSAPP_PHONE_ID not set) -> to=%s body=%r",
            _mask(to), body,
        )
        return {"status": "dry_run", "to": to, "body": body}

    url = f"{settings.graph_url}/{settings.WHATSAPP_PHONE_ID.strip()}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        # preview_url off: a link preview would be fetched by Meta and can leak
        # the fact that the number is live to whatever host is linked.
        "text": {"preview_url": False, "body": body},
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN.strip()}"}

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.is_error:
        try:
            detail = (response.json().get("error") or {}).get("message")
        except Exception:  # noqa: BLE001 - a proxy may return HTML, not JSON
            detail = None
        detail = detail or response.text[:300]
        raise RuntimeError(f"WhatsApp send failed [{response.status_code}]: {detail}")

    return response.json()


def _mask(number: str) -> str:
    """Keep phone numbers out of the log in full."""
    number = (number or "").strip()
    return ("*" * max(len(number) - 4, 0)) + number[-4:]
