"""Ready-made memory for each game, shared through the project's GitHub page.

A pack is a JSON file in the repository's packs/ folder holding a game's
names and translated lines. At start-up the app checks packs/index.json once
and quietly imports any newer pack for games the player has: lines go into
the translation memory (never over the player's own) and names into the
learned glossary. So a friend starts GTA VI already knowing its names and
common lines, and those lines cost no DeepL quota.

"Export" writes the same format from the player's own memory, which is how
packs are made.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from . import __version__
from .config import AppConfig, data_dir
from .textproc import cache_key
from .translate.cache import TranslationCache
from .updates import REPO

log = logging.getLogger(__name__)

RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/main/packs/"
FORMAT = 1
MAX_BYTES = 8 * 1024 * 1024


def _fetch_json(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": f"PlayTranslate/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(MAX_BYTES).decode("utf-8"))


def _clean_map(data, max_len: int) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and 0 < len(k) <= max_len and 0 < len(v) <= max_len * 3:
            out[k.strip()] = v.strip()
    return out


def apply_pack(pack: dict, cfg: AppConfig, cache: TranslationCache) -> tuple[str, int, int] | None:
    """Import one pack. Returns (profile, lines added, names added), or None if not for us."""
    if not isinstance(pack, dict) or pack.get("format") != FORMAT:
        return None
    profile_name = str(pack.get("profile", ""))
    profile = cfg.profiles.get(profile_name)
    if profile is None:
        return None
    names = _clean_map(pack.get("glossary"), 60)
    lines = _clean_map(pack.get("translations"), 400)
    added_names = 0
    for en, ar in names.items():
        if en not in profile.glossary and en not in profile.auto_glossary:
            profile.auto_glossary[en] = ar
            added_names += 1
    added_lines = cache.import_many(profile_name, [(cache_key(en), en, ar) for en, ar in lines.items()])
    return profile_name, added_lines, added_names


def fetch_new_packs(cfg: AppConfig) -> list[tuple[str, int, dict]]:
    """Download packs newer than the imported ones, for games in this config.

    Only reads the config (safe from a worker thread). Silent on any failure.
    """
    try:
        index = _fetch_json(RAW_BASE + "index.json")
    except Exception as exc:  # noqa: BLE001 - offline is fine
        log.info("Pack check skipped: %s", exc)
        return []
    found = []
    profiles = set(cfg.profiles)
    done = dict(cfg.pack_versions)
    for entry in index.get("packs", []) if isinstance(index, dict) else []:
        if not isinstance(entry, dict):
            continue
        profile = str(entry.get("profile", ""))
        file = str(entry.get("file", ""))
        try:
            version = int(entry.get("version", 0) or 0)
        except (TypeError, ValueError):
            continue
        if profile not in profiles or not re.fullmatch(r"[a-z0-9-]+\.json", file):
            continue
        if version <= int(done.get(profile, 0) or 0):
            continue
        try:
            found.append((profile, version, _fetch_json(RAW_BASE + file)))
        except Exception as exc:  # noqa: BLE001
            log.info("Pack %s skipped: %s", file, exc)
    return found


def apply_new_packs(found: list[tuple[str, int, dict]], cfg: AppConfig,
                    cache: TranslationCache) -> list[tuple[str, int, int]]:
    """Import what fetch_new_packs found (GUI thread: it changes the config)."""
    results = []
    for profile, version, pack in found:
        result = apply_pack(pack, cfg, cache)
        if result and result[0] == profile:
            cfg.pack_versions[profile] = version
            results.append(result)
            log.info("Pack %s v%s: %s lines, %s names", profile, version, result[1], result[2])
    return results


def export_pack(cfg: AppConfig, cache: TranslationCache, out_dir: Path | None = None) -> Path:
    profile = cfg.profile
    pack = {
        "format": FORMAT,
        "profile": profile.name,
        "exported": time.strftime("%Y-%m-%d"),
        "app_version": __version__,
        "glossary": {**profile.auto_glossary, **profile.glossary},
        "translations": cache.export(profile.name),
    }
    if out_dir is None:
        desktop = Path.home() / "Desktop"
        out_dir = desktop if desktop.is_dir() else data_dir()
    slug = re.sub(r"[^a-z0-9]+", "-", profile.name.lower()).strip("-") or "game"
    out = out_dir / f"{slug}.json"
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
