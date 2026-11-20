import CoreMedia
import Foundation

/// Everything that runs while the screen is being shared: TV server, beacon, reader, status.
final class Session {
    let settings: Settings
    let server: DisplayServer
    let beacon: Beacon
    let cache = TranslationCache()
    private(set) var reader: Reader!
    private var status = BroadcastStatus()
    private let statusLock = NSLock()
    private var heartbeat: DispatchSourceTimer?
    var onFatal: ((String) -> Void)?

    init(settings: Settings, name: String = "PlayTranslate (iPhone)") {
        self.settings = settings
        server = DisplayServer(name: name, style: settings.tvStyle)
        beacon = Beacon(name: name)
        reader = Reader(settings: settings, server: server, cache: cache)
        reader.onStatus = { [weak self] en, ar, err, ms in
            guard let self else { return }
            self.statusLock.lock()
            self.status.reads += 1
            self.status.msPerRead = ms
            if let en { self.status.lastEnglish = en }
            if let ar { self.status.lastArabic = ar }
            if let err { self.status.lastError = err }
            self.statusLock.unlock()
        }
        server.onClientsChanged = { [weak self] n in
            guard let self else { return }
            self.statusLock.lock(); self.status.tvCount = n; self.statusLock.unlock()
        }
        server.onTranslatePage = { [weak self] in self?.reader.requestPage() }
        server.onFailure = { [weak self] why in self?.onFatal?(why) }
    }

    func start() {
        status.running = true
        server.start()
        beacon.start()
        let t = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        t.schedule(deadline: .now(), repeating: 1)
        t.setEventHandler { [weak self] in self?.writeStatus() }
        t.resume()
        heartbeat = t
    }

    func handle(_ sample: CMSampleBuffer) {
        reader.submit(sample)
    }

    func stop() {
        heartbeat?.cancel()
        heartbeat = nil
        server.hide()
        beacon.stop()
        server.stop()
        cache.save()
        statusLock.lock(); status.running = false; statusLock.unlock()
        writeStatus()
    }

    private func writeStatus() {
        statusLock.lock()
        status.updated = Date()
        status.address = Net.localIPv4() ?? ""
        let snapshot = status
        statusLock.unlock()
        snapshot.save()
    }
}
