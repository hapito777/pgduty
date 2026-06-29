package team.sati.pgduty.notify

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import team.sati.pgduty.data.Incident
import team.sati.pgduty.data.PgDutyRepository
import team.sati.pgduty.data.SettingsStore

/**
 * Foreground service that polls pgduty on an interval and raises a high-priority
 * notification whenever an incident enters (or re-enters) the `triggered` state
 * — a self-contained near-real-time pager that needs no FCM/Firebase and no
 * server changes. Resolved/acked incidents have their page auto-cleared.
 */
class MonitorService : Service() {

    private val scope = CoroutineScope(SupervisorJob())
    private var loop: Job? = null

    private lateinit var settingsStore: SettingsStore
    private lateinit var repo: PgDutyRepository

    // Incidents we've already paged for, by id, with the status at notify time.
    private val notified = HashMap<Int, String>()

    override fun onCreate() {
        super.onCreate()
        settingsStore = SettingsStore(applicationContext)
        repo = PgDutyRepository(settingsStore)
        Notifications.ensureChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundCompat("Watching for incidents…")
        if (loop == null) loop = scope.launch { pollLoop() }
        return START_STICKY
    }

    private suspend fun pollLoop() {
        while (true) {
            val settings = settingsStore.settings.first()
            if (!settings.monitorEnabled) {
                stopSelf()
                return
            }
            val ok = runCatching { pollOnce() }.isSuccess
            updateForeground(
                if (ok) "Monitoring · polling every ${settings.pollSeconds}s"
                else "Monitoring · can't reach server",
            )
            delay(settings.pollSeconds.coerceIn(10, 600) * 1000L)
        }
    }

    /** One fetch + diff. Pages on new/re-triggered incidents; clears closed ones. */
    private suspend fun pollOnce() {
        val incidents: List<Incident> = repo.incidents()
        val nm = NotificationManagerCompat.from(this)
        val seenIds = HashSet<Int>()

        for (inc in incidents) {
            seenIds.add(inc.id)
            val previouslyNotified = notified[inc.id]
            when (inc.status) {
                "triggered" -> {
                    // Notify once per triggered episode (and again if it was
                    // resolved/acked and later re-triggered).
                    if (previouslyNotified != "triggered") {
                        if (nm.areNotificationsEnabled()) {
                            nm.notify(
                                Notifications.incidentNotificationId(inc.id),
                                Notifications.incidentNotification(this, inc),
                            )
                        }
                        notified[inc.id] = "triggered"
                    }
                }
                else -> {
                    // Acked or resolved → clear any standing page.
                    if (previouslyNotified == "triggered") {
                        Notifications.cancelIncident(this, inc.id)
                    }
                    notified[inc.id] = inc.status
                }
            }
        }

        // Forget incidents no longer returned (and clear stale pages).
        val gone = notified.keys.filter { it !in seenIds }
        for (id in gone) {
            Notifications.cancelIncident(this, id)
            notified.remove(id)
        }
    }

    private fun startForegroundCompat(text: String) {
        val notification = Notifications.monitorNotification(this, text)
        // specialUse (API 34+) suits a continuous on-call monitor and avoids
        // Android 15's per-day runtime cap on dataSync FGS. Older APIs that
        // require a type but predate specialUse fall back to dataSync.
        when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE ->
                startForeground(
                    Notifications.MONITOR_NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
                )
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ->
                startForeground(
                    Notifications.MONITOR_NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
                )
            else ->
                startForeground(Notifications.MONITOR_NOTIFICATION_ID, notification)
        }
    }

    private fun updateForeground(text: String) {
        if (NotificationManagerCompat.from(this).areNotificationsEnabled()) {
            NotificationManagerCompat.from(this)
                .notify(Notifications.MONITOR_NOTIFICATION_ID, Notifications.monitorNotification(this, text))
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        fun start(context: Context) {
            val intent = Intent(context, MonitorService::class.java)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, MonitorService::class.java))
        }
    }
}
