"""Persistent models. Only dynamic state lives here; users/schedules/policies
are config-as-code (see config.yaml)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from .db import utcnow


class IncidentStatus(str, Enum):
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Incident(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Grafana/Alertmanager fingerprint — our dedup key while not resolved.
    fingerprint: str = Field(index=True)
    title: str
    description: str = ""
    severity: str = "default"
    source_url: str = ""
    labels: dict = Field(default_factory=dict, sa_column=Column(JSON))

    status: IncidentStatus = Field(default=IncidentStatus.TRIGGERED, index=True)
    policy_id: str = ""

    # Escalation bookkeeping.
    current_step: int = 0
    repeats_left: int = 0
    next_escalation_at: Optional[datetime] = Field(default=None, index=True)

    acked_by: Optional[str] = None
    acked_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    # Who/what resolved it: a user, "web", or "grafana"/"grafana-poll" (auto).
    resolved_by: Optional[str] = None

    # Snooze: while muted_until is in the future, escalation is paused (no
    # paging). When it passes, escalation resumes on the next tick.
    muted_until: Optional[datetime] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def is_open(self) -> bool:
        return self.status != IncidentStatus.RESOLVED


class NotificationLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    incident_id: int = Field(index=True)
    user_id: Optional[str] = None
    channel: str = ""
    step: int = 0
    detail: str = ""
    ok: bool = True
    created_at: datetime = Field(default_factory=utcnow)
