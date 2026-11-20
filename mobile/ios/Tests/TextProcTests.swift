import XCTest
@testable import PlayTranslate

final class TextProcTests: XCTestCase {
    func testCleanLine() {
        XCTAssertEqual(TextProc.cleanLine("  Hello ,  world …"), "Hello, world...")
        XCTAssertEqual(TextProc.cleanLine("C0ME here"), "COME here")
        XCTAssertEqual(TextProc.cleanLine("| don't know"), "I don't know")
        XCTAssertEqual(TextProc.cleanLine("“Hi”"), "\"Hi\"")
    }

    func testSegmentsJoinWrappedLines() {
        let segs = TextProc.toSegments([OcrLine(text: "We need to get out"), OcrLine(text: "of here, now.")])
        XCTAssertEqual(segs, [Segment(text: "We need to get out of here, now.")])
    }

    func testSegmentsSplitSpeakerAndDash() {
        let segs = TextProc.toSegments([OcrLine(text: "LUCIA: Drive."), OcrLine(text: "- Okay."), OcrLine(text: "- Go!")])
        XCTAssertEqual(segs, [Segment(text: "Drive.", speaker: "LUCIA"), Segment(text: "Okay."), Segment(text: "Go!")])
    }

    func testJunkDropped() {
        XCTAssertTrue(TextProc.toSegments([OcrLine(text: "12:30"), OcrLine(text: "$ 500")]).isEmpty)
    }

    func testSimilar() {
        XCTAssertTrue(TextProc.similar("Get in the car now.", "Get in the car now"))
        XCTAssertFalse(TextProc.similar("Get in the car.", "Where are you going?"))
        XCTAssertFalse(TextProc.similar("", "x"))
    }

    func testCacheKey() {
        XCTAssertEqual(TextProc.cacheKey("Hello there. "), "hello there")
    }

    func testPageSegmentsLimit() {
        let lines = (0..<30).map { OcrLine(text: "Menu item number \(String(repeating: "x", count: $0))") }
        XCTAssertEqual(TextProc.pageSegments(lines).count, 16)
    }
}

final class GlossaryTests: XCTestCase {
    func testProtectAndRestore() {
        let g = Glossary(["Vice City": "فايس سيتي", "Lucia": "لوسيا", "Leonida": "ليونيدا", "Leonida Keys": "جزر ليونيدا"])
        let (text, reps) = g.protect("Lucia went to Leonida Keys & Vice City <now>")
        XCTAssertEqual(text, #"<x id="0">Lucia</x> went to <x id="1">Leonida Keys</x> &amp; <x id="2">Vice City</x> &lt;now&gt;"#)
        XCTAssertEqual(reps, ["لوسيا", "جزر ليونيدا", "فايس سيتي"])
        let back = Glossary.restore(#"ذهبت <x id="0">Lucia</x> إلى <x id="1">Leonida Keys</x> &amp; <x id="2">Vice City</x>"#, reps)
        XCTAssertEqual(back, "ذهبت لوسيا إلى جزر ليونيدا & فايس سيتي")
        XCTAssertEqual(g.translateSpeaker("LUCIA"), "لوسيا")
    }

    func testParseUserGlossary() {
        let terms = Glossary.parse(userText: "# comment\nJason = جيسون\nbad line\n Ambrosia=أمبروزيا ")
        XCTAssertEqual(terms, ["Jason": "جيسون", "Ambrosia": "أمبروزيا"])
    }

    func testBundledPackLoads() {
        let pack = Pack.load(named: "gta-vi")
        XCTAssertEqual(pack.glossary["Lucia"], "لوسيا")
    }
}

final class ReaderGeometryTests: XCTestCase {
    func testVideoRectOnWidePhone() {
        // iPhone in landscape: 2556 x 1179, picture is pillar-boxed.
        let r = Reader.videoRect(width: 2556, height: 1179)
        XCTAssertEqual(r.height, 1179, accuracy: 0.5)
        XCTAssertEqual(r.width, 1179 * 16 / 9, accuracy: 0.5)
        XCTAssertEqual(r.midX, 1278, accuracy: 0.5)
    }

    func testVideoRectOnIPad() {
        // iPad in landscape: 2732 x 2048, picture is letter-boxed.
        let r = Reader.videoRect(width: 2732, height: 2048)
        XCTAssertEqual(r.width, 2732, accuracy: 0.5)
        XCTAssertEqual(r.midY, 1024, accuracy: 0.5)
    }

    func testRegionOfInterestBottomStrip() {
        let roi = Reader.regionOfInterest(area: CGRect(x: 0, y: 0.8, width: 1, height: 0.2), width: 1600, height: 900)
        XCTAssertEqual(roi.minY, 0, accuracy: 0.0001)
        XCTAssertEqual(roi.height, 0.2, accuracy: 0.0001)
        XCTAssertEqual(roi.width, 1, accuracy: 0.0001)
    }
}
