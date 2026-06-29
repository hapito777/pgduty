"""Telegram paging: targeted DMs with inline Ack / Resolve buttons.

Uses long-polling getUpdates (no public URL needed) to receive button taps.
The polling loop runs as a background task started from main.lifespan.
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings

log = logging.getLogger("pgduty.telegram")
API = "https://api.telegram.org/bot{token}/{method}"


def _enabled() -> bool:
    return bool(get_settings().telegram_bot_token)


async def _call(method: str, payload: dict) -> dict | None:
    token = get_settings().telegram_bot_token
    if not token:
        return None
    url = API.format(token=token, method=method)
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        if not data.get("ok"):
            log.warning("telegram %s failed: %s", method, data)
            return None
        return data.get("result")


def _keyboard(incident_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Acknowledge", "callback_data": f"ack:{incident_id}"},
                {"text": "✔️ Resolve", "callback_data": f"resolve:{incident_id}"},
            ],
            [
                {"text": "😴 Snooze 1h", "callback_data": f"snooze:{incident_id}:60"},
                {"text": "😴 Snooze 4h", "callback_data": f"snooze:{incident_id}:240"},
            ],
        ]
    }


async def page_user(chat_id: str, incident_id: int, text: str) -> bool:
    """Send a page to one user's chat with action buttons."""
    if not _enabled():
        return False
    res = await _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": _keyboard(incident_id),
        },
    )
    return res is not None


async def answer_callback(callback_id: str, text: str = "") -> None:
    await _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


# Labels for the persistent bottom keyboard. The poller matches incoming
# message text against these to know which view to show.
BTN_TRIGGERED = "🔴 Triggered"
BTN_ACK = "🟡 Acknowledged"
BTN_OPEN = "📋 All open"


def _reply_keyboard() -> dict:
    """On-demand bottom keyboard: three stacked full-width buttons that tuck
    away again after one tap (shown only when the user opens the menu)."""
    return {
        "keyboard": [[BTN_TRIGGERED], [BTN_ACK], [BTN_OPEN]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


async def send_menu(chat_id: str) -> None:
    """Show the incident menu keyboard at the bottom of the chat."""
    if not _enabled():
        return
    await _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": "📋 Incident menu — pick a view 👇",
            "reply_markup": _reply_keyboard(),
        },
    )


def _list_action_keyboard(incident_id: int, status: str, muted: bool = False) -> dict | None:
    """Buttons for an incident shown in a menu list: Ack+Resolve when
    triggered, Resolve when acknowledged, Unsnooze when muted."""
    row = []
    if status == "triggered":
        row.append({"text": "✅ Acknowledge", "callback_data": f"ack:{incident_id}"})
    if status in ("triggered", "acknowledged"):
        row.append({"text": "✔️ Resolve", "callback_data": f"resolve:{incident_id}"})
    if muted:
        row.append({"text": "⏰ Unsnooze", "callback_data": f"unsnooze:{incident_id}"})
    return {"inline_keyboard": [row]} if row else None


async def send_incident_line(chat_id: str, incident_id: int, text: str,
                             status: str, muted: bool = False) -> None:
    """One compact incident line with status-appropriate action buttons."""
    if not _enabled():
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    markup = _list_action_keyboard(incident_id, status, muted)
    if markup:
        payload["reply_markup"] = markup
    await _call("sendMessage", payload)


async def set_commands() -> None:
    """Register slash commands so they show in Telegram's menu button."""
    if not _enabled():
        return
    await _call(
        "setMyCommands",
        {
            "commands": [
                {"command": "menu", "description": "Show the incident menu"},
                {"command": "triggered", "description": "List triggered incidents"},
                {"command": "acknowledged", "description": "List acknowledged incidents"},
                {"command": "open", "description": "List all open incidents"},
            ]
        },
    )


async def notify_text(chat_id: str, text: str) -> None:
    """Plain status update (e.g. acked/resolved), no buttons."""
    await _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


async def get_updates(offset: int, timeout: int = 30) -> dict:
    """Return the raw Telegram response so the poller can distinguish a normal
    empty long-poll from an error (e.g. 409 Conflict) and back off accordingly."""
    token = get_settings().telegram_bot_token
    if not token:
        return {"ok": False, "error_code": 0, "description": "no token"}
    url = API.format(token=token, method="getUpdates")
    payload = {"offset": offset, "timeout": timeout, "allowed_updates": ["callback_query", "message"]}
    async with httpx.AsyncClient(timeout=timeout + 10) as client:
        resp = await client.post(url, json=payload)
        return resp.json()
