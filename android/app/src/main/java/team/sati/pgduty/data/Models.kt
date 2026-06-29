package team.sati.pgduty.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * One incident, mirroring pgduty's `_incident_dict` JSON shape
 * (see app/main.py). Timestamps arrive as naive-UTC ISO-8601 strings.
 */
@Serializable
data class Incident(
    val id: Int,
    val title: String,
    val description: String = "",
    val severity: String = "default",
    val status: String = "triggered",
    @SerialName("policy_id") val policyId: String = "",
    @SerialName("current_step") val currentStep: Int = 0,
    // Label values can be strings/numbers/etc., so keep them as raw JSON.
    val labels: Map<String, JsonElement> = emptyMap(),
    @SerialName("source_url") val sourceUrl: String = "",
    @SerialName("acked_by") val ackedBy: String? = null,
    @SerialName("next_escalation_at") val nextEscalationAt: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("acked_at") val ackedAt: String? = null,
    @SerialName("resolved_at") val resolvedAt: String? = null,
    @SerialName("resolved_by") val resolvedBy: String? = null,
    @SerialName("muted_until") val mutedUntil: String? = null,
) {
    val isOpen: Boolean get() = status != "resolved"
}

/** A single schedule's current on-call holder, from GET /oncall. */
@Serializable
data class OnCall(
    val schedule: String,
    @SerialName("user_id") val userId: String,
    @SerialName("user_name") val userName: String,
)

/** GET /healthz response. */
@Serializable
data class Health(
    val ok: Boolean = false,
    val version: String = "",
)
