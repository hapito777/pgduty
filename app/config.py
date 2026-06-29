"""Runtime settings (from env) and org config (from YAML).

Two distinct concerns:
  * Settings  — secrets and runtime knobs, read from environment / .env.
  * OrgConfig — users, schedules, escalation policies, routing, read from YAML.

The org config is treated as config-as-code: edit the YAML and restart.
Incidents are dynamic state and live in the database instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_url: str
    secret: str
    database_url: str
    config_path: str
    tick_seconds: int
    telegram_bot_token: Optional[str]
    google_chat_webhook_url: Optional[str]
    webhook_token: Optional[str]
    # Optional pull-based ingest: poll a Grafana instance for firing alerts
    # instead of (or alongside) receiving its webhook pushes.
    grafana_url: Optional[str]
    grafana_token: Optional[str]
    grafana_poll_seconds: int
    grafana_verify_ssl: bool


@lru_cache
def get_settings() -> Settings:
    return Settings(
        base_url=os.getenv("PGDUTY_BASE_URL", "http://localhost:8080").rstrip("/"),
        secret=os.getenv("PGDUTY_SECRET", "change-me"),
        database_url=os.getenv("PGDUTY_DATABASE_URL", "sqlite:///pgduty.db"),
        config_path=os.getenv("PGDUTY_CONFIG", "config.yaml"),
        tick_seconds=int(os.getenv("PGDUTY_TICK_SECONDS", "15")),
        telegram_bot_token=(os.getenv("TELEGRAM_BOT_TOKEN") or None),
        google_chat_webhook_url=(os.getenv("GOOGLE_CHAT_WEBHOOK_URL") or None),
        webhook_token=(os.getenv("PGDUTY_WEBHOOK_TOKEN") or None),
        grafana_url=((os.getenv("PGDUTY_GRAFANA_URL") or "").rstrip("/") or None),
        grafana_token=(os.getenv("PGDUTY_GRAFANA_TOKEN") or None),
        grafana_poll_seconds=int(os.getenv("PGDUTY_GRAFANA_POLL_SECONDS", "30")),
        grafana_verify_ssl=(os.getenv("PGDUTY_GRAFANA_VERIFY_SSL", "true").lower()
                            not in ("0", "false", "no")),
    )


# --- Org config dataclasses ------------------------------------------------


@dataclass
class User:
    id: str
    name: str
    telegram_chat_id: Optional[str] = None
    email: Optional[str] = None


@dataclass
class Schedule:
    id: str
    name: str
    rotation: str  # "daily" | "weekly"
    start: datetime
    users: list[str] = field(default_factory=list)


@dataclass
class Target:
    type: str  # "schedule" | "user"
    id: str


@dataclass
class EscalationStep:
    delay_minutes: int
    targets: list[Target]


@dataclass
class EscalationPolicy:
    id: str
    name: str
    repeat: int
    steps: list[EscalationStep]


@dataclass
class RoutingRule:
    match: dict[str, str]
    policy: str


@dataclass
class OrgConfig:
    users: dict[str, User]
    schedules: dict[str, Schedule]
    policies: dict[str, EscalationPolicy]
    default_policy: str
    rules: list[RoutingRule]

    def route(self, labels: dict[str, str]) -> str:
        """Return the escalation policy id for a set of alert labels."""
        for rule in self.rules:
            if all(labels.get(k) == v for k, v in rule.match.items()):
                if rule.policy in self.policies:
                    return rule.policy
        return self.default_policy


def _parse_dt(value: str) -> datetime:
    # Accept ISO strings; strip timezone to keep everything in naive UTC.
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def load_org_config(path: Optional[str] = None) -> OrgConfig:
    path = path or get_settings().config_path
    with open(path, "r") as fh:
        raw = yaml.safe_load(fh) or {}

    users = {
        u["id"]: User(
            id=u["id"],
            name=u.get("name", u["id"]),
            telegram_chat_id=(str(u["telegram_chat_id"]) if u.get("telegram_chat_id") else None),
            email=u.get("email"),
        )
        for u in raw.get("users", [])
    }

    schedules = {
        s["id"]: Schedule(
            id=s["id"],
            name=s.get("name", s["id"]),
            rotation=s.get("rotation", "weekly"),
            start=_parse_dt(s["start"]),
            users=list(s.get("users", [])),
        )
        for s in raw.get("schedules", [])
    }

    policies = {}
    for p in raw.get("escalation_policies", []):
        steps = [
            EscalationStep(
                delay_minutes=int(step.get("delay_minutes", 5)),
                targets=[Target(type=t["type"], id=t["id"]) for t in step.get("targets", [])],
            )
            for step in p.get("steps", [])
        ]
        policies[p["id"]] = EscalationPolicy(
            id=p["id"],
            name=p.get("name", p["id"]),
            repeat=int(p.get("repeat", 0)),
            steps=steps,
        )

    routing = raw.get("routing", {}) or {}
    rules = [
        RoutingRule(match=dict(r.get("match", {})), policy=r["policy"])
        for r in routing.get("rules", [])
    ]
    default_policy = routing.get("default_policy") or (next(iter(policies), ""))

    cfg = OrgConfig(
        users=users,
        schedules=schedules,
        policies=policies,
        default_policy=default_policy,
        rules=rules,
    )
    _validate(cfg)
    return cfg


def _validate(cfg: OrgConfig) -> None:
    for sched in cfg.schedules.values():
        if not sched.users:
            raise ValueError(f"schedule '{sched.id}' has no users")
        for uid in sched.users:
            if uid not in cfg.users:
                raise ValueError(f"schedule '{sched.id}' references unknown user '{uid}'")
        if sched.rotation not in ("daily", "weekly"):
            raise ValueError(f"schedule '{sched.id}' has invalid rotation '{sched.rotation}'")
    for pol in cfg.policies.values():
        if not pol.steps:
            raise ValueError(f"policy '{pol.id}' has no steps")
        for step in pol.steps:
            for tgt in step.targets:
                if tgt.type == "user" and tgt.id not in cfg.users:
                    raise ValueError(f"policy '{pol.id}' references unknown user '{tgt.id}'")
                if tgt.type == "schedule" and tgt.id not in cfg.schedules:
                    raise ValueError(f"policy '{pol.id}' references unknown schedule '{tgt.id}'")
    if cfg.default_policy and cfg.default_policy not in cfg.policies:
        raise ValueError(f"default_policy '{cfg.default_policy}' is not defined")


# Process-wide org config, (re)loaded at startup.
_org: Optional[OrgConfig] = None


def org() -> OrgConfig:
    global _org
    if _org is None:
        _org = load_org_config()
    return _org


def reload_org() -> OrgConfig:
    global _org
    _org = load_org_config()
    return _org
