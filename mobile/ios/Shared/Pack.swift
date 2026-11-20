import Foundation

/// A game pack from the repo's packs/ folder (same file the laptop imports).
struct Pack {
    var glossary: [String: String] = [:]
    var translations: [String: String] = [:]

    static func load(named name: String?, bundle: Bundle = .main) -> Pack {
        guard let name, let url = bundle.url(forResource: name, withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return Pack() }
        return Pack(glossary: obj["glossary"] as? [String: String] ?? [:],
                    translations: obj["translations"] as? [String: String] ?? [:])
    }
}
