"""Incident lifecycle + escalation engine.

Flow:
  Grafana webhook --> ingest_alert() dedups by fingerprint into an Incident,
  picks an escalation policy via routing, and pages step 0's targets.

  A periodic tick() advances any incident whose next_escalation_at is due,
  paging the next step's targets, repeating the ladder up to policy.repeat
  times, then going quiet (but staying TRIGGERED) until acked/resolved.

  ack/resolve stop escalation.
"""
from __future__ import annotations

import html
import logging
from datetime import timedelta
from typing import Optional

from sqlmodel import Session, select

from .config import OrgConfig, org
from .db import get_session, utcnow
from .models import Incident, IncidentStatus, NotificationLog
from .notifiers import google_chat, telegram

log = logging.getLogger("pgduty.escalation")


# --- message formatting ----------------------------------------------------


def _incident_text(inc: Incident, cfg: OrgConfig, prefix: str = "") -> str:
    labels = inc.labels or {}
    alertname = labels.get("alertname")
    summary = inc.title  # ingest stores the alert's summary as the title.

    # Compact: alert name + incident number, then the summary beneath.
    lines = [f"<b>🔥 {alertname or summary}</b> · #{inc.id}"]
    if summary and summary != alertname:
        lines.append(summary)
    if inc.description:
        lines.append(inc.description)
    body = "\n".join(lines)
    return f"{prefix}\n{body}" if prefix else body


_LIST_TITLES = {"triggered": "🔴 Triggered", "acknowledged": "🟡 Acknowledged"}


def list_title(status: Optional[str]) -> str:
    return _LIST_TITLES.get(status, "📋 Open incidents")


def incidents_for_list(status: Optional[str], limit: int = 20) -> list[dict]:
    """Compact incident rows for the Telegram menu. `status` None = all open.
    Each item: {id, status, text} where text is a one-line HTML-safe summary."""
    with get_session() as session:
        stmt = select(Incident).order_by(Incident.id.desc())
        if status:
            stmt = stmt.where(Incident.status == status)
        else:
            stmt = stmt.where(Incident.status != IncidentStatus.RESOLVED)
        rows = session.exec(stmt.limit(limit)).all()

    items = []
    for inc in rows:
        alertname = (inc.labels or {}).get("alertname")
        summary = inc.title
        name = html.escape(alertname or summary)
        st = inc.status.value if hasattr(inc.status, "value") else inc.status
        is_muted = bool(inc.muted_until and inc.muted_until > utcnow())
        flag = " 😴" if is_muted else ""
        text = f"<b>#{inc.id}</b> · {name}{flag}"
        if summary and summary != alertname:
            text += f"\n{html.escape(summary)}"
        items.append({"id": inc.id, "status": st, "muted": is_muted, "text": text})
    return items


def _open_by_fingerprint(session: Session, fingerprint: str) -> Optional[Incident]:
    stmt = (
        select(Incident)
        .where(Incident.fingerprint == fingerprint)
        .where(Incident.status != IncidentStatus.RESOLVED)
        .order_by(Incident.id.desc())
    )
    return session.exec(stmt).first()


# --- paging ----------------------------------------------------------------


async def notify_step(session: Session, inc: Incident, cfg: OrgConfig) -> None:
    """Page every user targeted by the incident's current escalation step."""
    from .oncall import expand_targets

    policy = cfg.policies.get(inc.policy_id)
    if not policy or inc.current_step >= len(policy.steps):
        return
    step = policy.steps[inc.current_step]
    user_ids = expand_targets(cfg, step.targets)

    prefix = f"⛑️ Escalation step {inc.current_step + 1}/{len(policy.steps)}"
    text = _incident_text(inc, cfg, prefix=prefix)

    for uid in user_ids:
        user = cfg.users.get(uid)
        if not user:
            continue
        ok = False
        if user.telegram_chat_id:
            ok = await telegram.page_user(user.telegram_chat_id, inc.id, text)
        session.add(
            NotificationLog(
                incident_id=inc.id,
                user_id=uid,
                channel="telegram" if user.telegram_chat_id else "none",
                step=inc.current_step,
                detail=f"paged {user.name}",
                ok=ok,
            )
        )

    # Google Chat is a space-level broadcast (good for visibility).
    # Use the alert name as the card title; the body drops the redundant
    # "alertname · #id" line and just carries the summary/description.
    alertname = (inc.labels or {}).get("alertname")
    gc_title = alertname or inc.title
    gc_lines = [prefix]
    if inc.title and inc.title != gc_title:
        gc_lines.append(inc.title)
    if inc.description:
        gc_lines.append(inc.description)
    gc_ok = await google_chat.post_incident(
        inc.id,
        gc_title,
        body="\n".join(gc_lines),
        severity=inc.severity,
    )
    if gc_ok:
        session.add(
            NotificationLog(
                incident_id=inc.id, channel="google_chat", step=inc.current_step, detail="posted to space", ok=True
            )
        )
    session.commit()


