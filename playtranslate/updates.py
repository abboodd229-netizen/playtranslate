"""Tell the user when a newer version is published on GitHub.

One small request at start-up, in the background. Any failure (offline,
GitHub down, rate limit) is silent: the app works the same without it.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request

from . import __version__

log = logging.getLogger(__name__)

REPO = "abboodd229-netizen/playtranslate"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.2.0' -> (0, 2, 0). Anything unreadable -> ()."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)", str(text).strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def check_latest(timeout: float = 6.0) -> tuple[str, str] | None:
    """(version, page url) when GitHub has a newer release, else None."""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"PlayTranslate/{__version__}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(256 * 1024).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - never let this bother the user
        log.info("Update check skipped: %s", exc)
        return None
    tag = str(data.get("tag_name", "")) if isinstance(data, dict) else ""
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    url = str(data.get("html_url") or RELEASES_URL)
    if not url.startswith("https://github.com/"):
        url = RELEASES_URL
    return tag.lstrip("v"), url
