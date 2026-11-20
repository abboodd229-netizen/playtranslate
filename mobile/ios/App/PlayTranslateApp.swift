import SwiftUI
import UIKit

@main
struct PlayTranslateApp: App {
    @UIApplicationDelegateAdaptor(PlayTranslateAppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

/// Lets the Remote Play screen lock itself to landscape (AppOrientationLock comes from Pylux).
final class PlayTranslateAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication,
                     supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        AppOrientationLock.maskForAppDelegate
    }
}

/// Two tabs: the PlayStation (built-in Remote Play, from Pylux) and PlayTranslate's own settings.
struct RootView: View {
    enum Tab: Hashable { case playstation, translate }

    @State private var tab: Tab = .translate

    var body: some View {
        TabView(selection: $tab) {
            ContentView()   // Pylux's Remote Play screen: consoles, sign-in, linking, stream
                .environment(\.layoutDirection, .leftToRight)
                .tabItem { Label("البلايستيشن", systemImage: "gamecontroller.fill") }
                .tag(Tab.playstation)

            TranslateView(openPlayStation: { tab = .playstation })
                .environment(\.layoutDirection, .rightToLeft)
                .environment(\.locale, Locale(identifier: "ar"))
                .tabItem { Label("الترجمة", systemImage: "character.bubble.fill") }
                .tag(Tab.translate)
        }
    }
}
