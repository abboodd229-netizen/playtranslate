import Foundation

/// Per-game terms that must always translate the same way (same idea as the laptop's
/// glossary.py). Each term is wrapped in <x id="n">…</x>, which DeepL is told to leave
/// alone, and afterwards the tag is replaced by the Arabic term.
final class Glossary {
    let terms: [String: String]
    private let lookup: [String: String]
    private let regex: NSRegularExpression?
    private static let tagRE = try! NSRegularExpression(pattern: #"<x id="(\d+)">(.*?)</x>"#, options: [.dotMatchesLineSeparators])
    private static let strayTagRE = try! NSRegularExpression(pattern: #"</?x[^>]*>"#)

    init(_ input: [String: String]) {
        var clean: [String: String] = [:]
        for (k, v) in input {
            let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = v.trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty && !value.isEmpty { clean[key] = value }
        }
        terms = clean
        // Longest first so "Leonida Keys" wins over "Leonida".
        let ordered = clean.keys.sorted { $0.count != $1.count ? $0.count > $1.count : $0 < $1 }
        var lk: [String: String] = [:]
        for k in ordered where lk[k.lowercased()] == nil { lk[k.lowercased()] = clean[k] }
        lookup = lk
        if ordered.isEmpty {
            regex = nil
        } else {
            let alternatives = ordered.map { NSRegularExpression.escapedPattern(for: $0) }.joined(separator: "|")
            regex = try? NSRegularExpression(pattern: "(?<![\\w])(\(alternatives))(?![\\w])", options: [.caseInsensitive])
        }
    }

    var isEmpty: Bool { terms.isEmpty }

    /// Text to send (XML-escaped, terms tagged) and the Arabic replacements in order.
    func protect(_ text: String) -> (String, [String]) {
        guard let regex else { return (Glossary.escape(text), []) }
        var out = ""
        var replacements: [String] = []
        var last = text.startIndex
        for m in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
            guard let r = Range(m.range(at: 1), in: text) else { continue }
            out += Glossary.escape(String(text[last..<r.lowerBound]))
            let term = String(text[r])
            replacements.append(lookup[term.lowercased()] ?? term)
            out += "<x id=\"\(replacements.count - 1)\">\(Glossary.escape(term))</x>"
            last = r.upperBound
        }
        out += Glossary.escape(String(text[last...]))
        return (out, replacements)
    }

    static func restore(_ text: String, _ replacements: [String]) -> String {
        var result = text
        let matches = tagRE.matches(in: result, range: NSRange(result.startIndex..., in: result))
        for m in matches.reversed() {
            guard let whole = Range(m.range, in: result),
                  let idRange = Range(m.range(at: 1), in: result),
                  let inner = Range(m.range(at: 2), in: result) else { continue }
            let idx = Int(result[idRange]) ?? -1
            let value = (idx >= 0 && idx < replacements.count) ? replacements[idx] : unescape(String(result[inner]))
            result.replaceSubrange(whole, with: value)
        }
        result = TextProc.replace(strayTagRE, in: result, with: "")
        return unescape(result)
    }

    func translateSpeaker(_ name: String) -> String {
        lookup[name.trimmingCharacters(in: .whitespaces).lowercased()] ?? name
    }

    /// "English = عربي" per line; lines starting with # are comments.
    static func parse(userText: String) -> [String: String] {
        var out: [String: String] = [:]
        for line in userText.split(whereSeparator: \.isNewline) {
            let s = line.trimmingCharacters(in: .whitespaces)
            if s.isEmpty || s.hasPrefix("#") { continue }
            guard let eq = s.firstIndex(of: "=") else { continue }
            let k = s[..<eq].trimmingCharacters(in: .whitespaces)
            let v = s[s.index(after: eq)...].trimmingCharacters(in: .whitespaces)
            if !k.isEmpty && !v.isEmpty { out[k] = v }
        }
        return out
    }

    static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    static func unescape(_ s: String) -> String {
        s.replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "&#x27;", with: "'")
            .replacingOccurrences(of: "&apos;", with: "'")
            .replacingOccurrences(of: "&amp;", with: "&")
    }
}
