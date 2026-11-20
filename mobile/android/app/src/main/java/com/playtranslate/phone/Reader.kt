package com.playtranslate.phone

import android.content.Context
import android.graphics.Bitmap
import android.graphics.RectF
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import org.json.JSONObject
import java.io.File

/**
 * Reads the English subtitle from screen frames, translates it and sends the Arabic
 * to the TV. Called on one background thread, one frame at a time.
 */
class Reader(ctx: Context, private val settings: Settings, private val server: DisplayServer, val cache: TranslationCache) {
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    private val glossary: Glossary
    private val deepl: DeepL?
    private val deeplError: String

    @Volatile private var pageRequested = false
    private var candidate = ""
    private var shownSource = ""
    private var showing = false
    private var emptyReads = 0
    private var context = ""
    private var pageUntil = 0L
    private var lastErrorShown = "" to 0L

    init {
        val pack = loadPack(ctx, settings.profile.pack)
        val terms = LinkedHashMap(pack.first)
        terms.putAll(Glossary.parse(settings.userGlossary))
        glossary = Glossary(terms)
        cache.seed(pack.second.mapKeys { TextProc.cacheKey(it.key) })
        var d: DeepL? = null
        var err = ""
        try { d = DeepL(settings.deeplKey) } catch (e: TranslateError) { err = e.message ?: "" }
        deepl = d
        deeplError = err
    }

    fun requestPage() { pageRequested = true }

    fun close() { recognizer.close() }

    /** Where the 16:9 game picture sits inside the screen frame (Remote Play letterboxes it). */
    fun videoRect(width: Int, height: Int): RectF {
        val aspect = 16f / 9f
        return if (width.toFloat() / height > aspect) {
            val w = height * aspect
            RectF((width - w) / 2, 0f, (width + w) / 2, height.toFloat())
        } else {
            val h = width / aspect
            RectF(0f, (height - h) / 2, width.toFloat(), (height + h) / 2)
        }
    }

    fun process(frame: Bitmap) {
        val started = System.currentTimeMillis()
        val page = pageRequested.also { pageRequested = false }
        if (!page && pageUntil > 0) {
            if (started < pageUntil) return
            pageUntil = 0
            server.hide()
            showing = false
            shownSource = ""
        }
        val area = if (page) RectF(0f, 0f, 1f, 1f) else settings.effectiveRegion
        val video = videoRect(frame.width, frame.height)
        val left = (video.left + area.left * video.width()).toInt().coerceIn(0, frame.width - 2)
        val top = (video.top + area.top * video.height()).toInt().coerceIn(0, frame.height - 2)
        val right = (video.left + area.right * video.width()).toInt().coerceIn(left + 1, frame.width)
        val bottom = (video.top + area.bottom * video.height()).toInt().coerceIn(top + 1, frame.height)
        val crop = Bitmap.createBitmap(frame, left, top, right - left, bottom - top)
        val lines = try {
            val result = Tasks.await(recognizer.process(InputImage.fromBitmap(crop, 0)))
            val h = crop.height.toFloat().coerceAtLeast(1f)
            val w = crop.width.toFloat().coerceAtLeast(1f)
            result.textBlocks.flatMap { it.lines }.mapNotNull { line ->
                val box = line.boundingBox ?: return@mapNotNull null
                OcrLine(line.text, box.top / h, box.left / w)
            }.sortedWith(compareBy<OcrLine>({ Math.round(it.top / 0.025f) }, { it.left }))
        } catch (e: Exception) {
            report(null, null, "تعذّرت قراءة الشاشة: ${e.message}", started)
            return
        } finally {
            if (crop !== frame) crop.recycle()
        }
        if (page) handlePage(lines, started) else handleSubtitle(lines, started)
    }

