package team.sati.pgduty.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val PgDutyColors = darkColorScheme(
    primary = TriggeredFg,
    onPrimary = Bg,
    background = Bg,
    onBackground = TextPrimary,
    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceElevated,
    onSurfaceVariant = TextMuted,
    outline = SurfaceBorder,
    error = TriggeredFg,
)

@Composable
fun PgDutyTheme(
    // The dashboard is dark-only; keep that identity regardless of system setting.
    @Suppress("UNUSED_PARAMETER") darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = PgDutyColors,
        typography = Typography(),
        content = content,
    )
}
