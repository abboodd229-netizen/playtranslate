package com.playtranslate.phone

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

class TranslateError(message: String) : Exception(message)

/** DeepL API (Free keys end in ":fx" and get 500,000 characters a month). Blocking calls. */
class DeepL(rawKey: String) {
    private val key = rawKey.trim()
    private val base: String
    private val client: OkHttpClient

    init {
        if (key.isEmpty()) throw TranslateError("أدخل مفتاح DeepL في تطبيق PlayTranslate")
        base = if (key.endsWith(":fx")) "https://api-free.deepl.com" else "https://api.deepl.com"
        // One client keeps the TLS connection open between lines.
        client = OkHttpClient.Builder()
            .connectTimeout(6, TimeUnit.SECONDS)
            .readTimeout(6, TimeUnit.SECONDS)
            .build()
    }

    private fun request(path: String) = Request.Builder()
        .url(base + path)
        .header("Authorization", "DeepL-Auth-Key $key")
        .header("User-Agent", "PlayTranslate-Android/0.1")

    fun translate(texts: List<String>, context: String = ""): List<String> {
        if (texts.isEmpty()) return emptyList()
        val payload = JSONObject()
            .put("text", JSONArray(texts))
            .put("source_lang", "EN").put("target_lang", "AR")
            .put("tag_handling", "xml").put("ignore_tags", JSONArray(listOf("x")))
            .put("preserve_formatting", true)
        // Context is not billed and helps with pronouns and short lines.
        if (context.isNotEmpty()) payload.put("context", Glossary.escape(context))
        val body = payload.toString().toRequestBody("application/json".toMediaType())
        var lastError = "تعذّر الاتصال بـ DeepL"
        for (attempt in 0 until 3) {
            try {
                client.newCall(request("/v2/translate").post(body).build()).execute().use { resp ->
                    when (resp.code) {
                        200 -> {
                            val items = JSONObject(resp.body!!.string()).getJSONArray("translations")
                            val out = (0 until items.length()).map { items.getJSONObject(it).optString("text") }
                            if (out.size != texts.size) throw TranslateError("ردّ غير متوقع من DeepL")
                            return out
                        }
                        403 -> throw TranslateError("مفتاح DeepL غير صحيح")
                        456 -> throw TranslateError("انتهى رصيد DeepL المجاني لهذا الشهر")
                        429, 500, 502, 503, 504 -> {
                            lastError = "DeepL مشغول (${resp.code})"
                            Thread.sleep(500L * (attempt + 1))
                        }
                        else -> throw TranslateError("خطأ من DeepL (${resp.code})")
                    }
                }
            } catch (e: IOException) {
                lastError = "تعذّر الاتصال بـ DeepL (${e.message})"
                Thread.sleep(300L * (attempt + 1))
            }
        }
        throw TranslateError(lastError)
    }

    /** (characters used, monthly limit). */
    fun usage(): Pair<Long, Long> {
        try {
            client.newCall(request("/v2/usage").get().build()).execute().use { resp ->
                if (resp.code == 403) throw TranslateError("مفتاح DeepL غير صحيح")
                if (resp.code != 200) throw TranslateError("خطأ من DeepL (${resp.code})")
                val obj = JSONObject(resp.body!!.string())
                return obj.optLong("character_count") to obj.optLong("character_limit")
            }
        } catch (e: IOException) {
            throw TranslateError("تعذّر الاتصال بـ DeepL (${e.message})")
        }
    }
}
