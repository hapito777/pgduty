package team.sati.pgduty.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bedtime
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.DoneAll
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import team.sati.pgduty.data.Incident
import team.sati.pgduty.data.TimeFormat
import team.sati.pgduty.ui.theme.AckBg
import team.sati.pgduty.ui.theme.AckFg
import team.sati.pgduty.ui.theme.ResolvedBg
import team.sati.pgduty.ui.theme.ResolvedFg
import team.sati.pgduty.ui.theme.Surface
import team.sati.pgduty.ui.theme.SurfaceBorder
import team.sati.pgduty.ui.theme.TextMuted
import team.sati.pgduty.ui.theme.TextPrimary
import team.sati.pgduty.ui.theme.TriggeredBg
import team.sati.pgduty.ui.theme.TriggeredFg

private fun statusColors(status: String): Pair<Color, Color> = when (status) {
    "triggered" -> TriggeredBg to TriggeredFg
    "acknowledged" -> AckBg to AckFg
    "resolved" -> ResolvedBg to ResolvedFg
    else -> SurfaceBorder to TextPrimary
}

@Composable
fun StatusBadge(status: String) {
    val (bg, fg) = statusColors(status)
    Text(
        text = status,
        color = fg,
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier
            .background(bg, RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

@Composable
fun CountPill(text: String, color: Color = TextPrimary) {
    Text(
        text = text,
        color = color,
        fontSize = 12.sp,
        modifier = Modifier
            .background(SurfaceBorder, RoundedCornerShape(999.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

/** A single incident as a card, with severity, timestamps and actions. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun IncidentCard(
    incident: Incident,
    acting: Boolean,
    onAck: () -> Unit,
    onResolve: () -> Unit,
    onSnooze: (Int) -> Unit,
    onUnsnooze: () -> Unit,
) {
    val muted = TimeFormat.isFuture(incident.mutedUntil)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Surface, RoundedCornerShape(10.dp))
            .border(1.dp, SurfaceBorder, RoundedCornerShape(10.dp))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Top,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    "#${incident.id}  ${incident.title}",
                    color = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp,
                )
                if (incident.description.isNotBlank()) {
                    Text(incident.description, color = TextMuted, fontSize = 13.sp)
                }
            }
            StatusBadge(incident.status)
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("sev: ${incident.severity}", color = TextMuted, fontSize = 12.sp)
            if (incident.isOpen) {
                Text("• age ${TimeFormat.relativeAge(incident.createdAt)}", color = TextMuted, fontSize = 12.sp)
            }
            if (muted) {
                Text("• 😴 until ${TimeFormat.local(incident.mutedUntil)}", color = AckFg, fontSize = 12.sp)
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(1.dp)) {
            MetaLine("Started", TimeFormat.local(incident.createdAt))
            if (incident.ackedAt != null) {
                MetaLine("Acked", TimeFormat.local(incident.ackedAt) +
                    (incident.ackedBy?.let { " by $it" } ?: ""))
            }
            if (incident.resolvedAt != null) {
                MetaLine("Resolved", TimeFormat.local(incident.resolvedAt) +
                    " " + resolverLabel(incident.resolvedBy))
            }
        }

        if (incident.isOpen) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (incident.status == "triggered") {
                    ActionButton("Ack", Icons.Default.Check, acting, onAck)
                    if (muted) {
                        ActionButton("Unsnooze", Icons.Default.NotificationsActive, acting, onUnsnooze)
                    } else {
                        ActionButton("😴 1h", Icons.Default.Bedtime, acting) { onSnooze(60) }
                        ActionButton("😴 4h", Icons.Default.Bedtime, acting) { onSnooze(240) }
                    }
                }
                ActionButton("Resolve", Icons.Default.DoneAll, acting, onResolve)
            }
        }
    }
}

@Composable
private fun MetaLine(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("$label:", color = TextMuted, fontSize = 12.sp)
        Text(value, color = TextPrimary, fontSize = 12.sp)
    }
}

@Composable
private fun ActionButton(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    disabled: Boolean,
    onClick: () -> Unit,
) {
    OutlinedButton(onClick = onClick, enabled = !disabled) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(16.dp))
        Spacer(Modifier.size(4.dp))
        Text(label, fontSize = 13.sp)
    }
}

private fun resolverLabel(who: String?): String = when {
    who.isNullOrBlank() -> ""
    who.startsWith("grafana") -> "🤖 auto (Grafana)"
    else -> "by $who"
}
