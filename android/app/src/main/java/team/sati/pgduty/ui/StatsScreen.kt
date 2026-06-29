package team.sati.pgduty.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import team.sati.pgduty.ui.theme.Bg
import team.sati.pgduty.ui.theme.ResolvedFg
import team.sati.pgduty.ui.theme.Surface
import team.sati.pgduty.ui.theme.TextMuted
import team.sati.pgduty.ui.theme.TextPrimary
import team.sati.pgduty.ui.theme.TriggeredFg

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun StatsScreen(vm: PgDutyViewModel, onBack: () -> Unit) {
    // Recompute when incidents change so the chart stays live.
    val state by vm.state.collectAsStateWithLifecycle()
    var days by remember { mutableIntStateOf(7) }
    val daily = remember(days, state.incidents) { vm.dailyStats(days) }
    val totalNew = daily.sumOf { it.created }
    val totalResolved = daily.sumOf { it.resolved }
    val maxCreated = (daily.maxOfOrNull { it.created } ?: 0).coerceAtLeast(1)

    Scaffold(
        containerColor = Bg,
        topBar = {
            TopAppBar(
                title = { Text("Stats", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface,
                    titleContentColor = TextPrimary,
                    navigationIconContentColor = TextPrimary,
                ),
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(7, 14, 30, 90).forEach { r ->
                        FilterChip(
                            selected = days == r,
                            onClick = { days = r },
                            label = { Text("${r}d", fontSize = 12.sp) },
                        )
                    }
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("$totalNew", color = TextPrimary, fontWeight = FontWeight.Bold)
                    Text("new ·", color = TextMuted)
                    Text("$totalResolved", color = TextPrimary, fontWeight = FontWeight.Bold)
                    Text("resolved over last $days days", color = TextMuted)
                }
            }
            items(daily.size) { i ->
                val d = daily[i]
                DayBar(d.label, d.created, d.resolved, maxCreated)
            }
        }
    }
}

@Composable
private fun DayBar(label: String, created: Int, resolved: Int, maxCreated: Int) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = TextMuted, fontSize = 12.sp, modifier = Modifier.width(96.dp))
        Box(
            Modifier
                .weight(1f)
                .height(12.dp)
                .background(Surface, RoundedCornerShape(3.dp)),
        ) {
            val frac = created.toFloat() / maxCreated
            Box(
                Modifier
                    .fillMaxWidth(frac)
                    .height(12.dp)
                    .background(TriggeredFg, RoundedCornerShape(3.dp)),
            )
        }
        Text(
            buildString {
                append("  $created new")
                if (resolved > 0) append(" · $resolved resolved")
            },
            color = if (resolved > 0) ResolvedFg else TextPrimary,
            fontSize = 12.sp,
        )
    }
}
