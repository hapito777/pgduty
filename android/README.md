# sati-duty — Android

A native Android client for [pgduty](../README.md). It mirrors the web
dashboard: who's **on-call**, the live **incident** list, and **stats** — and
lets you **acknowledge / snooze / resolve** incidents from your phone.

It's a thin client over the pgduty REST API (`/oncall`, `/incidents`,
`/incidents/{id}/ack|snooze|unsnooze|resolve`, `/healthz`). No server changes
are needed.

## Stack

- Kotlin + Jetpack Compose (Material 3), dark theme matching the dashboard
- Retrofit + OkHttp + kotlinx.serialization
- DataStore for settings, ViewModel + coroutines, auto-refresh every 15s

## Build & run

Open the `android/` folder in **Android Studio** (Koala or newer) and Run, or
from the command line:

```bash
cd android
./gradlew installDebug      # builds and installs on a connected device/emulator
```

Requires JDK 17 and the Android SDK (`compileSdk 35`). The Gradle wrapper
(8.9) is committed, so no separate Gradle install is needed.

## Configure

On first launch, open **Settings** (gear icon) and set:

- **Base URL** — where pgduty is reachable.
  - Android **emulator** → host machine is `http://10.0.2.2:8080`
  - **Real device** → use the server's LAN address, e.g. `http://192.168.1.10:8080`
- **Your name** — sent as the `who` param when you ack/resolve (shows up in the
  incident history).

Tap **Test connection** to verify, then **Save**.

Cleartext HTTP is allowed (see `res/xml/network_security_config.xml`) since
pgduty is usually self-hosted over plain HTTP on a LAN. Front it with TLS and
tighten that config for anything exposed.

## Screens

| Screen | Shows |
|---|---|
| **Incidents** | count pills (open/triggered/acknowledged/total), on-call cards, filters (status / severity / title search), and incident cards with Ack · 😴 1h/4h · Unsnooze · Resolve actions |
| **Stats** | created-vs-resolved per day over 7/14/30/90 days (computed client-side from the incident list) |
| **Settings** | base URL + identity, connection test, and **real-time alerts** (background monitoring) |

## Real-time alerts (background monitoring)

Turn on **Monitor in background** in Settings to get near-real-time pages
without Firebase/FCM and without any server changes:

- A foreground service polls `/incidents` every *N* seconds (configurable,
  10–600; default 30) and fires a **high-priority notification** the moment an
  incident enters the `triggered` state.
- The notification has **Ack** and **Resolve** actions that hit the API
  directly — no need to open the app.
- When an incident is acked/resolved (by you or anyone else), its page is
  cleared automatically.
- A persistent low-priority "monitoring" notification shows while active (this
  is what keeps the service alive); monitoring auto-resumes after a reboot.
- On Android 13+ the app requests the notification permission when you enable
  the toggle.

Trade-off vs. FCM: this keeps a foreground service running, so it uses more
battery than true server push would. FCM would be lighter but needs a Firebase
project plus server-side changes to store device tokens and push to them — out
of scope for a self-hosted tool with no account setup. The polling monitor is
self-contained and works against any pgduty instance as-is.

## Notes / limitations

- The incident list fetches the most recent 200 incidents (the server's default
  cap), so the 90-day stats view reflects that window.
- Filtering, paging and stats are done client-side off the fetched list, so
  they don't issue extra requests.
- Real-time alerts use a polling foreground service (see above), not FCM.
