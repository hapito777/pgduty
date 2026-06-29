package team.sati.pgduty.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import team.sati.pgduty.data.SettingsStore

/** Restarts the monitor after reboot if the user had it enabled. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val pending = goAsync()
        val appContext = context.applicationContext
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val enabled = SettingsStore(appContext).settings.first().monitorEnabled
                // Background FGS starts are restricted on newer Android; best-effort.
                if (enabled) runCatching { MonitorService.start(appContext) }
            } finally {
                pending.finish()
            }
        }
    }
}
