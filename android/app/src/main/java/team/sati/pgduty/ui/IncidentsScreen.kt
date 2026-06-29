package team.sati.pgduty.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import team.sati.pgduty.data.OnCall
import team.sati.pgduty.ui.theme.AckFg
import team.sati.pgduty.ui.theme.Bg
import team.sati.pgduty.ui.theme.ResolvedFg
import team.sati.pgduty.ui.theme.Surface
import team.sati.pgduty.ui.theme.SurfaceBorder
import team.sati.pgduty.ui.theme.TextMuted
import team.sati.pgduty.ui.theme.TextPrimary
import team.sati.pgduty.ui.theme.TriggeredFg

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun IncidentsScreen(
    vm: PgDutyViewModel,
    onOpenStats: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    Scaffold(
        containerColor = Bg,
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("sati-duty", fontWeight = FontWeight.Bold)
                        Spacer8()
                        ConnectionDot(state.connected)
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                    IconButton(onClick = onOpenStats) {
                        Icon(Icons.Default.BarChart, contentDescription = "Stats")
                    }
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Default.Settings, contentDescription = "Settings")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface,
                    titleContentColor = TextPrimary,
                    actionIconContentColor = TextPrimary,
                ),
            )
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item { CountPills(state) }
                item { OnCallRow(state.oncall) }
                item { FilterBar(state, vm) }

                state.error?.let { err ->
                    item { ErrorBanner(err) }
                }

                val list = state.filtered
                if (state.loading) {
                    item { LoadingRow() }
                } else if (list.isEmpty()) {
                    item { EmptyRow(state.totalCount == 0) }
                } else {
                    items(list, key = { it.id }) { inc ->
                        IncidentCard(
                            incident = inc,
                            acting = inc.id in state.acting,
                            onAck = { vm.ack(inc.id) },
                            onResolve = { vm.resolve(inc.id) },
                            onSnooze = { m -> vm.snooze(inc.id, m) },
                            onUnsnooze = { vm.unsnooze(inc.id) },
                        )
                    }
                    item {
                        Text(
                            "${list.size} shown · ${state.totalCount} total",
                            color = TextMuted,
                            fontSize = 12.sp,
                            modifier = Modifier.fillMaxWidth().padding(8.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ConnectionDot(connected: Boolean) {
    val color = if (connected) ResolvedFg else TriggeredFg
    Text(
        text = if (connected) "● live" else "● offline",
        color = color,
        fontSize = 12.sp,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CountPills(state: UiState) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        CountPill("${state.openCount} open")
        CountPill("${state.triggeredCount} triggered", TriggeredFg)
        CountPill("${state.acknowledgedCount} acknowledged", AckFg)
        CountPill("${state.totalCount} total")
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OnCallRow(oncall: Map<String, OnCall>) {
    if (oncall.isEmpty()) return
    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        oncall.values.forEach { oc ->
            Column(
                modifier = Modifier
                    .background(Surface, RoundedCornerShape(10.dp))
                    .border(1.dp, SurfaceBorder, RoundedCornerShape(10.dp))
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            ) {
                Text(oc.schedule, color = TextMuted, fontSize = 12.sp)
                Row {
                    Text(oc.userName, color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                    Text("  on-call", color = TextMuted, fontSize = 14.sp)
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun FilterBar(state: UiState, vm: PgDutyViewModel) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
            value = state.query,
            onValueChange = vm::setQuery,
            placeholder = { Text("search title…") },
            singleLine = true,
            trailingIcon = {
                if (state.query.isNotBlank()) {
                    IconButton(onClick = { vm.setQuery("") }) {
                        Icon(Icons.Default.Clear, contentDescription = "Clear search")
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("triggered", "acknowledged", "resolved").forEach { s ->
                FilterChip(
                    selected = state.statusFilter == s,
                    onClick = { vm.setStatusFilter(if (state.statusFilter == s) null else s) },
                    label = { Text(s, fontSize = 12.sp) },
                )
            }
            state.severities.forEach { sev ->
                FilterChip(
                    selected = state.severityFilter == sev,
                    onClick = { vm.setSeverityFilter(if (state.severityFilter == sev) null else sev) },
                    label = { Text(sev, fontSize = 12.sp) },
                )
            }
            if (state.statusFilter != null || state.severityFilter != null || state.query.isNotBlank()) {
                FilterChip(
                    selected = false,
                    onClick = { vm.clearFilters() },
                    label = { Text("clear", fontSize = 12.sp) },
                )
            }
        }
    }
}

@Composable
private fun ErrorBanner(message: String) {
    Text(
        text = message,
        color = TriggeredFg,
        fontSize = 13.sp,
        modifier = Modifier
            .fillMaxWidth()
            .background(Surface, RoundedCornerShape(8.dp))
            .border(1.dp, TriggeredFg, RoundedCornerShape(8.dp))
            .padding(12.dp),
    )
}

@Composable
private fun LoadingRow() {
    Row(
        Modifier.fillMaxWidth().padding(40.dp),
        horizontalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator(color = TriggeredFg)
    }
}

@Composable
private fun EmptyRow(noneAtAll: Boolean) {
    Text(
        text = if (noneAtAll) "No incidents yet." else "No incidents match these filters.",
        color = TextMuted,
        modifier = Modifier.fillMaxWidth().padding(40.dp),
    )
}

@Composable
private fun Spacer8() = Box(Modifier.padding(start = 8.dp))
