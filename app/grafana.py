"""Pull-based Grafana ingest.

Counterpart to the webhook push path: instead of waiting for Grafana to POST
alerts to /webhook/grafana, we poll Grafana's built-in Alertmanager-compatible
API for the set of currently-firing alert instances and feed them through the
same ingest_alert() dedup path.

Grafana only returns *active* alerts here — a resolved alert simply drops out of
the list rather than sending a `resolved` status. The poller (see poller.py)
diffs successive snapshots to auto-resolve incidents whose alert has cleared.
"""
from __future__ import annotations

import logging

import httpx

from .config import get_settings

log = logging.getLogger("pgduty.grafana")

# Grafana's embedded Alertmanager exposes the standard AM v2 alerts endpoint.
_ALERTS_PATH = "/api/alertmanager/grafana/api/v2/alerts"


def _enabled() -> bool:
    s = get_settings()
    return bool(s.grafana_url and s.grafana_token)


def _normalize(alert: dict) -> dict | None:
    """Map a Grafana AM v2 alert object onto the Alertmanager *webhook* shape
    that escalation.ingest_alert() consumes. Returns None if it can't be keyed."""
    labels = dict(alert.get("labels", {}) or {})
    fingerprint = alert.get("fingerprint")
    if not fingerprint:
        # Fall back to a label-derived key so ingest_alert can still dedup.
        if not labels:
            return None
        fingerprint = str(abs(hash(frozenset(labels.items()))))
    return {
        # The v2 API only returns firing instances; status is an object
        # ({"state": "active"|"suppressed"}), so we assert "firing" ourselves.
        "status": "firing",
        "labels": labels,
        "annotations": dict(alert.get("annotations", {}) or {}),
        "fingerprint": fingerprint,
        "generatorURL": alert.get("generatorURL", "") or "",
    }


async def fetch_active_alerts() -> list[dict] | None:
    """Return currently-firing alerts as Alertmanager-webhook dicts.

    Returns None on any transport/HTTP error so the poller can tell a real
    "nothing is firing" (``[]``) from a failed fetch and avoid spuriously
    auto-resolving everything when Grafana is briefly unreachable.
    """
    s = get_settings()
    if not _enabled():
        return None
    url = f"{s.grafana_url}{_ALERTS_PATH}"
    headers = {"Authorization": f"Bearer {s.grafana_token}"}
    params = {"active": "true", "silenced": "false", "inhibited": "false"}
    try:
        async with httpx.AsyncClient(timeout=20, verify=s.grafana_verify_ssl) as client:
            resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            log.warning("grafana alerts fetch -> HTTP %s: %s",
                        resp.status_code, resp.text[:200])
            return None
        raw = resp.json()
    except Exception as exc:
        log.warning("grafana alerts fetch failed: %s", exc)
        return None

    if not isinstance(raw, list):
        log.warning("grafana alerts: unexpected payload type %s", type(raw).__name__)
        return None

    out = []
    for a in raw:
        norm = _normalize(a) if isinstance(a, dict) else None
        if norm:
            out.append(norm)
    return out
