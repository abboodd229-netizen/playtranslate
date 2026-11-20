package com.playtranslate.phone

import android.content.Context
import android.graphics.RectF
import org.json.JSONObject

/** A game preset: where its subtitles are (inside the 16:9 picture, 0..1) and its pack. */
data class GameProfile(val id: String, val name: String, val region: RectF, val pack: String?) {
    companion object {
        // Same as the laptop preset: bottom centre, leaves out the minimap.
        val GTA_VI = GameProfile("gta-vi", "GTA VI", RectF(0.17f, 0.77f, 0.83f, 0.96f), "gta-vi")
        val GENERAL = GameProfile("general", "ألعاب أخرى", RectF(0.10f, 0.68f, 0.90f, 0.97f), null)
        val ALL = listOf(GTA_VI, GENERAL)
        fun byId(id: String?) = ALL.firstOrNull { it.id == id } ?: GTA_VI
    }
}

data class Settings(
    var deeplKey: String = "",
    var profileId: String = GameProfile.GTA_VI.id,
    var customRegion: Boolean = false,
    var region: RectF = RectF(GameProfile.GTA_VI.region),
    var fontSize: Int = 44,
    var userGlossary: String = "",
) {
    val profile get() = GameProfile.byId(profileId)
    val effectiveRegion: RectF get() = if (customRegion) region else profile.region

    fun save(ctx: Context) {
        normalize()
        prefs(ctx).edit()
            .putString("deepl_key", deeplKey).putString("profile", profileId)
            .putBoolean("custom_region", customRegion)
            .putFloat("rl", region.left).putFloat("rt", region.top)
            .putFloat("rr", region.right).putFloat("rb", region.bottom)
            .putInt("font_size", fontSize).putString("user_glossary", userGlossary)
            .apply()
    }

    fun normalize() {
        deeplKey = deeplKey.trim()
        fontSize = fontSize.coerceIn(16, 120)
        val l = region.left.coerceIn(0f, 0.95f)
        val t = region.top.coerceIn(0f, 0.97f)
        region = RectF(l, t, region.right.coerceIn(l + 0.05f, 1f), region.bottom.coerceIn(t + 0.03f, 1f))
    }

    /** Style message for the TV app (same fields and defaults as the laptop). */
    fun tvStyle(): JSONObject = JSONObject()
        .put("font_family", "Noto Naskh Arabic").put("font_size", fontSize)
        .put("text_color", "#FFFFFF").put("speaker_color", "#FFD54F")
        .put("background_color", "#000000").put("background_opacity", 0.55)
        .put("outline", true).put("bottom_margin", 0.17).put("max_width", 0.8)

    companion object {
        private fun prefs(ctx: Context) = ctx.getSharedPreferences("settings", Context.MODE_PRIVATE)

        fun load(ctx: Context): Settings {
            val p = prefs(ctx)
            val s = Settings()
            s.deeplKey = p.getString("deepl_key", "") ?: ""
            s.profileId = p.getString("profile", s.profileId) ?: s.profileId
            s.customRegion = p.getBoolean("custom_region", false)
            s.region = if (p.contains("rl")) RectF(p.getFloat("rl", 0f), p.getFloat("rt", 0f), p.getFloat("rr", 1f), p.getFloat("rb", 1f))
            else RectF(s.profile.region)
            s.fontSize = p.getInt("font_size", 44)
            s.userGlossary = p.getString("user_glossary", "") ?: ""
            s.normalize()
            return s
        }
    }
}

/** Live state shared between the capture service and the screen. */
object Status {
    @Volatile var running = false
    @Volatile var tvCount = 0
    @Volatile var lastEnglish = ""
    @Volatile var lastArabic = ""
    @Volatile var lastError = ""
    @Volatile var msPerRead = 0
}
