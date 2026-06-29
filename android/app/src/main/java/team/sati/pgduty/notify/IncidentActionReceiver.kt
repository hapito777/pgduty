package team.sati.pgduty.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import team.sati.pgduty.data.PgDutyRepository
import team.sati.pgduty.data.SettingsStore

/** Handles Ack/Resolve tapped directly on an incident notification. */
class IncidentActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val incidentId = intent.getIntExtra(EXTRA_INCIDENT_ID, -1)
        if (incidentId < 0) return
        val action = intent.action ?: return

        // Network must happen off the main thread; keep the broadcast alive.
        val pending = goAsync()
        val appContext = context.applicationContext
        val repo = PgDutyRepository(SettingsStore(appContext))

        CoroutineScope(Dispatchers.IO).launch {
            val verb = if (action == ACTION_ACK) "Acknowledged" else "Resolved"
            try {
                when (action) {
                    ACTION_ACK -> repo.ack(incidentId)
                    ACTION_RESOLVE -> repo.resolve(incidentId)
                }
                // Clear the page and confirm.
                NotificationManagerCompat.from(appContext)
                    .cancel(Notifications.incidentNotificationId(incidentId))
                toast(appContext, "$verb #$incidentId")
            } catch (e: Exception) {
                toast(appContext, "Failed to ${if (action == ACTION_ACK) "ack" else "resolve"} #$incidentId: ${e.message}")
            } finally {
                pending.finish()
            }
        }
    }

    private suspend fun toast(context: Context, msg: String) {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, msg, Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        const val ACTION_ACK = "team.sati.pgduty.ACK"
        const val ACTION_RESOLVE = "team.sati.pgduty.RESOLVE"
        const val EXTRA_INCIDENT_ID = "incident_id"
    }
}
