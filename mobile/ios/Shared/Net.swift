import Darwin
import Foundation
import Network

enum Net {
    static let port: UInt16 = 8765          // same as the laptop, so the TV app needs no change
    static let discoveryPort: UInt16 = 8766
    static let beaconMagic = "playtranslate"
    static let protocolVersion = 1

    /// The phone's Wi-Fi address (or its hotspot address when the TV joins the phone's hotspot).
    static func localIPv4() -> String? {
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return nil }
        defer { freeifaddrs(list) }
        var fallback: String?
        for ptr in sequence(first: first, next: { $0.pointee.ifa_next }) {
            let ifa = ptr.pointee
            guard let addr = ifa.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET),
                  (ifa.ifa_flags & UInt32(IFF_UP)) != 0 else { continue }
            let name = String(cString: ifa.ifa_name)
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            guard getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count),
                              nil, 0, NI_NUMERICHOST) == 0 else { continue }
            let ip = String(cString: host)
            if ip.hasPrefix("127.") || ip.hasPrefix("169.254.") { continue }
            if name == "en0" { return ip }
            if name.hasPrefix("bridge") || name.hasPrefix("en") { fallback = fallback ?? ip }
        }
        return fallback
    }
}

/// Lets the TV app find the phone without typing an address. The laptop sends a UDP
/// broadcast; iOS only allows broadcasts with a special Apple permission, so the phone
/// sends the same small beacon to every address on its /24 network instead.
final class Beacon {
    private let name: String
    private var timer: DispatchSourceTimer?
    private var fd: Int32 = -1
    private let queue = DispatchQueue(label: "playtranslate.beacon", qos: .utility)

    init(name: String) { self.name = name }

    func start() {
        queue.async { [self] in
            guard timer == nil else { return }
            fd = socket(AF_INET, SOCK_DGRAM, 0)
            guard fd >= 0 else { return }
            var on: Int32 = 1
            setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &on, socklen_t(MemoryLayout<Int32>.size))
            _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
            let t = DispatchSource.makeTimerSource(queue: queue)
            t.schedule(deadline: .now(), repeating: 2.0)
            t.setEventHandler { [weak self] in self?.sweep() }
            t.resume()
            timer = t
        }
    }

    func stop() {
        queue.sync {
            timer?.cancel()
            timer = nil
            if fd >= 0 { close(fd); fd = -1 }
        }
    }

    private func sweep() {
        guard fd >= 0, let ip = Net.localIPv4() else { return }
        let parts = ip.split(separator: ".").map(String.init)
        guard parts.count == 4 else { return }
        let payload: [String: Any] = ["app": Net.beaconMagic, "protocol": Net.protocolVersion, "port": Int(Net.port),
                                      "name": name, "ips": [ip]]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return }
        let prefix = parts[0...2].joined(separator: ".")
        var targets = ["255.255.255.255", prefix + ".255"]
        for i in 1...254 where String(i) != parts[3] { targets.append("\(prefix).\(i)") }
        data.withUnsafeBytes { (buf: UnsafeRawBufferPointer) in
            for target in targets {
                var addr = sockaddr_in()
                addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
                addr.sin_family = sa_family_t(AF_INET)
                addr.sin_port = Net.discoveryPort.bigEndian
                guard inet_pton(AF_INET, target, &addr.sin_addr) == 1 else { continue }
                _ = withUnsafePointer(to: &addr) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        sendto(fd, buf.baseAddress, buf.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
        }
    }
}

/// WebSocket server the TV app connects to. Speaks protocol v1, exactly like the
/// laptop's playtranslate/server/server.py, so the TV app works unchanged.
final class DisplayServer {
    private let name: String
    private let queue = DispatchQueue(label: "playtranslate.server", qos: .userInitiated)
    private var listener: NWListener?
    private var clients: [ObjectIdentifier: NWConnection] = [:]
    private var ready: Set<ObjectIdentifier> = []
    private var state: [String: Any]?
    private var seq = 0
    private var style: [String: Any]
    private var pingTimer: DispatchSourceTimer?
    private var stopped = true
    private var retries = 0

    /// Called on a background queue.
    var onClientsChanged: ((Int) -> Void)?
    var onTranslatePage: (() -> Void)?
    /// Called once when the port could not be opened after several tries.
    var onFailure: ((String) -> Void)?

    init(name: String, style: [String: Any]) {
        self.name = name
        self.style = style
    }

    func start() {
        queue.async { [self] in
            stopped = false
            retries = 0
            listen()
            let t = DispatchSource.makeTimerSource(queue: queue)
            t.schedule(deadline: .now() + 5, repeating: 5)
            t.setEventHandler { [weak self] in
                self?.broadcast(["type": "ping", "t": Date().timeIntervalSince1970])
            }
            t.resume()
            pingTimer = t
        }
    }

