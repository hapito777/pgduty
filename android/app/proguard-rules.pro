# kotlinx.serialization keeps generated serializers; keep them when minifying.
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class * {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class team.sati.pgduty.**$$serializer { *; }
