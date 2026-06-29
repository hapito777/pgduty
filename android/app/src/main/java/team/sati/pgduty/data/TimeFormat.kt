package team.sati.pgduty.data

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import kotlin.math.abs

/**
 * pgduty stores timestamps as naive UTC and serializes them without a zone
 * suffix (e.g. "2026-06-29T10:15:00.123456"). These helpers parse that and
 * render local time, matching the web dashboard's `_fmt_local`.
 */
object TimeFormat {

    private val display = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")

    /** Parse a naive-UTC timestamp string into a UTC [Instant], or null. */
    fun parseUtc(raw: String?): Instant? {
        if (raw.isNullOrBlank()) return null
        return runCatching {
            // Most values are naive (no offset); a few may carry one.
            if (raw.endsWith("Z") || raw.contains('+') || raw.lastIndexOf('-') > 9) {
                runCatching { Instant.parse(raw) }.getOrNull()
                    ?: LocalDateTime.parse(raw).toInstant(ZoneOffset.UTC)
            } else {
                LocalDateTime.parse(raw).toInstant(ZoneOffset.UTC)
            }
        }.getOrNull()
    }

    /** "—" or a local "yyyy-MM-dd HH:mm:ss" string. */
    fun local(raw: String?): String {
        val inst = parseUtc(raw) ?: return "—"
        return display.format(inst.atZone(ZoneId.systemDefault()))
    }

    fun localDate(raw: String?): LocalDate? =
        parseUtc(raw)?.atZone(ZoneId.systemDefault())?.toLocalDate()

    /** Short relative age like "3m", "2h", "5d" for an open incident. */
    fun relativeAge(raw: String?, now: Instant = Instant.now()): String {
        val inst = parseUtc(raw) ?: return ""
        val secs = (now.epochSecond - inst.epochSecond)
        val s = abs(secs)
        return when {
            s < 60 -> "${s}s"
            s < 3600 -> "${s / 60}m"
            s < 86400 -> "${s / 3600}h"
            else -> "${s / 86400}d"
        }
    }

    /** True if [raw] (a muted_until timestamp) is still in the future. */
    fun isFuture(raw: String?, now: Instant = Instant.now()): Boolean {
        val inst = parseUtc(raw) ?: return false
        return inst.isAfter(now)
    }
}
