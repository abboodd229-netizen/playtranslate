"""DeepL API (Free or Pro). Free keys end in ':fx' and get 500,000 characters a month."""

from __future__ import annotations

import html
import logging
import time

import requests

from .base import AuthError, QuotaExceeded, TranslationError, Translator

log = logging.getLogger(__name__)

FREE_URL = "https://api-free.deepl.com"
PRO_URL = "https://api.deepl.com"


class DeepLTranslator(Translator):
    name = "DeepL"
    supports_tags = True

    def __init__(self, api_key: str, timeout: float = 6.0):
        api_key = (api_key or "").strip()
        if not api_key:
            raise AuthError("أدخل مفتاح DeepL في تبويب الترجمة")
        self.api_key = api_key
        self.base = FREE_URL if api_key.endswith(":fx") else PRO_URL
        self.timeout = timeout
        # One session keeps the TLS connection open: saves ~100 ms per line.
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"DeepL-Auth-Key {api_key}",
            "User-Agent": "PlayTranslate/0.1",
        })

    def _post(self, payload: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._session.post(f"{self.base}/v2/translate", json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(0.3 * (attempt + 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 403:
                raise AuthError("مفتاح DeepL غير صحيح")
            if resp.status_code == 456:
                raise QuotaExceeded("انتهى رصيد DeepL المجاني لهذا الشهر")
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = TranslationError(f"DeepL مشغول ({resp.status_code})")
                time.sleep(0.5 * (attempt + 1))
                continue
            raise TranslationError(f"خطأ من DeepL ({resp.status_code}): {resp.text[:200]}")
        raise TranslationError(f"تعذّر الاتصال بـ DeepL: {last_exc}")

    def translate(self, texts: list[str], context: str = "") -> list[str]:
        if not texts:
            return []
        payload: dict = {
            "text": texts,
            "source_lang": "EN",
            "target_lang": "AR",
            "tag_handling": "xml",
            "ignore_tags": ["x"],
            "preserve_formatting": True,
        }
        if context:
            # Context is not billed and helps with pronouns and short lines.
            payload["context"] = html.escape(context, quote=False)
        data = self._post(payload)
        out = [item.get("text", "") for item in data.get("translations", [])]
        if len(out) != len(texts):
            raise TranslationError("ردّ غير متوقع من DeepL")
        return out

    def usage(self) -> tuple[int, int]:
        """(characters used, monthly limit)."""
        try:
            resp = self._session.get(f"{self.base}/v2/usage", timeout=self.timeout)
        except requests.RequestException as exc:
            raise TranslationError(f"تعذّر الاتصال بـ DeepL: {exc}") from exc
        if resp.status_code == 403:
            raise AuthError("مفتاح DeepL غير صحيح")
        if resp.status_code != 200:
            raise TranslationError(f"خطأ من DeepL ({resp.status_code})")
        data = resp.json()
        return int(data.get("character_count", 0)), int(data.get("character_limit", 0))

    def close(self) -> None:
        self._session.close()
