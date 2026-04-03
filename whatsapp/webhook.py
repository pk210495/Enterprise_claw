"""
WhatsApp Webhook Adapter
────────────────────────
Bridges WhatsApp (Twilio or Meta Cloud API) ↔ Enterprise Claw agent.

Supports two providers (set via WHATSAPP_PROVIDER env var):
  • twilio  — Twilio WhatsApp sandbox / production
  • meta    — Meta WhatsApp Business Cloud API

Each WhatsApp phone number becomes an agent session_id so per-user
conversation history is automatically maintained.
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

import httpx
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
import uvicorn

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Config ───────────────────────────────────────────────────────────────────

AGENT_BASE_URL  = os.getenv("AGENT_BASE_URL", "http://agent:8000")
PROVIDER        = os.getenv("WHATSAPP_PROVIDER", "twilio").lower()
DEFAULT_SKILL   = os.getenv("DEFAULT_SKILL", "assistant")

# Twilio
TWILIO_ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM          = os.getenv("TWILIO_WHATSAPP_FROM", "")

# Meta
META_TOKEN           = os.getenv("META_WHATSAPP_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID", "")
META_VERIFY_TOKEN    = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "changeme")
META_APP_SECRET      = os.getenv("META_APP_SECRET", "")  # for payload signature verification

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="WhatsApp ↔ Enterprise Claw Bridge")


def _session_id(phone: str) -> str:
    """Deterministic session id from phone number (strip whatsapp: prefix)."""
    clean = phone.replace("whatsapp:", "").replace("+", "").strip()
    return f"wa_{clean}"


async def _call_agent(session_id: str, message: str) -> str:
    """Send message to agent and return reply text."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{AGENT_BASE_URL}/chat",
            json={
                "session_id": session_id,
                "message": message,
                "skill": DEFAULT_SKILL,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("reply", "(no reply)")


# ══════════════════════════════════════════════════════════════════════════════
#  TWILIO PROVIDER
# ══════════════════════════════════════════════════════════════════════════════

def _verify_twilio_signature(request_url: str, post_params: dict, signature: str) -> bool:
    """Validate that the request is genuinely from Twilio."""
    if not TWILIO_AUTH_TOKEN:
        return True  # skip if not configured
    try:
        from twilio.request_validator import RequestValidator
        validator = RequestValidator(TWILIO_AUTH_TOKEN)
        return validator.validate(request_url, post_params, signature)
    except ImportError:
        logger.warning("twilio package not installed — skipping signature validation")
        return True


@app.post("/twilio/webhook", response_class=PlainTextResponse)
async def twilio_webhook(
    request: Request,
    Body: str = Form(""),
    From: str = Form(""),
    To: str = Form(""),
    x_twilio_signature: Optional[str] = Header(None),
):
    """Twilio sends form-encoded POST when a WhatsApp message arrives."""
    # Signature verification
    form_data = dict(await request.form())
    url = str(request.url)
    if not _verify_twilio_signature(url, form_data, x_twilio_signature or ""):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    if not Body or not From:
        return ""

    session_id = _session_id(From)
    logger.info(f"[Twilio] {From} → session={session_id}: {Body[:80]}")

    try:
        reply = await _call_agent(session_id, Body)
    except Exception as e:
        logger.exception(f"Agent call failed: {e}")
        reply = "Sorry, I'm having trouble right now. Please try again in a moment."

    # Return TwiML
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message to="{From}" from="{TWILIO_FROM or To}">{_escape_xml(reply)}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="text/xml")


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


# ══════════════════════════════════════════════════════════════════════════════
#  META CLOUD API PROVIDER
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/meta/webhook")
async def meta_verify(request: Request):
    """Meta sends GET to verify the webhook endpoint on setup."""
    params = dict(request.query_params)
    mode      = params.get("hub.mode", "")
    token     = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        logger.info("Meta webhook verified successfully")
        return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/meta/webhook")
async def meta_webhook(request: Request):
    """Meta sends POST when a WhatsApp message arrives."""
    # Verify payload signature (X-Hub-Signature-256)
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256", "")
    if META_APP_SECRET and signature_header:
        expected = "sha256=" + hmac.new(
            META_APP_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature_header, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue  # ignore media for now
                from_number = message.get("from", "")
                text        = message.get("text", {}).get("body", "")
                if not text or not from_number:
                    continue

                session_id = _session_id(from_number)
                logger.info(f"[Meta] {from_number} → session={session_id}: {text[:80]}")

                try:
                    reply = await _call_agent(session_id, text)
                except Exception as e:
                    logger.exception(f"Agent call failed: {e}")
                    reply = "Sorry, I'm having trouble right now. Please try again in a moment."

                await _meta_send_reply(from_number, reply)

    return Response(content="EVENT_RECEIVED", status_code=200)


async def _meta_send_reply(to: str, message: str):
    """Send a reply via Meta Graph API."""
    url = f"https://graph.facebook.com/v19.0/{META_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            logger.error(f"Meta send failed: {resp.status_code} {resp.text}")
        else:
            logger.info(f"Meta reply sent to {to}")


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "provider": PROVIDER}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("WHATSAPP_PORT", "8001"))
    uvicorn.run("webhook:app", host="0.0.0.0", port=port, reload=False)
