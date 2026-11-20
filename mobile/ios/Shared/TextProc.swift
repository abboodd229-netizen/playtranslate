import Foundation

/// One line of text found by OCR. `top`/`left` are 0...1 inside the read area, top-left origin.
struct OcrLine {
    var text: String
    var confidence: Float = 1
    var top: Double = 0
    var left: Double = 0
}

struct Segment: Equatable {
    var text: String
    var speaker: String = ""
}

/// Turns raw OCR lines into clean subtitle segments. Same rules as the laptop
/// version (playtranslate/textproc.py) so both translate the same way.
enum TextProc {
    private static func re(_ pattern: String, _ options: NSRegularExpression.Options = []) -> NSRegularExpression {
        // The patterns are constants; a typo here is a programming error caught by the unit tests.
        try! NSRegularExpression(pattern: pattern, options: options)
    }

    // "ARTHUR: text", "Arthur Morgan: text", "Dr. Kim: text"
    private static let speakerRE = re(#"^\s*([A-Z][A-Za-z0-9.'\- ]{0,28}?)\s*[:：]\s+(\S.*)$"#)
    private static let dashRE = re(#"^\s*[-–—]\s*"#)
    private static let spacesRE = re(#"\s+"#)
    private static let replacements: [(NSRegularExpression, String)] = [
        (re("[‘’`´]"), "'"),
        (re("[“”]"), "\""),
        (re("…"), "..."),
        // A lone "|" or "l" before a space or 'm/'ll/'ve/'d is almost always the pronoun I.
        (re(#"(?<![A-Za-z])[|l](?=\s|'m|'ll|'ve|'d\b)"#), "I"),
        (re(#"\s+([,.!?;:])"#), "$1"),
        // "0" inside a word is "O" ("C0ME" -> "COME").
        (re(#"(?<=[A-Za-z])0(?=[A-Za-z])"#), "O"),
    ]

    static func replace(_ regex: NSRegularExpression, in text: String, with template: String) -> String {
        regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text), withTemplate: template)
    }

    static func cleanLine(_ raw: String) -> String {
        var text = raw.precomposedStringWithCompatibilityMapping
        var scalars = String.UnicodeScalarView()
        for scalar in text.unicodeScalars
        where !CharacterSet.controlCharacters.contains(scalar) && !CharacterSet.illegalCharacters.contains(scalar) {
            scalars.append(scalar)
        }
        text = String(scalars)
        for (regex, template) in replacements {
            text = replace(regex, in: text, with: template)
        }
        return replace(spacesRE, in: text, with: " ").trimmingCharacters(in: .whitespaces)
    }

    static func isJunk(_ text: String) -> Bool {
        let letters = text.filter { $0.isLetter }.count
        if letters < 2 { return true }
        let visible = text.filter { !$0.isWhitespace }.count
        return Double(letters) / Double(max(1, visible)) < 0.5
    }

    /// Joins wrapped lines into sentences; a speaker name or a dash starts a new segment.
    static func toSegments(_ lines: [OcrLine], splitSpeaker: Bool = true) -> [Segment] {
        var segments: [Segment] = []
        for raw in lines {
            var text = cleanLine(raw.text)
            if text.isEmpty || isJunk(text) { continue }
            var startsNew = false
            var speaker = ""
            let full = NSRange(text.startIndex..., in: text)
            if dashRE.firstMatch(in: text, range: full) != nil {
                text = replace(dashRE, in: text, with: "")
                startsNew = true
            }
            if splitSpeaker {
                let range = NSRange(text.startIndex..., in: text)
                if let m = speakerRE.firstMatch(in: text, range: range),
                   let nameRange = Range(m.range(at: 1), in: text),
                   let bodyRange = Range(m.range(at: 2), in: text) {
                    let name = text[nameRange].trimmingCharacters(in: .whitespaces)
                    if name.split(separator: " ").count <= 3 {
                        speaker = name
                        text = text[bodyRange].trimmingCharacters(in: .whitespaces)
                        startsNew = true
                    }
                }
            }
            if !segments.isEmpty && !startsNew {
                segments[segments.count - 1].text += " " + text
            } else {
                segments.append(Segment(text: text, speaker: speaker))
            }
        }
        return segments
    }

    /// One segment per line for a whole-screen read; keeps the `limit` longest lines in screen order.
    static func pageSegments(_ lines: [OcrLine], limit: Int = 16) -> [Segment] {
        var seen = Set<String>()
        var picked: [(Int, String)] = []
        for (i, raw) in lines.enumerated() {
            let text = cleanLine(raw.text)
            let key = text.lowercased()
            if text.isEmpty || isJunk(text) || seen.contains(key) { continue }
            seen.insert(key)
            picked.append((i, text))
        }
        if picked.count > limit {
            let keep = Set(picked.sorted { $0.1.count > $1.1.count }.prefix(limit).map { $0.0 })
            picked = picked.filter { keep.contains($0.0) }
        }
        return picked.map { Segment(text: $0.1) }
    }

    /// Stable key so OCR noise in case/spacing/quotes hits the same cache entry.
    static func cacheKey(_ text: String) -> String {
        var key = cleanLine(text).lowercased()
        while let last = key.last, last == " " || last == "." { key.removeLast() }
        return key
    }

    /// True when two strings are nearly the same (edit-distance ratio).
    static func similar(_ a: String, _ b: String, threshold: Double = 0.9) -> Bool {
        if a.isEmpty || b.isEmpty { return false }
        if a == b { return true }
        let x = Array(a.lowercased()), y = Array(b.lowercased())
        let longest = max(x.count, y.count)
        // Cheap reject: a big length gap can never reach the threshold.
        if Double(abs(x.count - y.count)) / Double(longest) > 1 - threshold { return false }
        var prev = Array(0...y.count)
        var cur = [Int](repeating: 0, count: y.count + 1)
        for i in 1...x.count {
            cur[0] = i
            for j in 1...y.count {
                cur[j] = x[i - 1] == y[j - 1] ? prev[j - 1] : 1 + min(prev[j - 1], prev[j], cur[j - 1])
            }
            swap(&prev, &cur)
        }
        return 1 - Double(prev[y.count]) / Double(longest) >= threshold
    }

    static func joined(_ segments: [Segment]) -> String {
        segments.map { $0.speaker.isEmpty ? $0.text : "\($0.speaker): \($0.text)" }.joined(separator: "\n")
    }
}
