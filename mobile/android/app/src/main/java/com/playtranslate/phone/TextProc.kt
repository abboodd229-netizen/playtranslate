package com.playtranslate.phone

import java.text.Normalizer

/** One line of text found by OCR. top/left are 0..1 inside the read area. */
data class OcrLine(val text: String, val top: Float = 0f, val left: Float = 0f)

data class Segment(var text: String, val speaker: String = "")

/**
 * Turns raw OCR lines into clean subtitle segments. Same rules as the laptop
 * (playtranslate/textproc.py) and the iPhone app, so all three translate alike.
 */
object TextProc {
    // "ARTHUR: text", "Arthur Morgan: text", "Dr. Kim: text"
    private val speakerRe = Regex("""^\s*([A-Z][A-Za-z0-9.'\- ]{0,28}?)\s*[:：]\s+(\S.*)$""")
    private val dashRe = Regex("""^\s*[-–—]\s*""")
    private val spacesRe = Regex("""\s+""")
    private val replacements = listOf(
        Regex("[‘’`´]") to "'",
        Regex("[“”]") to "\"",
        Regex("…") to "...",
        // A lone "|" or "l" before a space or 'm/'ll/'ve/'d is almost always the pronoun I.
        Regex("""(?<![A-Za-z])[|l](?=\s|'m|'ll|'ve|'d\b)""") to "I",
        Regex("""\s+([,.!?;:])""") to "$1",
        // "0" inside a word is "O" ("C0ME" -> "COME").
        Regex("""(?<=[A-Za-z])0(?=[A-Za-z])""") to "O",
    )

    fun cleanLine(raw: String): String {
        var text = Normalizer.normalize(raw, Normalizer.Form.NFKC)
        text = text.filter { !Character.isISOControl(it) && Character.getType(it) != Character.FORMAT.toInt() }
        for ((re, repl) in replacements) text = re.replace(text, repl)
        return spacesRe.replace(text, " ").trim()
    }

    fun isJunk(text: String): Boolean {
        val letters = text.count { it.isLetter() }
        if (letters < 2) return true
        val visible = text.count { !it.isWhitespace() }
        return letters.toDouble() / maxOf(1, visible) < 0.5
    }

    /** Joins wrapped lines into sentences; a speaker name or a dash starts a new segment. */
    fun toSegments(lines: List<OcrLine>, splitSpeaker: Boolean = true): List<Segment> {
        val segments = mutableListOf<Segment>()
        for (raw in lines) {
            var text = cleanLine(raw.text)
            if (text.isEmpty() || isJunk(text)) continue
            var startsNew = false
            var speaker = ""
            if (dashRe.containsMatchIn(text) && dashRe.find(text)!!.range.first == 0) {
                text = dashRe.replaceFirst(text, "")
                startsNew = true
            }
            if (splitSpeaker) {
                val m = speakerRe.find(text)
                if (m != null) {
                    val name = m.groupValues[1].trim()
                    if (name.split(" ").filter { it.isNotEmpty() }.size <= 3) {
                        speaker = name
                        text = m.groupValues[2].trim()
                        startsNew = true
                    }
                }
            }
            if (segments.isNotEmpty() && !startsNew) {
                segments.last().text = segments.last().text + " " + text
            } else {
                segments.add(Segment(text, speaker))
            }
        }
        return segments
    }

    /** One segment per line for a whole-screen read; keeps the [limit] longest lines in screen order. */
    fun pageSegments(lines: List<OcrLine>, limit: Int = 16): List<Segment> {
        val seen = HashSet<String>()
        var picked = mutableListOf<Pair<Int, String>>()
        lines.forEachIndexed { i, raw ->
            val text = cleanLine(raw.text)
            val key = text.lowercase()
            if (text.isEmpty() || isJunk(text) || key in seen) return@forEachIndexed
            seen.add(key)
            picked.add(i to text)
        }
        if (picked.size > limit) {
            val keep = picked.sortedByDescending { it.second.length }.take(limit).map { it.first }.toSet()
            picked = picked.filter { it.first in keep }.toMutableList()
        }
        return picked.map { Segment(it.second) }
    }

    /** Stable key so OCR noise in case/spacing/quotes hits the same cache entry. */
    fun cacheKey(text: String): String = cleanLine(text).lowercase().trimEnd(' ', '.')

    /** True when two strings are nearly the same (edit-distance ratio). */
    fun similar(a: String, b: String, threshold: Double = 0.9): Boolean {
        if (a.isEmpty() || b.isEmpty()) return false
        if (a == b) return true
        val x = a.lowercase()
        val y = b.lowercase()
        val longest = maxOf(x.length, y.length)
        if (Math.abs(x.length - y.length).toDouble() / longest > 1 - threshold) return false
        var prev = IntArray(y.length + 1) { it }
        var cur = IntArray(y.length + 1)
        for (i in 1..x.length) {
            cur[0] = i
            for (j in 1..y.length) {
                cur[j] = if (x[i - 1] == y[j - 1]) prev[j - 1] else 1 + minOf(prev[j - 1], prev[j], cur[j - 1])
            }
            val t = prev; prev = cur; cur = t
        }
        return 1 - prev[y.length].toDouble() / longest >= threshold
    }

    fun joined(segments: List<Segment>): String =
        segments.joinToString("\n") { if (it.speaker.isEmpty()) it.text else "${it.speaker}: ${it.text}" }
}