# --- ingest ----------------------------------------------------------------


async def ingest_alert(session: Session, alert: dict, cfg: OrgConfig) -> Optional[Incident]:
    """Process one Alertmanager-style alert object (firing or resolved)."""
    status = alert.get("status", "firing")
    labels = dict(alert.get("labels", {}) or {})
    annotations = dict(alert.get("annotations", {}) or {})
    fingerprint = alert.get("fingerprint") or str(abs(hash(frozenset(labels.items()))))

    if status == "resolved":
        inc = _open_by_fingerprint(session, fingerprint)
        if inc:
            await _resolve(session, inc, cfg, who="grafana", auto=True)
        return inc

    # firing
    existing = _open_by_fingerprint(session, fingerprint)
    if existing:
        # Refresh metadata; don't restart escalation for a repeat firing.
        existing.labels = labels
        existing.updated_at = utcnow()
        if annotations.get("description"):
            existing.description = annotations["description"]
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    title = (
        annotations.get("summary")
        or alert.get("title")
        or labels.get("alertname")
        or "Alert firing"
    )
    policy_id = cfg.route(labels)
    policy = cfg.policies.get(policy_id)

    inc = Incident(
        fingerprint=fingerprint,
        title=title,
        description=annotations.get("description", ""),
        severity=labels.get("severity", "default"),
        source_url=alert.get("generatorURL", "") or alert.get("panelURL", ""),
        labels=labels,
        status=IncidentStatus.TRIGGERED,
        policy_id=policy_id,
        current_step=0,
        repeats_left=policy.repeat if policy else 0,
    )
    session.add(inc)
    session.commit()
    session.refresh(inc)

    await notify_step(session, inc, cfg)

    # Schedule the first escalation after step 0's delay.
    if policy and policy.steps:
        inc.next_escalation_at = utcnow() + timedelta(minutes=policy.steps[0].delay_minutes)
        session.add(inc)
        session.commit()
        session.refresh(inc)
    log.info("incident #%s triggered (%s) policy=%s", inc.id, title, policy_id)
    return inc


# --- ack / resolve ---------------------------------------------------------


async def ack_incident(session: Session, incident_id: int, who: str) -> Optional[Incident]:
    cfg = org()
    inc = session.get(Incident, incident_id)
    if not inc or inc.status == IncidentStatus.RESOLVED:
        return inc
    if inc.status == IncidentStatus.ACKNOWLEDGED:
        return inc
    inc.status = IncidentStatus.ACKNOWLEDGED
    inc.acked_by = who
    inc.acked_at = utcnow()
    inc.next_escalation_at = None
    inc.updated_at = utcnow()
    session.add(inc)
    session.commit()
    session.refresh(inc)
    log.info("incident #%s acknowledged by %s", inc.id, who)
    await _broadcast_status(inc, cfg, f"✅ Incident #{inc.id} acknowledged by {who}")
    return inc


async def snooze_incident(session: Session, incident_id: int, minutes: int, who: str) -> Optional[Incident]:
    """Mute paging for `minutes`. Escalation pauses until then, then resumes."""
    cfg = org()
    inc = session.get(Incident, incident_id)
    if not inc or inc.status == IncidentStatus.RESOLVED:
        return inc
    minutes = max(1, minutes)
    inc.muted_until = utcnow() + timedelta(minutes=minutes)
    inc.updated_at = utcnow()
    session.add(inc)
    session.commit()
    session.refresh(inc)
    log.info("incident #%s snoozed by %s for %sm", inc.id, who, minutes)
    label = f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"
    await _broadcast_status(inc, cfg, f"😴 Incident #{inc.id} snoozed by {who} for {label}")
    return inc


