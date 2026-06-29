package team.sati.pgduty.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import team.sati.pgduty.data.Incident
import team.sati.pgduty.data.OnCall
import team.sati.pgduty.data.PgDutyRepository
import team.sati.pgduty.data.TimeFormat
import java.time.LocalDate

/** One bar in the stats view: incidents created vs resolved on a local day. */
data class DailyStat(
    val date: LocalDate,
    val label: String,
    val created: Int,
    val resolved: Int,
)

data class UiState(
    val incidents: List<Incident> = emptyList(),
    val oncall: Map<String, OnCall> = emptyMap(),
    val loading: Boolean = false,
    val refreshing: Boolean = false,
    val error: String? = null,
    val connected: Boolean = false,
    val version: String = "",
    // Filters (mirror the dashboard's query params).
    val statusFilter: String? = null,
    val severityFilter: String? = null,
    val query: String = "",
    // Per-incident in-flight action ids (disable buttons while acting).
    val acting: Set<Int> = emptySet(),
) {
    val triggeredCount: Int get() = incidents.count { it.status == "triggered" }
    val acknowledgedCount: Int get() = incidents.count { it.status == "acknowledged" }
    val openCount: Int get() = triggeredCount + acknowledgedCount
    val totalCount: Int get() = incidents.size

    val severities: List<String>
        get() = incidents.mapNotNull { it.severity.ifBlank { null } }.distinct().sorted()

    /** Incidents after applying the active status/severity/query filters. */
    val filtered: List<Incident>
        get() = incidents.filter { inc ->
            (statusFilter == null || inc.status == statusFilter) &&
                (severityFilter == null || inc.severity == severityFilter) &&
                (query.isBlank() || inc.title.contains(query, ignoreCase = true))
        }
}

class PgDutyViewModel(private val repo: PgDutyRepository) : ViewModel() {

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var autoRefreshJob: Job? = null

    init {
        refresh(initial = true)
        startAutoRefresh()
    }

    private fun startAutoRefresh() {
        autoRefreshJob?.cancel()
        autoRefreshJob = viewModelScope.launch {
            while (true) {
                delay(15_000)
                refresh(initial = false, silent = true)
            }
        }
    }

    fun refresh(initial: Boolean = false, silent: Boolean = false) {
        viewModelScope.launch {
            _state.update {
                it.copy(loading = initial, refreshing = !initial && !silent)
            }
            try {
                val incidents = repo.incidents()
                val oncall = repo.oncall()
                val health = runCatching { repo.health() }.getOrNull()
                _state.update {
                    it.copy(
                        incidents = incidents,
                        oncall = oncall,
                        loading = false,
                        refreshing = false,
                        error = null,
                        connected = true,
                        version = health?.version ?: it.version,
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        loading = false,
                        refreshing = false,
                        connected = false,
                        error = e.friendlyMessage(),
                    )
                }
            }
        }
    }

    // --- filters ---
    fun setStatusFilter(status: String?) = _state.update { it.copy(statusFilter = status) }
    fun setSeverityFilter(sev: String?) = _state.update { it.copy(severityFilter = sev) }
    fun setQuery(q: String) = _state.update { it.copy(query = q) }
    fun clearFilters() = _state.update {
        it.copy(statusFilter = null, severityFilter = null, query = "")
    }

    // --- actions ---
    private fun act(id: Int, block: suspend () -> Incident) {
        viewModelScope.launch {
            _state.update { it.copy(acting = it.acting + id) }
            try {
                val updated = block()
                _state.update { st ->
                    st.copy(
                        incidents = st.incidents.map { if (it.id == id) updated else it },
                        acting = st.acting - id,
                        error = null,
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(acting = it.acting - id, error = e.friendlyMessage()) }
            }
        }
    }

    fun ack(id: Int) = act(id) { repo.ack(id) }
    fun resolve(id: Int) = act(id) { repo.resolve(id) }
    fun snooze(id: Int, minutes: Int) = act(id) { repo.snooze(id, minutes) }
    fun unsnooze(id: Int) = act(id) { repo.unsnooze(id) }

    fun dismissError() = _state.update { it.copy(error = null) }

    /** Created-vs-resolved counts per local day, most recent first. */
    fun dailyStats(days: Int): List<DailyStat> {
        val created = HashMap<LocalDate, Int>()
        val resolved = HashMap<LocalDate, Int>()
        for (inc in _state.value.incidents) {
            TimeFormat.localDate(inc.createdAt)?.let { created[it] = (created[it] ?: 0) + 1 }
            TimeFormat.localDate(inc.resolvedAt)?.let { resolved[it] = (resolved[it] ?: 0) + 1 }
        }
        val today = LocalDate.now()
        return (0 until days).map { i ->
            val d = today.minusDays(i.toLong())
            DailyStat(
                date = d,
                label = d.format(java.time.format.DateTimeFormatter.ofPattern("EEE dd MMM")),
                created = created[d] ?: 0,
                resolved = resolved[d] ?: 0,
            )
        }
    }

    class Factory(private val repo: PgDutyRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            PgDutyViewModel(repo) as T
    }
}

private fun Exception.friendlyMessage(): String = when (this) {
    is java.net.UnknownHostException -> "Can't reach server — check the base URL in Settings."
    is java.net.ConnectException -> "Connection refused — is pgduty running?"
    is java.net.SocketTimeoutException -> "Server timed out."
    else -> message ?: this::class.java.simpleName
}
