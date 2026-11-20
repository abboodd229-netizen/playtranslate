"""Collect the cases the app was unsure about, and pack them into one report file.

While playing, every subtitle the main OCR engine was unsure of is saved
(the picture and both readings) in <data>/hard_cases, keeping the newest 300.
After playing, one button packs them with the log into a zip on the Desktop
that the player can send, so reading can be tuned on real game footage.
Nothing is ever sent anywhere by the app itself.
"""

from __future__ import annotations

import json
import logging
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np

from .config import AppConfig, data_dir

log = logging.getLogger(__name__)

MAX_CASES = 300


def cases_dir() -> Path:
    d = data_dir() / "hard_cases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_case(image: np.ndarray, first: list, second: list, profile: str) -> None:
    try:
        d = cases_dir()
        stem = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        cv2.imwrite(str(d / f"{stem}.png"), image)
        (d / f"{stem}.json").write_text(json.dumps({
            "profile": profile,
            "main": [l.text for l in first],
            "main_confidence": [round(l.confidence, 3) for l in first],
            "second": [l.text for l in second],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        pngs = sorted(d.glob("*.png"))
        for old in pngs[:-MAX_CASES]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
    except Exception:
        log.exception("Could not save a hard case")


def case_count() -> int:
    return len(list(cases_dir().glob("*.png")))


def build_report(cfg: AppConfig, out_dir: Path | None = None) -> Path:
    """A zip with the hard cases, the logs and the settings (without the DeepL key)."""
    if out_dir is None:
        desktop = Path.home() / "Desktop"
        out_dir = desktop if desktop.is_dir() else data_dir()
    out = out_dir / f"PlayTranslate-report-{time.strftime('%Y%m%d-%H%M')}.zip"
    settings = cfg.to_dict()
    settings["deepl_api_key"] = "(hidden)" if cfg.deepl_api_key else ""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("settings.json", json.dumps(settings, ensure_ascii=False, indent=1))
        for f in sorted(cases_dir().iterdir()):
            z.write(f, f"hard_cases/{f.name}")
        logs = data_dir() / "logs"
        if logs.is_dir():
            for f in sorted(logs.glob("playtranslate.log*")):
                z.write(f, f"logs/{f.name}")
    return out


def clear_cases() -> None:
    for f in cases_dir().iterdir():
        f.unlink(missing_ok=True)
