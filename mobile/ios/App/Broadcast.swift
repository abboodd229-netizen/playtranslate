import ReplayKit
import SwiftUI

/// Opens iOS's "Start Broadcast" sheet with our extension already chosen.
final class BroadcastLauncher {
    static let shared = BroadcastLauncher()

    let picker: RPSystemBroadcastPickerView

    private init() {
        picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 44, height: 44))
        picker.showsMicrophoneButton = false
        picker.preferredExtension = BroadcastLauncher.extensionID()
    }

    /// The embedded extension's real bundle id (AltStore and SideStore change ids when they sign).
    static func extensionID() -> String {
        if let plugins = Bundle.main.builtInPlugInsURL,
           let items = try? FileManager.default.contentsOfDirectory(at: plugins, includingPropertiesForKeys: nil) {
            for url in items where url.pathExtension == "appex" {
                if let id = Bundle(url: url)?.bundleIdentifier { return id }
            }
        }
        return (Bundle.main.bundleIdentifier ?? "com.playtranslate.mobile") + ".Broadcast"
    }

    func open() {
        for case let button as UIButton in picker.subviews {
            button.sendActions(for: .allTouchEvents)
        }
    }
}

/// The real system button, kept visible as a fallback in case the big button cannot open the sheet.
struct SystemBroadcastButton: UIViewRepresentable {
    func makeUIView(context: Context) -> UIView {
        let host = UIView(frame: CGRect(x: 0, y: 0, width: 44, height: 44))
        let picker = BroadcastLauncher.shared.picker
        picker.removeFromSuperview()
        picker.frame = host.bounds
        picker.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        host.addSubview(picker)
        return host
    }

    func updateUIView(_ uiView: UIView, context: Context) {}
}
