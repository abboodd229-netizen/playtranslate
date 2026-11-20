import Foundation

/// Runs the TV link for a minute from inside the app, so the player can check the TV
/// before starting a game. It also makes iOS ask for local network access, which the
/// screen-reading extension needs and cannot ask for itself.
final class TVTester: ObservableObject {
    @Published private(set) var running = false
    @Published private(set) var tvCount = 0
    private var server: DisplayServer?
    private var beacon: Beacon?
    private var stopWork: DispatchWorkItem?

    func start(settings: Settings) {
        stop()
        let name = "PlayTranslate (iPhone)"
        let server = DisplayServer(name: name, style: settings.tvStyle)
        let beacon = Beacon(name: name)
        server.onClientsChanged = { [weak self] n in
            DispatchQueue.main.async { self?.tvCount = n }
        }
        server.start()
        beacon.start()
        server.show([["speaker": "PlayTranslate", "text": "هذا نص تجربة من الجوال. إذا شفته فوق صورة اللعبة فكل شيء جاهز."]])
        self.server = server
        self.beacon = beacon
        running = true
        let work = DispatchWorkItem { [weak self] in self?.stop() }
        stopWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 60, execute: work)
    }

    func stop() {
        stopWork?.cancel()
        stopWork = nil
        server?.hide()
        beacon?.stop()
        server?.stop()
        server = nil
        beacon = nil
        running = false
        tvCount = 0
    }

    /// One short beacon so the local network permission prompt appears on first launch.
    func askLocalNetworkOnce() {
        let key = "asked_local_network"
        guard !UserDefaults.standard.bool(forKey: key) else { return }
        UserDefaults.standard.set(true, forKey: key)
        let beacon = Beacon(name: "PlayTranslate (iPhone)")
        beacon.start()
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { beacon.stop() }
    }
}
