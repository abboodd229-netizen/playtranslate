package com.playtranslate.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TextProcTest {
    @Test fun cleanLine() {
        assertEquals("Hello, world...", TextProc.cleanLine("  Hello ,  world …"))
        assertEquals("COME here", TextProc.cleanLine("C0ME here"))
        assertEquals("I don't know", TextProc.cleanLine("| don't know"))
        assertEquals("\"Hi\"", TextProc.cleanLine("“Hi”"))
    }

    @Test fun joinsWrappedLines() {
        val segs = TextProc.toSegments(listOf(OcrLine("We need to get out"), OcrLine("of here, now.")))
        assertEquals(listOf(Segment("We need to get out of here, now.")), segs)
    }

    @Test fun splitsSpeakerAndDash() {
        val segs = TextProc.toSegments(listOf(OcrLine("LUCIA: Drive."), OcrLine("- Okay."), OcrLine("- Go!")))
        assertEquals(listOf(Segment("Drive.", "LUCIA"), Segment("Okay."), Segment("Go!")), segs)
    }

    @Test fun dropsJunk() {
        assertTrue(TextProc.toSegments(listOf(OcrLine("12:30"), OcrLine("$ 500"))).isEmpty())
    }

    @Test fun similar() {
        assertTrue(TextProc.similar("Get in the car now.", "Get in the car now"))
        assertFalse(TextProc.similar("Get in the car.", "Where are you going?"))
        assertFalse(TextProc.similar("", "x"))
    }

    @Test fun cacheKey() {
        assertEquals("hello there", TextProc.cacheKey("Hello there. "))
    }

    @Test fun pageLimit() {
        val lines = (0 until 30).map { OcrLine("Menu item number " + "x".repeat(it)) }
        assertEquals(16, TextProc.pageSegments(lines).size)
    }
}

class GlossaryTest {
    @Test fun protectAndRestore() {
        val g = Glossary(mapOf("Vice City" to "فايس سيتي", "Lucia" to "لوسيا", "Leonida" to "ليونيدا", "Leonida Keys" to "جزر ليونيدا"))
        val (text, reps) = g.protect("Lucia went to Leonida Keys & Vice City <now>")
        assertEquals("""<x id="0">Lucia</x> went to <x id="1">Leonida Keys</x> &amp; <x id="2">Vice City</x> &lt;now&gt;""", text)
        assertEquals(listOf("لوسيا", "جزر ليونيدا", "فايس سيتي"), reps)
        val back = Glossary.restore("""ذهبت <x id="0">Lucia</x> إلى <x id="1">Leonida Keys</x> &amp; <x id="2">Vice City</x>""", reps)
        assertEquals("ذهبت لوسيا إلى جزر ليونيدا & فايس سيتي", back)
        assertEquals("لوسيا", g.translateSpeaker("LUCIA"))
    }

    @Test fun parseUserGlossary() {
        val terms = Glossary.parse("# comment\nJason = جيسون\nbad line\n Ambrosia=أمبروزيا ")
        assertEquals(mapOf("Jason" to "جيسون", "Ambrosia" to "أمبروزيا"), terms)
    }
}
