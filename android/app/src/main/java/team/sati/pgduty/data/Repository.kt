package team.sati.pgduty.data

import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit

/**
 * Builds (and caches) a [PgDutyApi] for a given base URL. The base URL can
 * change at runtime via settings, so we rebuild Retrofit when it does.
 */
object ApiProvider {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        })
        .build()

    @Volatile
    private var cachedBaseUrl: String? = null

    @Volatile
    private var cachedApi: PgDutyApi? = null

    @Synchronized
    fun api(baseUrl: String): PgDutyApi {
        val current = cachedApi
        if (current != null && cachedBaseUrl == baseUrl) return current

        val contentType = "application/json".toMediaType()
        val api = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
            .create(PgDutyApi::class.java)

        cachedBaseUrl = baseUrl
        cachedApi = api
        return api
    }
}

/**
 * Thin repository over [PgDutyApi]. Reads the live base URL from settings
 * before every call so changing the server takes effect immediately.
 */
class PgDutyRepository(private val settingsStore: SettingsStore) {

    private suspend fun api(): Pair<PgDutyApi, AppSettings> {
        val s = settingsStore.settings.first()
        return ApiProvider.api(s.normalizedBaseUrl) to s
    }

    suspend fun health(): Health = api().first.health()

    suspend fun oncall(): Map<String, OnCall> = api().first.oncall()

    suspend fun incidents(status: String? = null): List<Incident> =
        api().first.incidents(status = status)

    suspend fun ack(id: Int): Incident {
        val (a, s) = api()
        return a.ack(id, s.identity)
    }

    suspend fun resolve(id: Int): Incident {
        val (a, s) = api()
        return a.resolve(id, s.identity)
    }

    suspend fun snooze(id: Int, minutes: Int): Incident {
        val (a, s) = api()
        return a.snooze(id, minutes, s.identity)
    }

    suspend fun unsnooze(id: Int): Incident {
        val (a, s) = api()
        return a.unsnooze(id, s.identity)
    }
}
