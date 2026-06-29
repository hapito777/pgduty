package team.sati.pgduty

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import team.sati.pgduty.data.PgDutyRepository
import team.sati.pgduty.data.SettingsStore
import team.sati.pgduty.notify.Notifications
import team.sati.pgduty.ui.IncidentsScreen
import team.sati.pgduty.ui.PgDutyViewModel
import team.sati.pgduty.ui.SettingsScreen
import team.sati.pgduty.ui.StatsScreen
import team.sati.pgduty.ui.theme.PgDutyTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        val settingsStore = SettingsStore(applicationContext)
        val repo = PgDutyRepository(settingsStore)
        Notifications.ensureChannels(applicationContext)

        setContent {
            PgDutyTheme {
                val nav = rememberNavController()
                // One ViewModel shared by the incidents + stats screens.
                val vm: PgDutyViewModel = viewModel(factory = PgDutyViewModel.Factory(repo))

                NavHost(navController = nav, startDestination = "incidents") {
                    composable("incidents") {
                        IncidentsScreen(
                            vm = vm,
                            onOpenStats = { nav.navigate("stats") },
                            onOpenSettings = { nav.navigate("settings") },
                        )
                    }
                    composable("stats") {
                        StatsScreen(vm = vm, onBack = { nav.popBackStack() })
                    }
                    composable("settings") {
                        SettingsScreen(
                            settingsStore = remember { settingsStore },
                            repo = remember { repo },
                            onBack = { nav.popBackStack() },
                            onSaved = {
                                vm.refresh()
                                nav.popBackStack()
                            },
                        )
                    }
                }
            }
        }
    }
}
