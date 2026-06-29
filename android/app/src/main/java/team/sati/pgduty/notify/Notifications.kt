package team.sati.pgduty.notify

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import team.sati.pgduty.MainActivity
import team.sati.pgduty.R
import team.sati.pgduty.data.Incident

/** Notification channels + builders for incident pages and the monitor service. */
object Notifications {

    const val CHANNEL_INCIDENTS = "pgduty_incidents"
    const val CHANNEL_MONITOR = "pgduty_monitor"

    /** Foreground-service notification id (stable; never collides with incidents). */
    const val MONITOR_NOTIFICATION_ID = 1

    /** Incident notifications use the incident id offset past the service id. */
    fun incidentNotificationId(incidentId: Int): Int = 1000 + incidentId

    fun ensureChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)

        val incidents = NotificationChannel(
            CHANNEL_INCIDENTS,
            "Incident pages",
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = "Alerts when a new incident is triggered."
            enableVibration(true)
            enableLights(true)
        }

        val monitor = NotificationChannel(
            CHANNEL_MONITOR,
            "Monitoring",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "Ongoing notification while pgduty is being monitored."
            setShowBadge(false)
        }

        nm.createNotificationChannel(incidents)
        nm.createNotificationChannel(monitor)
    }

    /** The persistent low-priority notification for the foreground service. */
    fun monitorNotification(context: Context, text: String): Notification =
        NotificationCompat.Builder(context, CHANNEL_MONITOR)
            .setContentTitle("sati-duty monitoring")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_stat_alert)
            .setOngoing(true)
            .setContentIntent(openAppIntent(context))
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

    /** A high-priority page for one triggered incident, with Ack/Resolve actions. */
    fun incidentNotification(context: Context, incident: Incident): Notification {
        val title = "🔴 #${incident.id} ${incident.title}"
        val body = buildString {
            append("severity: ${incident.severity}")
            if (incident.description.isNotBlank()) append("\n${incident.description}")
        }

        return NotificationCompat.Builder(context, CHANNEL_INCIDENTS)
            .setContentTitle(title)
            .setContentText(incident.severity)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setSmallIcon(R.drawable.ic_stat_alert)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(openAppIntent(context))
            .addAction(
                0, "Ack",
                actionIntent(context, IncidentActionReceiver.ACTION_ACK, incident.id),
            )
            .addAction(
                0, "Resolve",
                actionIntent(context, IncidentActionReceiver.ACTION_RESOLVE, incident.id),
            )
            .build()
    }

    fun cancelIncident(context: Context, incidentId: Int) {
        NotificationManagerCompat.from(context).cancel(incidentNotificationId(incidentId))
    }

    private fun openAppIntent(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(
            context, 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    private fun actionIntent(context: Context, action: String, incidentId: Int): PendingIntent {
        val intent = Intent(context, IncidentActionReceiver::class.java).apply {
            this.action = action
            putExtra(IncidentActionReceiver.EXTRA_INCIDENT_ID, incidentId)
        }
        // Unique request code per (action, incident) so PendingIntents don't clash.
        val requestCode = incidentId * 10 + action.hashCode().and(0x7)
        return PendingIntent.getBroadcast(
            context, requestCode, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }
}
