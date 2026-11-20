"""Settings, game profiles and where they are stored.

Everything is plain dataclasses saved as JSON. Loading is tolerant: unknown
keys are ignored and missing keys take their defaults, so a config written by
an older or newer version never stops the app from starting.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import APP_NAME, keystore

log = logging.getLogger(__name__)

CONFIG_VERSION = 1


def data_dir() -> Path:
    """Per-user folder for config, cache and logs."""
    override = os.environ.get("PLAYTRANSLATE_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "playtranslate"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _from_dict(cls, data: Any):
    """Build a dataclass from a dict, ignoring unknown keys and bad types."""
    if not isinstance(data, dict):
        return cls()
    kwargs = {}
    defaults = cls()
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        current = getattr(defaults, f.name)
        sub = _NESTED.get((cls.__name__, f.name))
        try:
            if sub is not None:
                value = _from_dict(sub, value)
            elif isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int) and not isinstance(current, bool):
                value = int(value)
            elif isinstance(current, float):
                value = float(value)
            elif isinstance(current, str):
                value = str(value)
            elif isinstance(current, dict):
                value = dict(value) if isinstance(value, dict) else current
            elif isinstance(current, list):
                value = [str(v) for v in value] if isinstance(value, list) else current
        except (TypeError, ValueError):
            log.warning("Ignoring bad config value %s.%s=%r", cls.__name__, f.name, value)
            continue
        kwargs[f.name] = value
    obj = cls(**kwargs)
    if hasattr(obj, "normalize"):
        obj.normalize()
    return obj


@dataclass
class Region:
    """Subtitle area, as fractions (0..1) of the Remote Play picture."""

    x: float = 0.12
    y: float = 0.76
    w: float = 0.76
    h: float = 0.20

    def normalize(self) -> None:
        self.x = _clamp(self.x, 0.0, 0.98)
        self.y = _clamp(self.y, 0.0, 0.98)
        self.w = _clamp(self.w, 0.02, 1.0 - self.x)
        self.h = _clamp(self.h, 0.02, 1.0 - self.y)

    def to_pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """(left, top, width, height) in pixels inside a width x height picture."""
        left = int(round(self.x * width))
        top = int(round(self.y * height))
        w = max(1, min(width - left, int(round(self.w * width))))
        h = max(1, min(height - top, int(round(self.h * height))))
        return left, top, w, h


@dataclass
class GameProfile:
    name: str = "افتراضي"
    region: Region = field(default_factory=Region)
    # "light" = white/yellow subtitles (most games), "dark" = dark text on a light box.
    text_mode: str = "light"
    # English term -> Arabic term, applied on every translation for this game.
    glossary: dict = field(default_factory=dict)
    # Show "Name:" speaker labels separately in a different colour.
    split_speaker: bool = True
    # Minimum stroke contrast for text detection; lower finds faint text, higher ignores scenery.
    sensitivity: int = 55

    def normalize(self) -> None:
        self.sensitivity = int(_clamp(self.sensitivity, 25, 140))
        if self.text_mode not in ("light", "dark", "auto"):
            self.text_mode = "light"
        self.glossary = {
            str(k).strip(): str(v).strip()
            for k, v in self.glossary.items()
            if str(k).strip() and str(v).strip()
        }
        if not self.name.strip():
            self.name = "افتراضي"


def preset_profiles() -> list[GameProfile]:
    """Ready-made profiles added once to every config (the user can edit or delete them)."""
    return [
        GameProfile(
            name="GTA VI",
            # Bottom centre only: leaves out the minimap (bottom left) and the
            # money/weapon HUD on the right, which would otherwise be read as text.
            region=Region(x=0.17, y=0.77, w=0.66, h=0.19),
            text_mode="light",
            split_speaker=True,
            sensitivity=55,
            glossary={
                "Lucia": "لوسيا",
                "Jason": "جيسون",
                "Vice City": "فايس سيتي",
                "Leonida": "ليونيدا",
                "Leonida Keys": "جزر ليونيدا",
                "Port Gellhorn": "بورت جيلهورن",
                "Grassrivers": "غراس ريفرز",
                "Ambrosia": "أمبروزيا",
                "Mount Kalaga": "جبل كالاغا",
            },
        ),
    ]


@dataclass
class Style:
    """How the Arabic text looks on the TV and in the laptop overlay."""

    font_family: str = "Noto Naskh Arabic"
    # Size in pixels on a 1080p screen; displays scale it to their own height.
    font_size: int = 44
    text_color: str = "#FFFFFF"
    speaker_color: str = "#FFD54F"
    background_color: str = "#000000"
    background_opacity: float = 0.55
    outline: bool = True
    # Distance of the text box from the bottom edge, as a fraction of screen height.
    bottom_margin: float = 0.17
    max_width: float = 0.8

    def normalize(self) -> None:
        self.font_size = int(_clamp(self.font_size, 16, 120))
        self.background_opacity = _clamp(self.background_opacity, 0.0, 1.0)
        self.bottom_margin = _clamp(self.bottom_margin, 0.0, 0.9)
        self.max_width = _clamp(self.max_width, 0.3, 1.0)
        for name in ("text_color", "speaker_color", "background_color"):
            value = getattr(self, name)
            if not (isinstance(value, str) and value.startswith("#") and len(value) in (7, 9)):
                setattr(self, name, getattr(Style(), name))


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    # Part of the window title to look for. PS Remote Play's window is titled "PS Remote Play".
    window_title: str = "PS Remote Play"
    capture_fps: int = 10
    # "auto" tries Windows OCR first and falls back to RapidOCR.
    ocr_engine: str = "auto"
    # "deepl", "argos" (offline) or "none" (show English, for testing).
    translator: str = "deepl"
    deepl_api_key: str = ""
    # Send previous lines to DeepL as context; better translations, no extra cost.
    use_context: bool = True
    server_port: int = 8765
    discovery_port: int = 8766
    send_to_tv: bool = True
    local_overlay: bool = False
    # Keep the Arabic on screen this long after the English disappears.
    linger_ms: int = 700
    active_profile: str = "افتراضي"
    profiles: dict = field(default_factory=dict)
    # Names of built-in presets already offered, so a deleted preset never comes back.
    seen_presets: list = field(default_factory=list)
    # Look for a newer version on GitHub at start-up.
    check_updates: bool = True
    style: Style = field(default_factory=Style)

    def normalize(self) -> None:
        self.capture_fps = int(_clamp(self.capture_fps, 2, 30))
        self.linger_ms = int(_clamp(self.linger_ms, 0, 5000))
        self.server_port = int(_clamp(self.server_port, 1024, 65535))
        self.discovery_port = int(_clamp(self.discovery_port, 1024, 65535))
        if self.ocr_engine not in ("auto", "windows", "rapid"):
            self.ocr_engine = "auto"
        if self.translator not in ("deepl", "argos", "none"):
            self.translator = "deepl"
        profiles = {}
        for name, raw in (self.profiles or {}).items():
            p = raw if isinstance(raw, GameProfile) else _from_dict(GameProfile, raw)
            p.name = str(name)
            profiles[p.name] = p
        if not profiles:
            p = GameProfile()
            profiles[p.name] = p
        for preset in preset_profiles():
            if preset.name not in self.seen_presets:
                self.seen_presets.append(preset.name)
                if preset.name not in profiles:
                    preset.normalize()
                    profiles[preset.name] = preset
        self.profiles = profiles
        if self.active_profile not in self.profiles:
            self.active_profile = next(iter(self.profiles))

    @property
    def profile(self) -> GameProfile:
        return self.profiles[self.active_profile]

    # ---- persistence -------------------------------------------------

    def to_dict(self) -> dict:
        data = asdict(self)
        data["deepl_api_key"] = keystore.protect(self.deepl_api_key) if self.deepl_api_key else ""
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        cfg = _from_dict(cls, data)
        if cfg.deepl_api_key:
            cfg.deepl_api_key = keystore.unprotect(cfg.deepl_api_key)
        return cfg


_NESTED = {
    ("GameProfile", "region"): Region,
    ("AppConfig", "style"): Style,
}


def config_path() -> Path:
    return data_dir() / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        cfg = AppConfig()
        cfg.normalize()
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AppConfig.from_dict(data)
    except (OSError, ValueError) as exc:
        # Keep the broken file for inspection and start fresh instead of crashing.
        log.error("Could not read %s (%s); starting with defaults", path, exc)
        try:
            path.replace(path.with_suffix(".broken.json"))
        except OSError:
            pass
        cfg = AppConfig()
        cfg.normalize()
        return cfg


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    """Write atomically so a crash mid-save never leaves a half-written file."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
