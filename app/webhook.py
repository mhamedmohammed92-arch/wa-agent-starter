"""The Meta WhatsApp Cloud API webhook: one GET and one POST.

GET  /webhook - Meta's one-time verification handshake when you save the
                callback URL in the app dashboard.
POST /webhook - every inbound message, delivery status and echo.
"""

from __future__ import annotations

import hmac
import json
import logging
from collections import OrderedDict

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import settings
from .rtl import prepare_outbound
from .signature import verify_signature
from .whatsapp import send_text

log = logging.getLogger("wa_agent.webhook")

router = APIRouter(tags=["webhook"])

# Meta redelivers any webhook it decides was answered slowly, and it also
# redelivers after any non-200. Without a memory of what has already been
# answered, the customer gets the same reply two or three times. An in-process
# ring is enough for one container; the paid kit keeps this in the database so
# it survives a restart and works across replicas.
_MAX_SEEN = 2000
_seen_message_ids: "OrderedDict[str, None]" = OrderedDict()


def _already_handled(message_id: str | None) -> bool:
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids[message_id] = None
    while len(_seen_message_ids) > _MAX_SEEN:
        _seen_message_ids.popitem(last=False)
    return False


@router.get("/webhook")
def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_challenge: str = Query("", alias="hub.challenge"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
) -> Response:
    """Meta calls this once, when you press Verify and save in the dashboard.

    It must echo `hub.challenge` back as PLAIN TEXT, with no quotes and no JSON
    wrapper - a JSON body fails verification with a message that does not say
    why. Returning a JSON string is the single most common reason this step
    fails.
    """
    expected = (settings.WHATSAPP_VERIFY_TOKEN or "").strip()
    if not expected:
        log.error("WHATSAPP_VERIFY_TOKEN is not set - verification cannot succeed")
        return PlainTextResponse("forbidden", status_code=403)
    # Compare as UTF-8 bytes, not as str: compare_digest raises TypeError on a
    # str holding any non-ASCII character, and this query parameter is supplied
    # by whoever calls the URL. As str, a one-line curl with a Hebrew or
    # accented token would be a 500 instead of a 403. Bytes compare in constant
    # time just the same, and this also lets an operator use a non-ASCII token.
    supplied = (hub_verify_token or "").encode("utf-8")
    if hub_mode == "subscribe" and hmac.compare_digest(supplied, expected.encode("utf-8")):
        return PlainTextResponse(hub_challenge)
    log.warning("webhook verification rejected (mode=%r)", hub_mode)
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/webhook")
async def receive_webhook(request: Request) -> Response:
    """Receive inbound messages, answer them, acknowledge to Meta."""
    raw = await request.body()

    if settings.ALLOW_UNSIGNED_WEBHOOK:
        log.warning("ALLOW_UNSIGNED_WEBHOOK is on - signature NOT checked")
    elif not verify_signature(
        raw, request.headers.get("X-Hub-Signature-256"), settings.META_APP_SECRET
    ):
        log.warning("rejected a webhook POST with a bad or missing signature")
        # 403, not 200: a genuine Meta delivery is always signed, so this only
        # ever fires for a forged request or a misconfigured secret - and in the
        # second case you want Meta's retries and its "delivery failing" flag to
        # tell you, instead of messages silently disappearing.
        return Response(status_code=403)

    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        log.warning("webhook POST body was not JSON")
        return JSONResponse({"status": "ignored"})

    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            await _handle_change(request, change.get("value") or {})

    # Always 200 once the delivery is authentic. Anything else makes Meta retry
    # the same payload for hours, and eventually disable the webhook.
    return JSONResponse({"status": "ok"})


async def _handle_change(request: Request, value: dict) -> None:
    messages = value.get("messages") or []
    if not messages:
        # Statuses (sent / delivered / read) and echoes land here. The starter
        # ignores them; the paid kit records them for the admin panel.
        return

    faq = request.app.state.faq
    for message in messages:
        sender = message.get("from")
        message_id = message.get("id")
        message_type = message.get("type")
        if not sender:
            continue
        if _already_handled(message_id):
            log.info("skipping redelivered message %s", (message_id or "")[-8:])
            continue

        text = ""
        if message_type == "text":
            text = ((message.get("text") or {}).get("body") or "").strip()
        elif message_type in ("image", "video", "document"):
            # A caption is real text and worth answering.
            text = ((message.get(message_type) or {}).get("caption") or "").strip()

        if text:
            reply, language, intent_id = faq.answer(text)
        else:
            # Audio, stickers, locations, contacts: no text to match on.
            language = faq.default_language
            reply, intent_id = faq.fallback_text(language), None

        log.info(
            "in type=%s lang=%s intent=%s -> reply %d chars",
            message_type, language, intent_id or "fallback", len(reply),
        )

        if not reply:
            continue
        try:
            await send_text(sender, prepare_outbound(reply, language))
        except Exception as exc:  # noqa: BLE001
            # One customer's failed send must not abort the rest of the batch,
            # and must not make us return non-200 (which would replay the whole
            # batch, including the messages that did go out).
            log.error("send failed: %s", exc)
