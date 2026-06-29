package team.sati.pgduty.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "pgduty_settings")

/** App configuration: where the pgduty server lives, the identity used when
 *  acking/resolving (sent as `who`), and background-monitor settings. */
data class AppSettings(
    val baseUrl: String,
    val identity: String,
    val monitorEnabled: Boolean,
    val pollSeconds: Int,
) {
    /** Base URL guaranteed to end with a single trailing slash for Retrofit. */
    val normalizedBaseUrl: String
        get() = baseUrl.trim().trimEnd('/') + "/"
}

class SettingsStore(private val context: Context) {

    private val keyBaseUrl = stringPreferencesKey("base_url")
    private val keyIdentity = stringPreferencesKey("identity")
    private val keyMonitor = booleanPreferencesKey("monitor_enabled")
    private val keyPoll = intPreferencesKey("poll_seconds")

    val settings: Flow<AppSettings> = context.dataStore.data.map { prefs ->
        AppSettings(
            // 10.0.2.2 is the host machine's loopback as seen from the emulator.
            baseUrl = prefs[keyBaseUrl] ?: "http://10.0.2.2:8080",
            identity = prefs[keyIdentity] ?: "android",
            monitorEnabled = prefs[keyMonitor] ?: false,
            pollSeconds = prefs[keyPoll] ?: 30,
        )
    }

    suspend fun update(baseUrl: String, identity: String) {
        context.dataStore.edit { prefs ->
            prefs[keyBaseUrl] = baseUrl.trim()
            prefs[keyIdentity] = identity.trim().ifBlank { "android" }
        }
    }

    suspend fun setMonitor(enabled: Boolean, pollSeconds: Int) {
        context.dataStore.edit { prefs ->
            prefs[keyMonitor] = enabled
            prefs[keyPoll] = pollSeconds.coerceIn(10, 600)
        }
    }
}
