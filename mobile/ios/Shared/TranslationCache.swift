import Foundation

/// English -> Arabic lines already translated, kept on disk so a repeated line
/// costs nothing and shows instantly. Thread-safe.
final class TranslationCache {
    private var map: [String: String] = [:]
    private let url: URL
    private let lock = NSLock()
    private var dirty = false
    private var lastSave = Date()
    private let limit = 30_000

    init(url: URL = AppGroup.dataFolder.appendingPathComponent("translations.json")) {
        self.url = url
        if let data = try? Data(contentsOf: url),
           let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String] {
            map = obj
        }
    }

    var count: Int { lock.lock(); defer { lock.unlock() }; return map.count }

    func get(_ key: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        return map[key]
    }

    func set(_ key: String, _ value: String) {
        lock.lock()
        if map.count >= limit { map.removeAll(keepingCapacity: true) }
        map[key] = value
        dirty = true
        let due = Date().timeIntervalSince(lastSave) > 15
        lock.unlock()
        if due { save() }
    }

    /// Adds entries without overwriting what the player already has.
    func seed(_ entries: [String: String]) {
        lock.lock()
        for (k, v) in entries where map[k] == nil && !v.isEmpty { map[k] = v }
        lock.unlock()
    }

    func clear() {
        lock.lock(); map.removeAll(); dirty = true; lock.unlock()
        save()
    }

    func save() {
        lock.lock()
        guard dirty else { lock.unlock(); return }
        let snapshot = map
        dirty = false
        lastSave = Date()
        lock.unlock()
        if let data = try? JSONSerialization.data(withJSONObject: snapshot) {
            try? data.write(to: url, options: .atomic)
        }
    }
}
