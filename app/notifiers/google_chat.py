"""Google Chat notifications via an incoming webhook (space-level).

Incoming webhooks can't receive button callbacks, so the Ack/Resolve buttons
are signed links back into pgduty's HTTP API (see app.security.action_url).
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..security import action_url

log = logging.getLogger("pgduty.gchat")


def _enabled() -> bool:
    return bool(get_settings().google_chat_webhook_url)


async def _post(payload: dict) -> bool:
    url = get_settings().google_chat_webhook_url
    if not url:
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 300:
            log.warning("google chat post failed: %s %s", resp.status_code, resp.text)
            return False
        return True


async def post_incident(incident_id: int, title: str, body: str, severity: str) -> bool:
    """Post an interactive-looking card with ack/resolve link buttons."""
    if not _enabled():
        return False
    card = {
        "cardsV2": [
            {
                "cardId": f"incident-{incident_id}",
                "card": {
                    "header": {
                        "title": f"🔥 {title}",
                        "subtitle": f"Incident #{incident_id} · severity={severity}",
                    },
                    "sections": [
                        {"widgets": [{"textParagraph": {"text": body}}]},
                        {
                            "widgets": [
                                {
                                    "buttonList": {
                                        "buttons": [
                                            {
                                                "text": "Acknowledge",
                                                "onClick": {"openLink": {"url": action_url(incident_id, "ack")}},
                                            },
                                            {
                                                "text": "Resolve",
                                                "onClick": {"openLink": {"url": action_url(incident_id, "resolve")}},
                                            },
                                        ]
                                    }
                                }
                            ]
                        },
                    ],
                },
            }
        ]
    }
    return await _post(card)


async def post_text(text: str) -> bool:
    if not _enabled():
        return False
    return await _post({"text": text})
