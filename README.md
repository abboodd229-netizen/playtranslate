# PlayTranslate

Arabic subtitles for console games, drawn over the game on the TV.

The PS5 plays on the TV directly (no added input lag). A Windows laptop watches the
same screen through PS Remote Play (secondary PSN account), reads the English subtitle
line, translates it with DeepL, and sends the Arabic text to a small Android TV app that
draws it over the HDMI input. If the TV can't run the app, the laptop can draw the
Arabic over the Remote Play window instead.

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
