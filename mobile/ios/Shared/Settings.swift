import CoreGraphics
import Foundation

/// A game preset: where its subtitles are, plus its bundled glossary pack.
struct GameProfile: Identifiable, Equatable {
    let id: String
    let name: String
    /// Read area inside the 16:9 game picture, top-left origin, 0...1.
    let region: CGRect
    /// Bundled pack file (without .json), from the repo's packs/ folder.
    let pack: String?

    static let gtaVI = GameProfile(id: "gta-vi", name: "GTA VI",
                                   // Same as the laptop preset: bottom centre, leaves out the minimap.
                                   region: CGRect(x: 0.17, y: 0.77, width: 0.66, height: 0.19),
                                   pack: "gta-vi")
    static let general = GameProfile(id: "general", name: "ألعاب أخرى",
                                     region: CGRect(x: 0.10, y: 0.68, width: 0.80, height: 0.29),
                                     pack: nil)
    static let all: [GameProfile] = [gtaVI, general]

    static func byID(_ id: String) -> GameProfile { all.first { $0.id == id } ?? gtaVI }
}

struct Settings: Equatable {
    var deeplKey: String = ""
    var profileID: String = GameProfile.gtaVI.id
    var customRegion: Bool = false
    var region: CGRect = GameProfile.gtaVI.region
    /// Accurate OCR reads better; fast uses less memory and battery.
    var accurateOCR: Bool = true
    /// Text size on the TV, in pixels on a 1080p screen (the TV app scales it).
    var fontSize: Int = 44
    /// Extra terms, "English = عربي" per line.
    var userGlossary: String = ""

    var profile: GameProfile { GameProfile.byID(profileID) }
    var effectiveRegion: CGRect { customRegion ? region : profile.region }

    private enum Key {
        static let deeplKey = "deepl_key", profile = "profile", custom = "custom_region"
        static let rx = "region_x", ry = "region_y", rw = "region_w", rh = "region_h"
        static let accurate = "accurate_ocr", fontSize = "font_size", glossary = "user_glossary"
    }

    static func load(_ d: UserDefaults = AppGroup.defaults) -> Settings {
        var s = Settings()
        s.deeplKey = d.string(forKey: Key.deeplKey) ?? ""
        s.profileID = d.string(forKey: Key.profile) ?? s.profileID
        s.customRegion = d.bool(forKey: Key.custom)
        if d.object(forKey: Key.rx) != nil {
            s.region = CGRect(x: d.double(forKey: Key.rx), y: d.double(forKey: Key.ry),
                              width: d.double(forKey: Key.rw), height: d.double(forKey: Key.rh))
        } else {
            s.region = s.profile.region
        }
        if d.object(forKey: Key.accurate) != nil { s.accurateOCR = d.bool(forKey: Key.accurate) }
        if d.object(forKey: Key.fontSize) != nil { s.fontSize = d.integer(forKey: Key.fontSize) }
        s.userGlossary = d.string(forKey: Key.glossary) ?? ""
        s.normalize()
        return s
    }

    func save(_ d: UserDefaults = AppGroup.defaults) {
        var s = self
        s.normalize()
        d.set(s.deeplKey, forKey: Key.deeplKey)
        d.set(s.profileID, forKey: Key.profile)
        d.set(s.customRegion, forKey: Key.custom)
        d.set(Double(s.region.minX), forKey: Key.rx)
        d.set(Double(s.region.minY), forKey: Key.ry)
        d.set(Double(s.region.width), forKey: Key.rw)
        d.set(Double(s.region.height), forKey: Key.rh)
        d.set(s.accurateOCR, forKey: Key.accurate)
        d.set(s.fontSize, forKey: Key.fontSize)
        d.set(s.userGlossary, forKey: Key.glossary)
    }

    mutating func normalize() {
        deeplKey = deeplKey.trimmingCharacters(in: .whitespacesAndNewlines)
        fontSize = min(120, max(16, fontSize))
        var r = region.standardized
        r.size.width = min(1, max(0.05, r.width))
        r.size.height = min(1, max(0.03, r.height))
        r.origin.x = min(1 - r.width, max(0, r.minX))
        r.origin.y = min(1 - r.height, max(0, r.minY))
        region = r
    }

    /// Style message for the TV app (same fields and defaults as the laptop).
    var tvStyle: [String: Any] { tvStyle(aboveReadArea: false) }

    /// With `aboveReadArea` the Arabic sits just above the area being read instead of over it.
    /// Camera mode needs this: the camera films the TV, so Arabic drawn over the English line
    /// would hide the very text it reads, and the subtitle would flicker on and off.
    func tvStyle(aboveReadArea: Bool) -> [String: Any] {
        ["font_family": "Noto Naskh Arabic", "font_size": fontSize, "text_color": "#FFFFFF",
         "speaker_color": "#FFD54F", "background_color": "#000000", "background_opacity": 0.55,
         "outline": true, "bottom_margin": aboveReadArea ? Settings.marginAbove(effectiveRegion) : 0.17,
         "max_width": 0.8]
    }

    /// Bottom margin (share of the screen height) that puts the TV text above `region`.
    static func marginAbove(_ region: CGRect) -> Double {
        min(0.9, max(0.17, Double(1 - region.minY) + 0.02))
    }
}

/// Live state written by the extension and shown in the app.
struct BroadcastStatus {
    var running = false
    var updated: Date = .distantPast
    var tvCount = 0
    var address = ""
    var lastEnglish = ""
    var lastArabic = ""
    var lastError = ""
    var reads = 0
    var msPerRead = 0

    private static let key = "broadcast_status"

    static func load(_ d: UserDefaults = AppGroup.defaults) -> BroadcastStatus {
        var s = BroadcastStatus()
        guard let m = d.dictionary(forKey: key) else { return s }
        s.running = m["running"] as? Bool ?? false
        s.updated = Date(timeIntervalSince1970: m["updated"] as? Double ?? 0)
        s.tvCount = m["tv"] as? Int ?? 0
        s.address = m["address"] as? String ?? ""
        s.lastEnglish = m["en"] as? String ?? ""
        s.lastArabic = m["ar"] as? String ?? ""
        s.lastError = m["error"] as? String ?? ""
        s.reads = m["reads"] as? Int ?? 0
        s.msPerRead = m["ms"] as? Int ?? 0
        return s
    }

    func save(_ d: UserDefaults = AppGroup.defaults) {
        d.set(["running": running, "updated": updated.timeIntervalSince1970, "tv": tvCount, "address": address,
               "en": lastEnglish, "ar": lastArabic, "error": lastError, "reads": reads, "ms": msPerRead],
              forKey: BroadcastStatus.key)
    }

    /// The extension can be killed without a goodbye; a stale heartbeat means it is not running.
    var isLive: Bool { running && Date().timeIntervalSince(updated) < 6 }
}
