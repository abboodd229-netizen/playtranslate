import Foundation

/// The app and the screen-reading extension share settings and status through an App Group.
/// AltStore and SideStore rename the group when they sign the app with a free Apple ID and
/// list the new name under ALTAppGroups in Info.plist, so that name is used when present.
enum AppGroup {
    static let defaultID = "group.com.playtranslate.mobile"

    static let id: String = {
        if let groups = Bundle.main.object(forInfoDictionaryKey: "ALTAppGroups") as? [String],
           let first = groups.first(where: { !$0.isEmpty }) {
            return first
        }
        return defaultID
    }()

    static var containerURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: id)
    }

    /// False when the signing step dropped the App Group: the extension would not see the settings.
    static var isAvailable: Bool { containerURL != nil }

    static let defaults: UserDefaults = UserDefaults(suiteName: id) ?? .standard

    /// Writable folder for the translation cache: the shared container, else the local caches folder.
    static var dataFolder: URL {
        if let url = containerURL { return url }
        return FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    }
}
