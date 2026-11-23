import CoreMedia
import CoreVideo
import UIKit

/// Receives the game picture, from the built-in Remote Play stream (Pylux's video decoder calls
/// `callback`, see scripts/patch-pylux.py) or from camera mode (CameraMode.swift), and runs the
/// translation session:
/// reader, TV server and beacon. The session starts with the first frame of a stream and
/// stops a few seconds after the frames stop, so the player never has to press anything.
final class FrameTap {
    static let shared = FrameTap()

    /// Posted on the main thread when a session starts, so the TV test can free the TV port.
    static let sessionStarted = Notification.Name("PlayTranslateInAppSessionStarted")

    /// Seconds without frames before the session ends (stream closed or app left).
    private let idleTimeout: CFAbsoluteTime = 4

    private let lock = NSLock()
    private var session: Session?
    private var lastFrame: CFAbsoluteTime = 0
    private var watchdog: DispatchSourceTimer?

    private init() {}

    /// The decoder's frame callback. Runs on the decoder thread for every frame.
    var callback: (CVPixelBuffer, CMTime) -> Void {
        { pixels, _ in FrameTap.shared.feed(pixels) }
    }

    var isRunning: Bool {
        lock.lock(); defer { lock.unlock() }
        return session != nil
    }

    /// `camera`: the picture is the TV filmed by the camera (the Arabic must not cover the English).
    func feed(_ pixels: CVPixelBuffer, camera: Bool = false) {
        lock.lock()
        lastFrame = CFAbsoluteTimeGetCurrent()
        let current: Session
        var started = false
        if let s = session {
            current = s
        } else {
            current = Session(settings: Settings.load(), keepReadAreaVisible: camera)
            session = current
            started = true
        }
        lock.unlock()

        if started { begin(current) }
        current.handle(pixels: pixels)
    }

    private func begin(_ s: Session) {
        s.onFatal = { [weak self] _ in self?.stop() }
        s.start()
        let t = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        t.schedule(deadline: .now() + 1, repeating: 1)
        t.setEventHandler { [weak self] in
            guard let self else { return }
            self.lock.lock()
            let idle = CFAbsoluteTimeGetCurrent() - self.lastFrame
            self.lock.unlock()
            if idle > self.idleTimeout { self.stop() }
        }
        lock.lock()
        watchdog?.cancel()
        watchdog = t
        lock.unlock()
        t.resume()
        DispatchQueue.main.async {
            // The phone must stay awake for the whole game, or iOS pauses the stream.
            UIApplication.shared.isIdleTimerDisabled = true
            NotificationCenter.default.post(name: FrameTap.sessionStarted, object: nil)
        }
    }

    func stop() {
        lock.lock()
        let s = session
        session = nil
        watchdog?.cancel()
        watchdog = nil
        lock.unlock()
        guard let s else { return }
        s.stop()
        DispatchQueue.main.async {
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }
}