    private func listen() {
        let params = NWParameters.tcp
        params.allowLocalEndpointReuse = true
        let ws = NWProtocolWebSocket.Options()
        ws.autoReplyPing = true
        ws.maximumMessageSize = 64 * 1024
        params.defaultProtocolStack.applicationProtocols.insert(ws, at: 0)
        guard let port = NWEndpoint.Port(rawValue: Net.port), let l = try? NWListener(using: params, on: port) else {
            retryListen("تعذّر فتح المنفذ \(Net.port)")
            return
        }
        l.newConnectionHandler = { [weak self] c in self?.accept(c) }
        l.stateUpdateHandler = { [weak self] st in
            guard let self else { return }
            switch st {
            case .ready: self.retries = 0
            case .failed(let err):
                l.cancel()
                if self.listener === l { self.listener = nil }
                self.retryListen("المنفذ \(Net.port) مستخدم (\(err.localizedDescription))")
            default: break
            }
        }
        listener = l
        l.start(queue: queue)
    }

    /// The port can still be held for a moment by the app's TV test; try again for ~15 seconds.
    private func retryListen(_ why: String) {
        guard !stopped else { return }
        retries += 1
        if retries > 15 {
            onFailure?(why)
            return
        }
        queue.asyncAfter(deadline: .now() + 1) { [weak self] in
            guard let self, !self.stopped, self.listener == nil else { return }
            self.listen()
        }
    }

    func stop() {
        queue.sync {
            stopped = true
            pingTimer?.cancel()
            pingTimer = nil
            listener?.cancel()
            listener = nil
            for c in clients.values { c.cancel() }
            clients.removeAll()
            ready.removeAll()
        }
    }

    var clientCount: Int { queue.sync { ready.count } }

    private func accept(_ c: NWConnection) {
        let id = ObjectIdentifier(c)
        clients[id] = c
        c.stateUpdateHandler = { [weak self, weak c] st in
            guard let self, let c else { return }
            switch st {
            case .ready:
                self.ready.insert(id)
                var hello: [String: Any] = ["type": "hello", "protocol": Net.protocolVersion, "server": self.name,
                                            "version": "ios-0.1.0"]
                hello["style"] = self.style
                self.send(hello, to: c)
                if let state = self.state { self.send(state, to: c) }
                self.onClientsChanged?(self.ready.count)
            case .failed, .cancelled:
                self.drop(c)
            default: break
            }
        }
        c.start(queue: queue)
        receive(c)
    }

    private func drop(_ c: NWConnection) {
        let id = ObjectIdentifier(c)
        guard clients.removeValue(forKey: id) != nil else { return }
        ready.remove(id)
        c.cancel()
        onClientsChanged?(ready.count)
    }

    private func receive(_ c: NWConnection) {
        c.receiveMessage { [weak self, weak c] data, context, _, error in
            guard let self, let c else { return }
            if let meta = context?.protocolMetadata(definition: NWProtocolWebSocket.definition) as? NWProtocolWebSocket.Metadata,
               meta.opcode == .close {
                self.drop(c)
                return
            }
            if let data, !data.isEmpty,
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               obj["type"] as? String == "translate_page" {
                self.onTranslatePage?()
            }
            if error != nil {
                self.drop(c)
            } else {
                self.receive(c)
            }
        }
    }

    private func send(_ message: [String: Any], to c: NWConnection) {
        guard let data = try? JSONSerialization.data(withJSONObject: message) else { return }
        let meta = NWProtocolWebSocket.Metadata(opcode: .text)
        let context = NWConnection.ContentContext(identifier: "text", metadata: [meta])
        c.send(content: data, contentContext: context, isComplete: true, completion: .contentProcessed { [weak self, weak c] err in
            if err != nil, let self, let c { self.drop(c) }
        })
    }

    private func broadcast(_ message: [String: Any]) {
        for (id, c) in clients where ready.contains(id) { send(message, to: c) }
    }

    // MARK: public, thread-safe

    /// lines: [["speaker": "...", "text": "..."]]; mode "page" = whole-screen translation.
    func show(_ lines: [[String: String]], mode: String = "subtitle") {
        queue.async { [self] in
            seq += 1
            var msg: [String: Any] = ["type": "show", "seq": seq, "lines": lines]
            if mode == "page" { msg["mode"] = "page" }
            state = msg
            broadcast(msg)
        }
    }

    func hide() {
        queue.async { [self] in
            state = nil
            broadcast(["type": "hide", "seq": seq])
        }
    }

    func setStyle(_ newStyle: [String: Any]) {
        queue.async { [self] in
            style = newStyle
            broadcast(["type": "style", "style": newStyle])
        }
    }
}
