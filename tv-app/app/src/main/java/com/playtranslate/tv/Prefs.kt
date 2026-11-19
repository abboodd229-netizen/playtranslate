package com.playtranslate.tv

import android.content.Context

/** Small settings store: manual laptop address and auto-start. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("playtranslate", Context.MODE_PRIVATE)

    /** "192.168.1.20" or "192.168.1.20:8765"; empty = find the laptop automatically. */
    var manualHost: String
        get() = sp.getString("manual_host", "") ?: ""
        set(value) = sp.edit().putString("manual_host", value.trim()).apply()

    var autoStart: Boolean
        get() = sp.getBoolean("auto_start", true)
        set(value) = sp.edit().putBoolean("auto_start", value).apply()

    var lastHost: String
        get() = sp.getString("last_host", "") ?: ""
        set(value) = sp.edit().putString("last_host", value).apply()

    companion object {
        const val DEFAULT_PORT = 8765
        const val DISCOVERY_PORT = 8766
    }
}
