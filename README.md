# pgduty

A small, self-hosted **PagerDuty-style on-call & escalation service** for Grafana alerts.

Grafana fires an alert → pgduty dedups it into an **incident**, picks an
**escalation policy** by alert labels, pages whoever is **on-call**, and keeps
**escalating** through the ladder until someone **acknowledges** or the alert
**resolves**. Paging goes to **Telegram** (targeted DMs with Ack/Resolve
buttons) and **Google Chat** (space notifications with ack links).

## Features

- **Grafana webhook** ingest (Alertmanager-style payload), dedup by fingerprint
- **On-call schedules** — daily/weekly rotations, config-as-code
- **Escalation policies** — multi-step ladders with per-step delays + repeat
- **Acknowledge / resolve** from Telegram buttons, Google Chat links, the web
  dashboard, or the REST API
- **Auto-resolve** when Grafana sends a `resolved` status
- **Web dashboard** at `/` with live on-call + open incidents
- SQLite by default (no external services); Postgres-ready

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # fill in TELEGRAM_BOT_TOKEN / GOOGLE_CHAT_WEBHOOK_URL
# edit config.yaml: add your users, schedules, escalation policies

python run.py                 # http://localhost:8080
```

Open the dashboard at <http://localhost:8080/>.

## Configure

- **Secrets & runtime** → `.env` (see `.env.example`)
- **Org (users / schedules / policies / routing)** → `config.yaml`

`POST /reload` re-reads `config.yaml` without a restart.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather), put the token in
   `TELEGRAM_BOT_TOKEN`.
2. Send your bot any message, then find your numeric chat id (e.g. via
   `https://api.telegram.org/bot<token>/getUpdates`) and set it as
   `telegram_chat_id` on your user in `config.yaml`.
3. Pages arrive as DMs with **Acknowledge / Resolve** buttons (handled by the
   built-in long-polling loop — no public URL required).

### Google Chat

Create an *Incoming Webhook* in the target space and put the URL in
`GOOGLE_CHAT_WEBHOOK_URL`. Incidents post as cards; the Ack/Resolve buttons are
signed links back into pgduty (so `PGDUTY_BASE_URL` must be reachable from your
browser).

## Wire up Grafana

In Grafana → **Alerting → Contact points**, add a **Webhook** contact point:

- URL: `http://<pgduty-host>:8080/webhook/grafana`
  (append `?token=<PGDUTY_WEBHOOK_TOKEN>` if you set one)
- HTTP method: `POST`

Then route your notification policy to it. Grafana sends an Alertmanager-style
payload; pgduty handles both `firing` and `resolved`.

### Or: pull from Grafana (polling)

If you'd rather not configure a contact point — or can't reach pgduty from
Grafana — pgduty can **poll Grafana** for firing alerts instead. Set both in
`.env`:

```bash
PGDUTY_GRAFANA_URL=https://grafana.example.com   # no trailing slash
PGDUTY_GRAFANA_TOKEN=<service-account-token>      # alerting read scope
PGDUTY_GRAFANA_POLL_SECONDS=30                    # default
```

Create the token in Grafana → **Administration → Service accounts** (a role
with alerting read is enough). pgduty then queries Grafana's built-in
Alertmanager API (`/api/alertmanager/grafana/api/v2/alerts`) every
`PGDUTY_GRAFANA_POLL_SECONDS` and feeds firing instances through the same
dedup/escalation path as the webhook.

Because the API only returns *currently firing* alerts, resolution is implicit:
when an alert clears in Grafana it drops out of the set and pgduty
**auto-resolves** the matching incident. A failed poll never mass-resolves — it
only reconciles after a successful fetch. Push (webhook) and pull (polling) can
run at the same time; they dedup by the same fingerprint.

Test it without Grafana:

```bash
curl -X POST localhost:8080/webhook/grafana -H 'content-type: application/json' -d '{
  "alerts": [{
    "status": "firing",
    "labels": {"alertname": "HighErrorRate", "severity": "critical", "service": "api"},
    "annotations": {"summary": "5xx rate > 10%", "description": "api error budget burning"},
    "fingerprint": "demo-1",
    "generatorURL": "https://grafana.example/d/abc"
  }]
}'
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/webhook/grafana` | Ingest Grafana/Alertmanager alerts |
| GET  | `/incidents` | List incidents (`?status=triggered`) |
| GET  | `/incidents/{id}` | Incident detail |
| POST/GET | `/incidents/{id}/ack` | Acknowledge (GET link needs `?token=`) |
| POST/GET | `/incidents/{id}/resolve` | Resolve |
| GET  | `/oncall` | Who is on-call now, per schedule |
| POST | `/reload` | Reload `config.yaml` |
| GET  | `/` | Web dashboard |
| GET  | `/healthz` | Health check |

## How escalation works

When an incident is created it pages step 1's targets and waits
`delay_minutes`. If still un-acked, it advances to step 2, and so on. After the
last step it repeats the whole ladder `repeat` times, then goes quiet (but stays
`triggered`). Acknowledging or resolving stops escalation immediately. A
background tick (every `PGDUTY_TICK_SECONDS`) drives this off the incident's
`next_escalation_at`, so it survives restarts.

## Run as a service

Directly:

```bash
python run.py     # or: uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Docker Compose

```bash
cp .env.example .env          # fill in tokens
docker compose up -d          # dashboard on http://localhost:8099
docker compose logs -f
```

- The host maps **8099 → 8080** (host 8080 is in use on this machine; change in
  `docker-compose.yml` if you like).
- `config.yaml` is mounted read-only — edit it on the host and `POST /reload`.
- Incidents persist in the `pgduty-data` named volume (SQLite).
- A Postgres service is included commented-out in `docker-compose.yml`.
