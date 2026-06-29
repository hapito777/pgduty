package team.sati.pgduty.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import team.sati.pgduty.data.PgDutyRepository
import team.sati.pgduty.data.SettingsStore
import team.sati.pgduty.notify.MonitorService
import team.sati.pgduty.ui.theme.Bg
import team.sati.pgduty.ui.theme.ResolvedFg
import team.sati.pgduty.ui.theme.Surface
import team.sati.pgduty.ui.theme.SurfaceBorder
import team.sati.pgduty.ui.theme.TextMuted
import team.sati.pgduty.ui.theme.TextPrimary
import team.sati.pgduty.ui.theme.TriggeredFg

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    settingsStore: SettingsStore,
    repo: PgDutyRepository,
    onBack: () -> Unit,
    onSaved: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var baseUrl by remember { mutableStateOf("") }
    var identity by remember { mutableStateOf("") }
    var monitorEnabled by remember { mutableStateOf(false) }
    var pollSeconds by remember { mutableStateOf("30") }
    var loaded by remember { mutableStateOf(false) }

    var testResult by remember { mutableStateOf<String?>(null) }
    var testOk by remember { mutableStateOf(false) }
    var testing by remember { mutableStateOf(false) }

    fun pollInt() = pollSeconds.toIntOrNull()?.coerceIn(10, 600) ?: 30

    // Launcher to request POST_NOTIFICATIONS (Android 13+). On result, turn the
    // monitor on regardless — we still start it, notifications just may be muted.
    val notifLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) {
        scope.launch {
            settingsStore.setMonitor(true, pollInt())
            MonitorService.start(context)
            monitorEnabled = true
        }
    }

    fun enableMonitor() {
        val needsPermission = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        if (needsPermission) {
            notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            scope.launch {
                settingsStore.setMonitor(true, pollInt())
                MonitorService.start(context)
                monitorEnabled = true
            }
        }
    }

    fun disableMonitor() {
        scope.launch {
            settingsStore.setMonitor(false, pollInt())
            MonitorService.stop(context)
            monitorEnabled = false
        }
    }

    LaunchedEffect(Unit) {
        val s = settingsStore.settings.first()
        baseUrl = s.baseUrl
        identity = s.identity
        monitorEnabled = s.monitorEnabled
        pollSeconds = s.pollSeconds.toString()
        loaded = true
    }

    Scaffold(
        containerColor = Bg,
        topBar = {
            TopAppBar(
                title = { Text("Settings", fontWeight = FontWeight.Bold) },
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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "Connect to your pgduty server. From the Android emulator, the host " +
                    "machine is reachable at 10.0.2.2; on a real device use the server's LAN address.",
                color = TextMuted,
                fontSize = 13.sp,
            )

            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it; testResult = null },
                label = { Text("Base URL") },
                placeholder = { Text("http://10.0.2.2:8080") },
                singleLine = true,
                enabled = loaded,
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = identity,
                onValueChange = { identity = it },
                label = { Text("Your name (used when you ack/resolve)") },
                placeholder = { Text("android") },
                singleLine = true,
                enabled = loaded,
                modifier = Modifier.fillMaxWidth(),
            )

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(
                    onClick = {
                        scope.launch {
                            settingsStore.update(baseUrl, identity)
                            onSaved()
                        }
                    },
                    enabled = loaded && baseUrl.isNotBlank(),
                ) { Text("Save") }

                OutlinedButton(
                    onClick = {
                        scope.launch {
                            testing = true
                            testResult = null
                            settingsStore.update(baseUrl, identity)
                            val r = runCatching { repo.health() }
                            testing = false
                            if (r.isSuccess) {
                                testOk = true
                                testResult = "Connected ✓ (pgduty v${r.getOrNull()?.version})"
                            } else {
                                testOk = false
                                testResult = "Failed: ${r.exceptionOrNull()?.message ?: "unreachable"}"
                            }
                        }
                    },
                    enabled = loaded && baseUrl.isNotBlank() && !testing,
                ) { Text(if (testing) "Testing…" else "Test connection") }
            }

            testResult?.let {
                Text(it, color = if (testOk) ResolvedFg else TriggeredFg, fontSize = 13.sp)
            }

            HorizontalDivider(color = SurfaceBorder)

            // --- Background monitoring / push ---
            Text("Real-time alerts", color = TextPrimary, fontWeight = FontWeight.Bold)
            Text(
                "Runs a background service that polls pgduty and posts a notification " +
                    "(with Ack/Resolve) the moment an incident is triggered. No Firebase " +
                    "or server changes needed; it shows an ongoing notification while active.",
                color = TextMuted,
                fontSize = 13.sp,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Monitor in background", color = TextPrimary)
                Switch(
                    checked = monitorEnabled,
                    enabled = loaded,
                    onCheckedChange = { on -> if (on) enableMonitor() else disableMonitor() },
                )
            }

            OutlinedTextField(
                value = pollSeconds,
                onValueChange = { pollSeconds = it.filter(Char::isDigit).take(3) },
                label = { Text("Poll interval (seconds, 10–600)") },
                singleLine = true,
                enabled = loaded,
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                    keyboardType = KeyboardType.Number,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
            if (monitorEnabled) {
                OutlinedButton(
                    onClick = {
                        // Apply a changed interval by restarting the loop.
                        scope.launch {
                            settingsStore.setMonitor(true, pollInt())
                            MonitorService.stop(context)
                            MonitorService.start(context)
                        }
                    },
                    enabled = loaded,
                ) { Text("Apply interval") }
            }
        }
    }
}
