package team.sati.pgduty.data

import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit binding for the pgduty REST API (see the API table in README.md).
 * The base URL is supplied per-call by [ApiProvider] from user settings.
 */
interface PgDutyApi {

    @GET("healthz")
    suspend fun health(): Health

    @GET("oncall")
    suspend fun oncall(): Map<String, OnCall>

    @GET("incidents")
    suspend fun incidents(
        @Query("status") status: String? = null,
        @Query("limit") limit: Int = 200,
    ): List<Incident>

    @GET("incidents/{id}")
    suspend fun incident(@Path("id") id: Int): Incident

    @POST("incidents/{id}/ack")
    suspend fun ack(
        @Path("id") id: Int,
        @Query("who") who: String,
    ): Incident

    @POST("incidents/{id}/resolve")
    suspend fun resolve(
        @Path("id") id: Int,
        @Query("who") who: String,
    ): Incident

    @POST("incidents/{id}/snooze")
    suspend fun snooze(
        @Path("id") id: Int,
        @Query("minutes") minutes: Int,
        @Query("who") who: String,
    ): Incident

    @POST("incidents/{id}/unsnooze")
    suspend fun unsnooze(
        @Path("id") id: Int,
        @Query("who") who: String,
    ): Incident
}
