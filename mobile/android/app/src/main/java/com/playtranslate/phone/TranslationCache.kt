package com.playtranslate.phone

import org.json.JSONObject
import java.io.File

/** English -> Arabic lines already translated, kept on disk. Thread-safe. */
class TranslationCache(private val file: File) {
    private val map = HashMap<String, String>()
    private var dirty = false
    private var lastSave = System.currentTimeMillis()

    init {
        try {
            if (file.exists()) {
                val obj = JSONObject(file.readText())
                for (k in obj.keys()) map[k] = obj.optString(k)
            }
        } catch (_: Exception) {
        }
    }

    @get:Synchronized val size: Int get() = map.size

    @Synchronized fun get(key: String): String? = map[key]

    fun set(key: String, value: String) {
        val due: Boolean
        synchronized(this) {
            if (map.size >= 30_000) map.clear()
            map[key] = value
            dirty = true
            due = System.currentTimeMillis() - lastSave > 15_000
        }
        if (due) save()
    }

    /** Adds entries without overwriting what the player already has. */
    @Synchronized fun seed(entries: Map<String, String>) {
        for ((k, v) in entries) if (v.isNotEmpty()) map.putIfAbsent(k, v)
    }

    fun clear() {
        synchronized(this) { map.clear(); dirty = true }
        save()
    }

    fun save() {
        val snapshot: Map<String, String>
        synchronized(this) {
            if (!dirty) return
            snapshot = HashMap(map)
            dirty = false
            lastSave = System.currentTimeMillis()
        }
        try {
            val tmp = File(file.path + ".tmp")
            tmp.writeText(JSONObject(snapshot as Map<*, *>).toString())
            tmp.renameTo(file)
        } catch (_: Exception) {
        }
    }
}
