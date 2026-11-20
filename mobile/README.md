# PlayTranslate mobile

`ios/` is the iPhone/iPad app. It is independent from the laptop program and the TV app:
nothing outside `mobile/` and `.github/workflows/ios.yml` belongs to it, except that it bundles
`packs/gta-vi.json`.

How it works (since ios-v0.2.0): the app has Remote Play built in. Its "PlayStation" tab is
Pylux (an open-source Chiaki fork, AGPL-3.0, fetched at a pinned commit by
`scripts/fetch-pylux.sh` and patched by `scripts/patch-pylux.py`). Pylux's video decoder hands
every decoded frame to `App/FrameTap.swift`, which starts a `Session` on the first frame and stops
it 4 s after the last one. The session reads the subtitle area with Apple Vision, translates with
DeepL (cache + glossary, same rules as the laptop's `textproc.py`/`glossary.py`), and runs the
same protocol v1 WebSocket server on port 8765 that the TV app already talks to. Because the
picture comes straight from the console stream, iOS screen recording is not needed and Sony's
app cannot black it out. The old ReplayKit Broadcast Upload extension (screen recording while
PS Remote Play is open) is kept as a fallback. Discovery: iOS blocks UDP broadcast without a
special entitlement, so the beacon is sent as unicast to every address on the /24 network; the
TV app's manual address field also works.

Build: CI (`ios.yml`, macOS 26 runner) fetches and patches Pylux, builds the Chiaki C library for
devices with `scripts/build-chiaki.sh`, runs `xcodegen generate`, runs
the logic tests (shared code, no app host) on a simulator, makes an unsigned device build, then
ad-hoc signs it to keep the App Group entitlement and zips `PlayTranslate.ipa`. Players sideload it for free with SideStore/AltStore
(see `docs/INSTALL-ios-ar.md`). Pushing a tag `ios-vX.Y.Z` (or a manual run with `release_tag=ios-vX.Y.Z`) publishes a
pre-release that is never marked "latest", so the laptop's `releases/latest` links stay put.
