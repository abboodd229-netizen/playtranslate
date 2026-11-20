package com.playtranslate.phone

/**
 * Per-game terms that must always translate the same way (same idea as the laptop's
 * glossary.py). Terms are wrapped in <x id="n">…</x>, which DeepL leaves alone, and
 * the tag is then replaced by the Arabic term.
 */
class Glossary(input: Map<String, String>) {
    val terms: Map<String, String>
    private val lookup: Map<String, String>
    private val regex: Regex?

    init {
        val clean = LinkedHashMap<String, String>()
        for ((k, v) in input) {
            val key = k.trim()
            val value = v.trim()
            if (key.isNotEmpty() && value.isNotEmpty()) clean[key] = value
        }
        terms = clean
        // Longest first so "Leonida Keys" wins over "Leonida".
        val ordered = clean.keys.sortedWith(compareByDescending<String> { it.length }.thenBy { it })
        val lk = LinkedHashMap<String, String>()
        for (k in ordered) lk.putIfAbsent(k.lowercase(), clean.getValue(k))
        lookup = lk
        regex = if (ordered.isEmpty()) null else
            Regex("(?<![\\w])(" + ordered.joinToString("|") { Regex.escape(it) } + ")(?![\\w])", RegexOption.IGNORE_CASE)
    }

    fun isEmpty() = terms.isEmpty()

    /** Text to send (XML-escaped, terms tagged) and the Arabic replacements in order. */
    fun protect(text: String): Pair<String, List<String>> {
        val re = regex ?: return escape(text) to emptyList()
        val out = StringBuilder()
        val replacements = mutableListOf<String>()
        var last = 0
        for (m in re.findAll(text)) {
            val g = m.groups[1] ?: continue
            out.append(escape(text.substring(last, g.range.first)))
            replacements.add(lookup[g.value.lowercase()] ?: g.value)
            out.append("<x id=\"${replacements.size - 1}\">${escape(g.value)}</x>")
            last = g.range.last + 1
        }
        out.append(escape(text.substring(last)))
        return out.toString() to replacements
    }

    fun translateSpeaker(name: String): String = lookup[name.trim().lowercase()] ?: name

    companion object {
        private val tagRe = Regex("""<x id="(\d+)">(.*?)</x>""", RegexOption.DOT_MATCHES_ALL)
        private val strayTagRe = Regex("""</?x[^>]*>""")

        fun restore(text: String, replacements: List<String>): String {
            var result = tagRe.replace(text) { m ->
                val idx = m.groupValues[1].toIntOrNull() ?: -1
                if (idx in replacements.indices) replacements[idx] else unescape(m.groupValues[2])
            }
            result = strayTagRe.replace(result, "")
            return unescape(result)
        }

        /** "English = عربي" per line; lines starting with # are comments. */
        fun parse(userText: String): Map<String, String> {
            val out = LinkedHashMap<String, String>()
            for (line in userText.lines()) {
                val s = line.trim()
                if (s.isEmpty() || s.startsWith("#")) continue
                val eq = s.indexOf('=')
                if (eq <= 0) continue
                val k = s.substring(0, eq).trim()
                val v = s.substring(eq + 1).trim()
                if (k.isNotEmpty() && v.isNotEmpty()) out[k] = v
            }
            return out
        }

        fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        fun unescape(s: String) = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"")
            .replace("&#39;", "'").replace("&#x27;", "'").replace("&apos;", "'").replace("&amp;", "&")
    }
}
