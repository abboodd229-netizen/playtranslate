# PlayTranslate mobile

`ios/` is the iPhone/iPad app. It is independent from the laptop program and the TV app:
nothing outside `mobile/` and `.github/workflows/ios.yml` belongs to it, except that it bundles
`packs/gta-vi.json`.

How it works: a ReplayKit Broadcast Upload extension receives the screen while PS Remote Play
is open, reads the subtitle area with Apple Vision, translates with DeepL (cache + glossary,
same rules as the laptop's `textproc.py`/`glossary.py`), and runs the same protocol v1
WebSocket server on port 8765 that the TV app already talks to. Discovery: iOS blocks UDP
broadcast without a special entitlement, so the beacon is sent as unicast to every address on
the /24 network; the TV app's manual address field also works.

Build: CI (`ios.yml`, macOS runner) runs `xcodegen generate`, unit tests on a simulator, an
unsigned device build, then ad-hoc signs it to keep the App Group entitlement and zips
`PlayTranslate.ipa`. Players sideload it for free with SideStore/AltStore
(see `docs/INSTALL-ios-ar.md`). A manual run with `release_tag=ios-vX.Y.Z` publishes a
pre-release that is never marked "latest", so the laptop's `releases/latest` links stay put.
