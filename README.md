# PlayTranslate

**دليل الاستخدام المصوّر:** https://abboodd229-netizen.github.io/playtranslate/

Arabic subtitles for console games, drawn over the game on the TV.

The console plays on the TV directly (no added input lag). Something else reads the English
subtitle line, translates it with DeepL, and sends the Arabic text to a small Android TV app
that draws it over the HDMI input. Four ways to read the game:

- **Windows laptop**: watches the screen through PS Remote Play (secondary PSN account). The
  most accurate; can also draw the Arabic over the Remote Play window when the TV can't run the app.
- **iPhone / iPad** (`mobile/ios`): Remote Play built into the app, no laptop. Experimental.
- **Phone camera** (same iPhone app): the phone on a stand films the TV. No laptop, no second
  PSN account, never talks to the console, works with any console.
- **Android phone** (`mobile/android`): screen capture over PS Remote Play. Experimental.

Arabic install guide: [docs/INSTALL-ar.md](docs/INSTALL-ar.md)

## How it works

```
PS5 ──HDMI──► TV (game + Arabic overlay)  ◄──WebSocket (text only)──┐
 │                                                                   │
 └──Remote Play──► Laptop: capture → detect → OCR → translate ───────┘
```

| Stage | Module | Notes |
| --- | --- | --- |
| Capture | `capture.py`, `winapi.py` | mss copy of the Remote Play client area, DPI-aware; video/image sources for testing |
| Detect | `detect.py` | morphological text mask + row grouping; emits a subtitle once it is stable, and when it disappears |
| OCR | `ocr/` | Windows OCR (fast, needs English OCR pack) → RapidOCR fallback reading the detector's rows (~20 ms/line) |
| Text | `textproc.py` | OCR cleanup, wrapped-line joining, speaker labels, fuzzy de-duplication |
| Translate | `translate/` | user corrections > SQLite cache > DeepL (context + glossary via ignored XML tags) > Argos (offline, optional) |
| Display | `server/`, `gui/overlay.py`, `tv-app/` | WebSocket + UDP discovery beacon; browser test page at `/overlay`; APK served at `/tv.apk` |

## Develop

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m playtranslate                             # GUI
python -m playtranslate --images shots/             # test with screenshots instead of Remote Play
python -m playtranslate --selftest                  # check OCR engines
```

TV app: `cd tv-app && ./gradlew assembleRelease` (Android SDK 34, JDK 17).

Windows build: `packaging\build_windows.bat`, or push to GitHub and download the
`PlayTranslate-windows` artifact from the Build workflow (it also builds the APK and
self-tests the packaged exe on Windows).

## Constraints kept

No console modification, no game-file changes, no DRM or HDCP bypass. Only the subtitle
text is sent to DeepL; images never leave the laptop.

## Author

Idea and development: **Abdullah Alghazwani (عبدالله الغزواني)**. © 2026, released under the MIT License.

## Keeping one signature for the TV app (repository owner, once)

Android only installs an update over the old app when both have the same signature.
Add one repository secret named `PT_SIGNING_PASSWORD` (Settings → Secrets and variables →
Actions → New repository secret) holding any long password (20+ characters). The next build
on `main` makes a signing key, encrypts it with that password (AES-256, PBKDF2 600k) and commits
only the encrypted file `tv-app/signing/release.jks.enc`. Every later build decrypts it.
Keep the password somewhere safe: without it the key cannot be recovered.