async def unsnooze_incident(session: Session, incident_id: int, who: str) -> Optional[Incident]:
    """Clear a snooze early; escalation resumes on the next tick."""
    cfg = org()
    inc = session.get(Incident, incident_id)
    if not inc:
        return None
    if inc.muted_until is None:
        return inc  # nothing to do
    inc.muted_until = None
    inc.updated_at = utcnow()
    session.add(inc)
    session.commit()
    session.refresh(inc)
    log.info("incident #%s unsnoozed by %s", inc.id, who)
    await _broadcast_status(inc, cfg, f"⏰ Incident #{inc.id} unsnoozed by {who}")
    return inc


async def resolve_incident(session: Session, incident_id: int, who: str) -> Optional[Incident]:
    cfg = org()
    inc = session.get(Incident, incident_id)
    if not inc:
        return None
    await _resolve(session, inc, cfg, who=who, auto=False)
    return inc


async def resolve_by_fingerprint(session: Session, fingerprint: str, who: str) -> Optional[Incident]:
    """Auto-resolve the open incident for a fingerprint. Used by the Grafana
    poller when an alert clears (drops out of the active set) rather than
    arriving as an explicit `resolved` webhook."""
    inc = _open_by_fingerprint(session, fingerprint)
    if inc:
        await _resolve(session, inc, org(), who=who, auto=True)
    return inc


async def _resolve(session: Session, inc: Incident, cfg: OrgConfig, who: str, auto: bool) -> None:
    if inc.status == IncidentStatus.RESOLVED:
        return
    inc.status = IncidentStatus.RESOLVED
    inc.resolved_at = utcnow()
    inc.resolved_by = who
    inc.next_escalation_at = None
    inc.updated_at = utcnow()
    session.add(inc)
    session.commit()
    session.refresh(inc)
    log.info("incident #%s resolved by %s (auto=%s)", inc.id, who, auto)
    suffix = " (auto, by Grafana)" if auto else ""
    await _broadcast_status(inc, cfg, f"✔️ Incident #{inc.id} resolved by {who}{suffix}")


async def _broadcast_status(inc: Incident, cfg: OrgConfig, text: str) -> None:
    """Tell everyone who could have been paged about a status change."""
    from .oncall import expand_targets

    policy = cfg.policies.get(inc.policy_id)
    targeted: list[str] = []
    if policy:
        for step in policy.steps:
            for uid in expand_targets(cfg, step.targets):
                if uid not in targeted:
                    targeted.append(uid)
    for uid in targeted:
        user = cfg.users.get(uid)
        if user and user.telegram_chat_id:
            await telegram.notify_text(user.telegram_chat_id, text)
    await google_chat.post_text(text)


# --- periodic escalation tick ---------------------------------------------


async def tick() -> None:
    """Advance every incident whose escalation timer is due."""
    cfg = org()
    now = utcnow()
    with get_session() as session:
        stmt = (
            select(Incident)
            .where(Incident.status == IncidentStatus.TRIGGERED)
            .where(Incident.next_escalation_at != None)  # noqa: E711
            .where(Incident.next_escalation_at <= now)
        )
        due = list(session.exec(stmt).all())
        for inc in due:
            # Snoozed: skip until the mute window passes, then resume.
            if inc.muted_until and inc.muted_until > now:
                continue
            await _advance(session, inc, cfg)


async def _advance(session: Session, inc: Incident, cfg: OrgConfig) -> None:
    policy = cfg.policies.get(inc.policy_id)
    if not policy or not policy.steps:
        inc.next_escalation_at = None
        session.add(inc)
        session.commit()
        return

    if inc.current_step + 1 < len(policy.steps):
        inc.current_step += 1
    elif inc.repeats_left > 0:
        inc.repeats_left -= 1
        inc.current_step = 0
    else:
        # Ladder exhausted: stop paging but leave it TRIGGERED for visibility.
        inc.next_escalation_at = None
        inc.updated_at = utcnow()
        session.add(inc)
        session.commit()
        log.info("incident #%s escalation exhausted", inc.id)
        return

    inc.updated_at = utcnow()
    session.add(inc)
    session.commit()
    session.refresh(inc)

    await notify_step(session, inc, cfg)

    delay = policy.steps[inc.current_step].delay_minutes
    inc.next_escalation_at = utcnow() + timedelta(minutes=delay)
    session.add(inc)
    session.commit()
    log.info("incident #%s escalated to step %s", inc.id, inc.current_step + 1)
