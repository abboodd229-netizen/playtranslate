# Third-party components

| Component | License | Where |
| --- | --- | --- |
| Noto Naskh Arabic font | SIL Open Font License 1.1 | `tv-app/app/src/main/res/font/` |
| PySide6 (Qt for Python) | LGPL-3.0 | laptop app |
| RapidOCR + PaddleOCR models | Apache-2.0 | laptop app |
| ONNX Runtime | MIT | laptop app |
| OpenCV | Apache-2.0 | laptop app |
| aiohttp, requests, mss, numpy | Apache-2.0 / BSD / MIT | laptop app |
| pywinrt (winrt-*) | MIT | laptop app (Windows OCR) |
| OkHttp | Apache-2.0 | TV app |

DeepL is an external service used with the user's own API key.

## iPhone app: built-in Remote Play

The iPhone app (`mobile/ios`) includes **Pylux** (https://github.com/ForWard-Technologies-LLC/Pylux),
an open-source fork of **Chiaki / chiaki-ng**, licensed **AGPL-3.0** (with an OpenSSL exception).
It is not stored in this repository: `mobile/ios/scripts/fetch-pylux.sh` downloads a pinned commit
and `mobile/ios/scripts/patch-pylux.py` applies PlayTranslate's two small changes (send decoded frames
to the translation reader, turn off stream audio). Because the app binary combines Pylux with
PlayTranslate's code, the distributed iPhone app as a whole is under AGPL-3.0; its complete source is
this repository plus that Pylux commit. PlayTranslate's own files stay under the MIT License.
Pylux bundles mbedTLS, curl, opus, json-c, nanopb, jerasure and gf-complete under their own licenses.

PlayStation is a trademark of Sony Interactive Entertainment. PlayTranslate is not affiliated with Sony.
