"""Background loop that consumes Telegram updates (button taps) so users can
acknowledge / resolve incidents straight from the page message."""
from __future__ import annotations

import asyncio
import logging

from . import grafana
from .config import get_settings, org
from .db import get_session
from .escalation import (
    ack_incident,
    incidents_for_list,
    ingest_alert,
    list_title,
    resolve_by_fingerprint,
    resolve_incident,
    snooze_incident,
    unsnooze_incident,
)
from .notifiers import telegram

log = logging.getLogger("pgduty.poller")


def _user_for_chat(chat_id: str) -> str:
    cfg = org()
    for user in cfg.users.values():
        if user.telegram_chat_id and str(user.telegram_chat_id) == str(chat_id):
            return user.id
    return f"telegram:{chat_id}"


async def _handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    cb_id = cb.get("id")
    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    who = _user_for_chat(chat_id)

    # Formats: "list:<view>", "ack:<id>", "resolve:<id>", "snooze:<id>:<minutes>".
    parts = data.split(":")
    if len(parts) < 2:
        await telegram.answer_callback(cb_id, "Unknown action")
        return
    action = parts[0]

    if action == "list":
        view = parts[1]
        await telegram.answer_callback(cb_id)
        await _send_list(chat_id, None if view == "open" else view)
        return

    try:
        incident_id = int(parts[1])
    except ValueError:
        await telegram.answer_callback(cb_id, "Bad incident id")
        return

    with get_session() as session:
        if action == "ack":
            inc = await ack_incident(session, incident_id, who)
            await telegram.answer_callback(cb_id, "Acknowledged" if inc else "Not found")
        elif action == "resolve":
            inc = await resolve_incident(session, incident_id, who)
            await telegram.answer_callback(cb_id, "Resolved" if inc else "Not found")
        elif action == "snooze":
            minutes = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 60
            inc = await snooze_incident(session, incident_id, minutes, who)
            await telegram.answer_callback(cb_id, f"Snoozed {minutes}m" if inc else "Not found")
        elif action == "unsnooze":
            inc = await unsnooze_incident(session, incident_id, who)
            await telegram.answer_callback(cb_id, "Unsnoozed" if inc else "Not found")
        else:
            await telegram.answer_callback(cb_id, "Unknown action")


async def _send_list(chat_id: str, status: str | None) -> None:
    """Send a compact list: a header, then one message per incident with
    status-appropriate Ack/Resolve buttons."""
    items = incidents_for_list(status)
    title = list_title(status)
    if not items:
        await telegram.notify_text(chat_id, f"<b>{title}</b>\nNone 🎉")
        return
    await telegram.notify_text(chat_id, f"<b>{title}</b> ({len(items)})")
    for it in items:
        await telegram.send_incident_line(chat_id, it["id"], it["text"], it["status"], it["muted"])


async def _handle_message(msg: dict) -> None:
    """Respond to the bottom-menu buttons and slash commands."""
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if not chat_id:
        return
    raw = (msg.get("text") or "").strip()
    cmd = raw.split()[0].split("@")[0].lower() if raw else ""

    if raw == telegram.BTN_TRIGGERED or cmd == "/triggered":
        await _send_list(chat_id, "triggered")
    elif raw == telegram.BTN_ACK or cmd == "/acknowledged":
        await _send_list(chat_id, "acknowledged")
    elif raw == telegram.BTN_OPEN or cmd == "/open":
        await _send_list(chat_id, None)
    elif cmd in ("/menu", "/start"):
        # Show the bottom menu only when explicitly requested.
        await telegram.send_menu(chat_id)
    # Any other text is ignored — the hamburger (≡) commands menu is always there.


async def run_telegram_poller(stop: asyncio.Event) -> None:
    if not get_settings().telegram_bot_token:
        log.info("Telegram disabled (no TELEGRAM_BOT_TOKEN); poller not started")
        return
    log.info("Telegram poller started")
    offset = 0
    conflict_logged = False
    while not stop.is_set():
        try:
            data = await telegram.get_updates(offset, timeout=30)
            if data.get("ok"):
                conflict_logged = False
                for upd in data.get("result", []):
                    offset = max(offset, upd["update_id"] + 1)
                    if "callback_query" in upd:
                        await _handle_callback(upd["callback_query"])
                    elif "message" in upd:
                        await _handle_message(upd["message"])
                continue

            code = data.get("error_code")
            if code == 409:
                # Another process is polling this bot (e.g. the Telegram MCP
                # plugin). Log once, then back off so we don't spam the API.
                if not conflict_logged:
                    log.warning(
                        "Telegram 409 Conflict: another process is polling this bot. "
                        "pgduty needs its OWN bot token (see README). Backing off."
                    )
                    conflict_logged = True
                await asyncio.sleep(30)
            else:
                log.warning("getUpdates failed: %s", data.get("description"))
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # keep the loop alive on transient errors
            log.warning("poller error: %s", exc)
            await asyncio.sleep(3)
    log.info("Telegram poller stopped")


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """Sleep up to `seconds`, returning early if `stop` is set."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run_grafana_poller(stop: asyncio.Event) -> None:
    """Pull firing alerts from Grafana on an interval and ingest them.

    Grafana's alerts API returns only the *active* set, so resolution is
    implicit: any incident this poller created that is no longer in the active
    set has cleared in Grafana and is auto-resolved. We only reconcile after a
    successful fetch (fetch_active_alerts returns None on error) so a transient
    Grafana outage never mass-resolves open incidents.
    """
    if not grafana._enabled():
        log.info("Grafana polling disabled (no PGDUTY_GRAFANA_URL/PGDUTY_GRAFANA_TOKEN); "
                 "poller not started")
        return
    interval = max(5, get_settings().grafana_poll_seconds)
    log.info("Grafana poller started (every %ss)", interval)
    # Fingerprints this poller is responsible for, so we never auto-resolve
    # incidents that arrived via the webhook push path instead.
    managed: set[str] = set()
    while not stop.is_set():
        try:
            alerts = await grafana.fetch_active_alerts()
            if alerts is not None:
                cfg = org()
                active: set[str] = set()
                with get_session() as session:
                    for alert in alerts:
                        fp = alert.get("fingerprint")
                        if not fp:
                            continue
                        active.add(fp)
                        inc = await ingest_alert(session, alert, cfg)
                        if inc:
                            managed.add(fp)
                    # Anything we were managing that's no longer firing has
                    # cleared in Grafana -> auto-resolve it.
                    for fp in managed - active:
                        await resolve_by_fingerprint(session, fp, who="grafana")
                    managed &= active
        except asyncio.CancelledError:
            break
        except Exception as exc:  # keep the loop alive on transient errors
            log.warning("grafana poller error: %s", exc)
        await _sleep_or_stop(stop, interval)
    log.info("Grafana poller stopped")
