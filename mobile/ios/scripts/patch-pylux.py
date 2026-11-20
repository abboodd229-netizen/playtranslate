"""PlayTranslate's changes to the Pylux iOS sources (AGPL-3.0, so they are published here).

Each change must match exactly the expected number of times; a Pylux update that moves the
code makes the build fail loudly instead of silently shipping an app without translation.
"""

import re
import sys
from pathlib import Path


def patch(path: Path, pattern: str, replacement: str, count: int, why: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if n != count:
        sys.exit(f"patch-pylux: expected {count} match(es) in {path} ({why}), found {n}")
    path.write_text(new, encoding="utf-8")
    print(f"patched {path.name}: {why}")


def main() -> None:
    root = Path(sys.argv[1]) / "ios" / "Pylux"

    # 1. Hand every decoded game frame to PlayTranslate's reader (FrameTap.swift).
    #    The decoder already exposes frameCallback; Pylux just never sets it.
    patch(
        root / "Services" / "StreamSession.swift",
        r"^(\s*)self\.videoDecoder = decoder$",
        r"\1self.videoDecoder = decoder\n\1decoder.frameCallback = FrameTap.shared.callback",
        2,
        "send decoded frames to the translation reader (LAN and PSN sessions)",
    )

    # 2. No game sound on the phone: the player listens to the TV. Also saves battery and Wi-Fi.
    patch(
        root / "Bridge" / "ChiakiSessionBridge.m",
        r"ci\.audio_video_disabled = CHIAKI_NONE_DISABLED;",
        "ci.audio_video_disabled = CHIAKI_AUDIO_DISABLED; /* PlayTranslate: sound stays on the TV */",
        1,
        "disable stream audio",
    )


if __name__ == "__main__":
    main()