    private fun handleSubtitle(lines: List<OcrLine>, started: Long) {
        val segments = TextProc.toSegments(lines)
        val text = TextProc.joined(segments)
        if (text.isEmpty()) {
            emptyReads++
            candidate = ""
            // Two empty reads in a row (~0.6 s): the subtitle is gone.
            if (showing && emptyReads >= 2) {
                server.hide()
                showing = false
                shownSource = ""
            }
            report(null, null, null, started)
            return
        }
        emptyReads = 0
        if (showing && TextProc.similar(text, shownSource)) {
            report(null, null, null, started)
            return
        }
        // Wait until the same text is read twice so a line still fading in is not sent.
        if (!TextProc.similar(text, candidate)) {
            candidate = text
            report(text, null, null, started)
            return
        }
        try {
            val arabic = translate(segments, true)
            server.show(arabic)
            showing = true
            shownSource = text
            context = segments.joinToString(" ") { it.text }
            report(text, arabic.joinToString("\n") { it["text"] ?: "" }, "", started)
        } catch (e: Exception) {
            showError(e, started, text)
        }
    }

    private fun handlePage(lines: List<OcrLine>, started: Long) {
        val segments = TextProc.pageSegments(lines)
        if (segments.isEmpty()) {
            report(null, null, "ما لقيت نص إنجليزي في الشاشة", started)
            return
        }
        try {
            val arabic = translate(segments, false)
            server.show(arabic, "page")
            showing = true
            shownSource = ""
            pageUntil = System.currentTimeMillis() + 12_000
            report(TextProc.joined(segments), arabic.joinToString("\n") { it["text"] ?: "" }, "", started)
        } catch (e: Exception) {
            showError(e, started, TextProc.joined(segments))
        }
    }

    private fun translate(segments: List<Segment>, useContext: Boolean): List<Map<String, String>> {
        val out = segments.map {
            mutableMapOf("speaker" to (if (it.speaker.isEmpty()) "" else glossary.translateSpeaker(it.speaker)), "text" to "")
        }
        val misses = mutableListOf<Int>()
        segments.forEachIndexed { i, seg ->
            val hit = cache.get(TextProc.cacheKey(seg.text))
            if (hit != null) out[i]["text"] = hit else misses.add(i)
        }
        if (misses.isNotEmpty()) {
            val d = deepl ?: throw TranslateError(deeplError)
            val protected = misses.map { glossary.protect(segments[it].text) }
            val results = d.translate(protected.map { it.first }, if (useContext) context else "")
            misses.forEachIndexed { j, i ->
                val arabic = Glossary.restore(results[j], protected[j].second)
                out[i]["text"] = arabic
                cache.set(TextProc.cacheKey(segments[i].text), arabic)
            }
        }
        return out
    }

    /** Shows a translation problem on the TV too (once every 30 s): the player is not looking at the phone. */
    private fun showError(e: Exception, started: Long, english: String) {
        val message = e.message ?: e.toString()
        val now = System.currentTimeMillis()
        if (lastErrorShown.first != message || now - lastErrorShown.second > 30_000) {
            server.show(listOf(mapOf("speaker" to "PlayTranslate", "text" to "⚠ $message")))
            showing = true
            shownSource = ""
            lastErrorShown = message to now
        }
        report(english, null, message, started)
    }

    private fun report(english: String?, arabic: String?, error: String?, started: Long) {
        Status.msPerRead = (System.currentTimeMillis() - started).toInt()
        english?.let { Status.lastEnglish = it }
        arabic?.let { Status.lastArabic = it }
        error?.let { Status.lastError = it }
    }

    companion object {
        /** (glossary, translations) from a bundled pack such as assets/gta-vi.json. */
        fun loadPack(ctx: Context, name: String?): Pair<Map<String, String>, Map<String, String>> {
            if (name == null) return emptyMap<String, String>() to emptyMap()
            return try {
                val obj = JSONObject(ctx.assets.open("$name.json").bufferedReader().readText())
                fun map(key: String): Map<String, String> {
                    val o = obj.optJSONObject(key) ?: return emptyMap()
                    return o.keys().asSequence().associateWith { o.optString(it) }
                }
                map("glossary") to map("translations")
            } catch (_: Exception) {
                emptyMap<String, String>() to emptyMap()
            }
        }

        fun cacheFile(ctx: Context) = File(ctx.filesDir, "translations.json")
    }
}
