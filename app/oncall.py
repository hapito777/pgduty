"""Resolve who is on-call for a schedule at a given time, and expand
escalation targets into concrete users."""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import OrgConfig, Schedule, Target
from .db import utcnow


def current_oncall(schedule: Schedule, at: datetime | None = None) -> str:
    """Return the user id on-call for `schedule` at time `at` (naive UTC).

    Simple single-layer rotation: users take turns for one rotation period
    (a day or a week), anchored at schedule.start.
    """
    at = at or utcnow()
    if not schedule.users:
        raise ValueError(f"schedule '{schedule.id}' has no users")

    period = timedelta(days=7 if schedule.rotation == "weekly" else 1)
    if at <= schedule.start:
        return schedule.users[0]

    elapsed = at - schedule.start
    index = int(elapsed // period) % len(schedule.users)
    return schedule.users[index]


def expand_targets(cfg: OrgConfig, targets: list[Target], at: datetime | None = None) -> list[str]:
    """Expand a step's targets into a de-duplicated, order-preserving list of
    user ids."""
    out: list[str] = []
    for tgt in targets:
        if tgt.type == "user":
            uid = tgt.id
            if uid in cfg.users and uid not in out:
                out.append(uid)
        elif tgt.type == "schedule":
            sched = cfg.schedules.get(tgt.id)
            if sched:
                uid = current_oncall(sched, at)
                if uid not in out:
                    out.append(uid)
    return out


def oncall_snapshot(cfg: OrgConfig, at: datetime | None = None) -> dict[str, dict]:
    """Who is on-call right now, per schedule (for the dashboard / API)."""
    at = at or utcnow()
    snap: dict[str, dict] = {}
    for sid, sched in cfg.schedules.items():
        uid = current_oncall(sched, at)
        user = cfg.users.get(uid)
        snap[sid] = {
            "schedule": sched.name,
            "user_id": uid,
            "user_name": user.name if user else uid,
        }
    return snap
