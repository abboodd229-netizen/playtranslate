package com.playtranslate.tv

/** Shared, read-only status the activity shows while the service runs. */
object ServiceState {
    @Volatile var running: Boolean = false
    @Volatile var connectedTo: String = ""
    @Volatile var serverName: String = ""
    @Volatile var lastError: String = ""
    @Volatile var overlayOk: Boolean = true
    @Volatile var linesShown: Int = 0

    fun describe(): String = when {
        !running -> "الخدمة متوقفة"
        !overlayOk -> "لا توجد صلاحية العرض فوق التطبيقات"
        connectedTo.isNotEmpty() -> "متصل بـ ${serverName.ifEmpty { connectedTo }} ✓  (جمل معروضة: $linesShown)"
        lastError.isNotEmpty() -> "يبحث عن اللابتوب… ($lastError)"
        else -> "يبحث عن اللابتوب على الشبكة…"
    }
}
