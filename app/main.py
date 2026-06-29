"""FastAPI application: Grafana webhook, incident API, ack/resolve, dashboard."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import func
from sqlmodel import select

from .config import get_settings, org, reload_org
from .db import get_session, init_db
from .escalation import (
    ack_incident,
    ingest_alert,
    resolve_incident,
    snooze_incident,
    tick,
    unsnooze_incident,
)
from .models import Incident, IncidentStatus
from .notifiers import telegram
from .oncall import oncall_snapshot
from .poller import run_grafana_poller, run_telegram_poller
from .security import verify_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
# Quiet per-request chatter from outbound HTTP and the scheduler.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
log = logging.getLogger("pgduty")

settings = get_settings()
# cache_size=0 disables Jinja2's template cache (its cache-key path is broken
# on Python 3.14); templates are tiny so re-parsing per request is fine.
_jinja = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent.parent / "templates")),
    autoescape=select_autoescape(["html"]),
    cache_size=0,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    reload_org()
    log.info("loaded org config: %d users, %d schedules, %d policies",
             len(org().users), len(org().schedules), len(org().policies))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=settings.tick_seconds, id="escalation-tick",
                      max_instances=1, coalesce=True)
    scheduler.start()

    await telegram.set_commands()

    stop = asyncio.Event()
    poller_tasks = [
        asyncio.create_task(run_telegram_poller(stop)),
        asyncio.create_task(run_grafana_poller(stop)),
    ]

    try:
        yield
    finally:
        stop.set()
        scheduler.shutdown(wait=False)
        for task in poller_tasks:
            task.cancel()


app = FastAPI(title="sati-duty", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")


# --- helpers ---------------------------------------------------------------


def _incident_dict(inc: Incident) -> dict:
    return {
        "id": inc.id,
        "title": inc.title,
        "description": inc.description,
        "severity": inc.severity,
        "status": inc.status.value if hasattr(inc.status, "value") else inc.status,
        "policy_id": inc.policy_id,
        "current_step": inc.current_step,
        "labels": inc.labels,
        "source_url": inc.source_url,
        "acked_by": inc.acked_by,
        "next_escalation_at": inc.next_escalation_at.isoformat() if inc.next_escalation_at else None,
        "created_at": inc.created_at.isoformat(),
        "updated_at": inc.updated_at.isoformat(),
        "acked_at": inc.acked_at.isoformat() if inc.acked_at else None,
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "resolved_by": inc.resolved_by,
        "muted_until": inc.muted_until.isoformat() if inc.muted_until else None,
    }


def _local_date(dt: datetime):
    """Local calendar date of a stored naive-UTC timestamp."""
    return dt.replace(tzinfo=timezone.utc).astimezone().date()


def _daily_stats(session, days: int = 7) -> list[dict]:
    """Incidents created vs resolved per local day, most recent first."""
    rows = session.exec(select(Incident.created_at, Incident.resolved_at)).all()
    created: dict = defaultdict(int)
    resolved: dict = defaultdict(int)
    for c, r in rows:
        if c:
            created[_local_date(c)] += 1
        if r:
            resolved[_local_date(r)] += 1

    today = datetime.now(timezone.utc).astimezone().date()
    out = []
    for i in range(days):
        d = today - timedelta(days=i)
        out.append({
            "label": d.strftime("%a %d %b"),
            "created": created.get(d, 0),
            "resolved": resolved.get(d, 0),
        })
    max_c = max((d["created"] for d in out), default=0) or 1
    for d in out:
        d["pct"] = round(d["created"] / max_c * 100)
    return out


def _resolver_label(who: str | None) -> str:
    """Human label for who resolved an incident; flags Grafana auto-resolves."""
    if not who:
        return ""
    if who.startswith("grafana"):
        return "🤖 auto (Grafana)"
    return f"by {who}"


def _fmt_local(dt: datetime | None) -> str:
    """Stored naive-UTC timestamp -> readable local-time string for the UI."""
    if not dt:
        return "—"
    return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _grafana_link(url: str) -> str:
    """Rewrite a stored Grafana URL's host to the reachable Grafana address.
    Grafana emits generatorURLs against its own root_url (often localhost);
    point them at PGDUTY_GRAFANA_URL so the dashboard links actually work."""
    base = settings.grafana_url
    if not url or not base:
        return url
    b, u = urlsplit(base), urlsplit(url)
    return urlunsplit((b.scheme, b.netloc, u.path, u.query, u.fragment))


# --- health & meta ---------------------------------------------------------


@app.get("/healthz")
async def healthz():
    return {"ok": True, "version": app.version}


@app.get("/oncall")
async def oncall():
    return oncall_snapshot(org())


@app.post("/reload")
async def reload_config():
    reload_org()
    return {"reloaded": True, "users": len(org().users), "policies": len(org().policies)}


# --- Grafana webhook -------------------------------------------------------


@app.post("/webhook/grafana")
async def grafana_webhook(request: Request, token: str | None = Query(default=None)):
    if settings.webhook_token and token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="bad webhook token")

    payload = await request.json()
    alerts = payload.get("alerts")
    if alerts is None:
        # Allow a bare single-alert payload too.
        alerts = [payload]

    cfg = org()
    handled = []
    with get_session() as session:
        for alert in alerts:
            inc = await ingest_alert(session, alert, cfg)
            if inc:
                handled.append(inc.id)
    return {"received": len(alerts), "incidents": handled}


# --- incident API ----------------------------------------------------------


@app.get("/incidents")
async def list_incidents(status: str | None = None, limit: int = 100):
    with get_session() as session:
        stmt = select(Incident).order_by(Incident.id.desc()).limit(limit)
        if status:
            stmt = select(Incident).where(Incident.status == status).order_by(Incident.id.desc()).limit(limit)
        rows = session.exec(stmt).all()
        return [_incident_dict(i) for i in rows]


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: int):
    with get_session() as session:
        inc = session.get(Incident, incident_id)
        if not inc:
            raise HTTPException(status_code=404, detail="not found")
        return _incident_dict(inc)


def _check_link_token(incident_id: int, action: str, token: str | None) -> None:
    """For GET links (Google Chat / email) require a signed token. POSTs from
    the dashboard / API are trusted (same origin)."""
    if token is not None and not verify_token(incident_id, action, token):
        raise HTTPException(status_code=403, detail="bad token")


@app.api_route("/incidents/{incident_id}/ack", methods=["GET", "POST"])
async def ack(incident_id: int, request: Request, token: str | None = Query(default=None),
              who: str = Query(default="web")):
    _check_link_token(incident_id, "ack", token)
    with get_session() as session:
        inc = await ack_incident(session, incident_id, who)
        if not inc:
            raise HTTPException(status_code=404, detail="not found")
    if request.method == "GET":
        return RedirectResponse(url="/", status_code=303)
    return _incident_dict(inc)


@app.api_route("/incidents/{incident_id}/snooze", methods=["GET", "POST"])
async def snooze(incident_id: int, request: Request, minutes: int = Query(default=60),
                 token: str | None = Query(default=None), who: str = Query(default="web")):
    _check_link_token(incident_id, "snooze", token)
    with get_session() as session:
        inc = await snooze_incident(session, incident_id, minutes, who)
        if not inc:
            raise HTTPException(status_code=404, detail="not found")
    if request.method == "GET":
        return RedirectResponse(url="/", status_code=303)
    return _incident_dict(inc)


@app.api_route("/incidents/{incident_id}/unsnooze", methods=["GET", "POST"])
async def unsnooze(incident_id: int, request: Request, token: str | None = Query(default=None),
                   who: str = Query(default="web")):
    _check_link_token(incident_id, "unsnooze", token)
    with get_session() as session:
        inc = await unsnooze_incident(session, incident_id, who)
        if not inc:
            raise HTTPException(status_code=404, detail="not found")
    if request.method == "GET":
        return RedirectResponse(url="/", status_code=303)
    return _incident_dict(inc)


@app.api_route("/incidents/{incident_id}/resolve", methods=["GET", "POST"])
async def resolve(incident_id: int, request: Request, token: str | None = Query(default=None),
                  who: str = Query(default="web")):
    _check_link_token(incident_id, "resolve", token)
    with get_session() as session:
        inc = await resolve_incident(session, incident_id, who)
        if not inc:
            raise HTTPException(status_code=404, detail="not found")
    if request.method == "GET":
        return RedirectResponse(url="/", status_code=303)
    return _incident_dict(inc)


# --- dashboard -------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=25),
):
    page = max(1, page)
    page_size = min(max(page_size, 5), 200)
    q = (q or "").strip() or None

    # Build the filter once and apply it to both the count and the page query.
    conds = []
    if status:
        conds.append(Incident.status == status)
    if severity:
        conds.append(Incident.severity == severity)
    if q:
        conds.append(Incident.title.ilike(f"%{q}%"))

    with get_session() as session:
        count_stmt = select(func.count(Incident.id))
        data_stmt = select(Incident)
        for c in conds:
            count_stmt = count_stmt.where(c)
            data_stmt = data_stmt.where(c)

        total = session.exec(count_stmt).one()
        rows = session.exec(
            data_stmt.order_by(Incident.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        # Global counts for the header pills (independent of the active filter).
        triggered_count = session.exec(
            select(func.count(Incident.id)).where(Incident.status == IncidentStatus.TRIGGERED)
        ).one()
        acknowledged_count = session.exec(
            select(func.count(Incident.id)).where(Incident.status == IncidentStatus.ACKNOWLEDGED)
        ).one()
        open_count = triggered_count + acknowledged_count
        total_all = session.exec(select(func.count(Incident.id))).one()
        severities = [s for s in session.exec(select(Incident.severity).distinct()).all() if s]

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        incidents = []
        for i in rows:
            d = _incident_dict(i)
            d["source_url"] = _grafana_link(i.source_url)
            d["created_local"] = _fmt_local(i.created_at)
            d["acked_local"] = _fmt_local(i.acked_at)
            d["resolved_local"] = _fmt_local(i.resolved_at)
            d["resolved_by_label"] = _resolver_label(i.resolved_by)
            d["is_muted"] = bool(i.muted_until and i.muted_until > now)
            d["muted_local"] = _fmt_local(i.muted_until)
            incidents.append(d)

    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    # Query string carrying the current filters (minus page) for page links.
    base_q = urlencode({k: v for k, v in {
        "status": status, "severity": severity, "q": q, "page_size": page_size,
    }.items() if v})

    html = _jinja.get_template("dashboard.html").render(
        incidents=incidents,
        oncall=oncall_snapshot(org()),
        open_count=open_count,
        triggered_count=triggered_count,
        acknowledged_count=acknowledged_count,
        total_all=total_all,
        total=total,
        page=page,
        pages=pages,
        page_size=page_size,
        statuses=[s.value for s in IncidentStatus],
        severities=sorted(severities),
        f_status=status or "",
        f_severity=severity or "",
        f_q=q or "",
        base_q=base_q,
    )
    return HTMLResponse(html)


@app.get("/stats", response_class=HTMLResponse)
async def stats(days: int = Query(default=7)):
    ranges = [7, 14, 30, 90]
    days = days if days in ranges else 7
    with get_session() as session:
        daily = _daily_stats(session, days=days)
    total_new = sum(d["created"] for d in daily)
    total_resolved = sum(d["resolved"] for d in daily)
    html = _jinja.get_template("stats.html").render(
        daily=daily,
        days=days,
        ranges=ranges,
        total_new=total_new,
        total_resolved=total_resolved,
    )
    return HTMLResponse(html)
