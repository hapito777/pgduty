"""Core logic tests: on-call rotation, routing, target expansion, and the
full escalation ladder (advance -> repeat -> exhaust). Run with `pytest`."""
import asyncio
from datetime import datetime, timedelta

from app.config import (
    EscalationPolicy,
    EscalationStep,
    OrgConfig,
    RoutingRule,
    Schedule,
    Target,
    User,
)
from app.grafana import _normalize
from app.oncall import current_oncall, expand_targets


def _cfg() -> OrgConfig:
    users = {
        "a": User(id="a", name="Alice", telegram_chat_id="1"),
        "b": User(id="b", name="Bob", telegram_chat_id="2"),
    }
    sched = Schedule(id="s", name="S", rotation="weekly",
                     start=datetime(2026, 1, 1), users=["a", "b"])
    policy = EscalationPolicy(
        id="p", name="P", repeat=1,
        steps=[
            EscalationStep(delay_minutes=5, targets=[Target("schedule", "s")]),
            EscalationStep(delay_minutes=10, targets=[Target("user", "b")]),
        ],
    )
    return OrgConfig(
        users=users,
        schedules={"s": sched},
        policies={"p": policy},
        default_policy="p",
        rules=[RoutingRule(match={"severity": "critical"}, policy="p")],
    )


def test_oncall_weekly_rotation():
    sched = _cfg().schedules["s"]
    # Week 0 -> Alice, week 1 -> Bob, week 2 -> Alice again.
    assert current_oncall(sched, datetime(2026, 1, 1)) == "a"
    assert current_oncall(sched, datetime(2026, 1, 3)) == "a"
    assert current_oncall(sched, datetime(2026, 1, 8)) == "b"
    assert current_oncall(sched, datetime(2026, 1, 15)) == "a"


def test_routing_matches_then_falls_back():
    cfg = _cfg()
    assert cfg.route({"severity": "critical"}) == "p"
    assert cfg.route({"severity": "info"}) == "p"  # default policy


def test_expand_targets_dedups_and_resolves_schedule():
    cfg = _cfg()
    at = datetime(2026, 1, 1)  # Alice on-call
    assert expand_targets(cfg, [Target("schedule", "s"), Target("user", "a")], at) == ["a"]


def test_grafana_normalize_maps_to_webhook_shape():
    # A Grafana AM v2 alert object (status is an object, not "firing"/"resolved").
    alert = {
        "labels": {"alertname": "HighErrorRate", "severity": "critical"},
        "annotations": {"summary": "5xx > 10%"},
        "generatorURL": "https://grafana.example/d/abc",
        "fingerprint": "abc123",
        "status": {"state": "active"},
    }
    norm = _normalize(alert)
    assert norm["status"] == "firing"  # asserted by us; AM v2 only returns firing
    assert norm["fingerprint"] == "abc123"
    assert norm["labels"]["severity"] == "critical"
    assert norm["annotations"]["summary"] == "5xx > 10%"
    assert norm["generatorURL"] == "https://grafana.example/d/abc"


def test_grafana_normalize_falls_back_to_label_key_and_skips_empty():
    # No fingerprint -> derive a stable key from labels so ingest can dedup.
    norm = _normalize({"labels": {"alertname": "X"}})
    assert norm["fingerprint"]
    # Nothing to key on at all -> skipped.
    assert _normalize({}) is None


def test_escalation_ladder(tmp_path, monkeypatch):
    # Point the DB at a temp file BEFORE importing db/engine-bound modules.
    monkeypatch.setenv("PGDUTY_DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("GOOGLE_CHAT_WEBHOOK_URL", "")

    import importlib

    from app import config as config_mod
    from app import db as db_mod

    config_mod.get_settings.cache_clear()
    importlib.reload(db_mod)
    from app import escalation as esc
    importlib.reload(esc)

    db_mod.init_db()
    cfg = _cfg()
    # Make org() (used internally by tick/ack/resolve) return the test config.
    config_mod._org = cfg

    async def scenario():
        with db_mod.get_session() as s:
            inc = await esc.ingest_alert(
                s,
                {"status": "firing", "labels": {"severity": "critical"},
                 "annotations": {"summary": "boom"}, "fingerprint": "x"},
                cfg,
            )
            assert inc.current_step == 0
            assert inc.next_escalation_at is not None

            # Dedup: same fingerprint firing again returns the same incident.
            inc2 = await esc.ingest_alert(
                s, {"status": "firing", "labels": {"severity": "critical"}, "fingerprint": "x"}, cfg
            )
            assert inc2.id == inc.id

            # Force the timer due and advance: step 0 -> step 1.
            inc.next_escalation_at = db_mod.utcnow() - timedelta(seconds=1)
            s.add(inc); s.commit()
            await esc.tick()
            s.refresh(inc)
            assert inc.current_step == 1

            # Advance past last step: repeat=1 restarts the ladder at step 0.
            inc.next_escalation_at = db_mod.utcnow() - timedelta(seconds=1)
            s.add(inc); s.commit()
            await esc.tick()
            s.refresh(inc)
            assert inc.current_step == 0
            assert inc.repeats_left == 0

            # Exhaust: no repeats left -> escalation stops (timer cleared).
            inc.current_step = 1
            inc.next_escalation_at = db_mod.utcnow() - timedelta(seconds=1)
            s.add(inc); s.commit()
            await esc.tick()
            s.refresh(inc)
            assert inc.next_escalation_at is None
            assert inc.status.value == "triggered"

            # Snooze: a due incident that's muted is skipped until the mute ends.
            await esc.snooze_incident(s, inc.id, 30, "alice")
            s.refresh(inc)
            assert inc.muted_until is not None
            inc.current_step = 0
            inc.next_escalation_at = db_mod.utcnow() - timedelta(seconds=1)
            s.add(inc); s.commit()
            await esc.tick()
            s.refresh(inc)
            assert inc.current_step == 0  # not advanced while muted

            # Mute expired -> tick resumes escalation.
            inc.muted_until = db_mod.utcnow() - timedelta(seconds=1)
            inc.next_escalation_at = db_mod.utcnow() - timedelta(seconds=1)
            s.add(inc); s.commit()
            await esc.tick()
            s.refresh(inc)
            assert inc.current_step == 1

        # ack stops escalation; resolve closes it.
        with db_mod.get_session() as s:
            acked = await esc.ack_incident(s, inc.id, "alice")
            assert acked.status.value == "acknowledged"
        with db_mod.get_session() as s:
            resolved = await esc.resolve_incident(s, inc.id, "alice")
            assert resolved.status.value == "resolved"

    asyncio.run(scenario())
