"""Argos Translate: fully offline English -> Arabic.

Lower quality than DeepL but free forever and works without internet. It is
optional: install with `pip install argostranslate`, then use "تنزيل النموذج"
in the app (or call `install_model()`), which downloads about 100 MB once.
"""

from __future__ import annotations

import logging

from .base import TranslationError, Translator

log = logging.getLogger(__name__)


def is_installed() -> bool:
    try:
        import argostranslate.translate  # noqa: F401
    except Exception:
        return False
    return True


def install_model() -> None:
    try:
        import argostranslate.package as pkg
    except Exception as exc:
        raise TranslationError("مكتبة Argos غير مثبتة") from exc
    pkg.update_package_index()
    for p in pkg.get_available_packages():
        if p.from_code == "en" and p.to_code == "ar":
            pkg.install_from_path(p.download())
            return
    raise TranslationError("لم أجد نموذج إنجليزي إلى عربي في Argos")


class ArgosTranslator(Translator):
    name = "Argos (offline)"
    supports_tags = False

    def __init__(self):
        try:
            import argostranslate.translate as tr
        except Exception as exc:
            raise TranslationError("مكتبة Argos غير مثبتة") from exc
        langs = {lang.code: lang for lang in tr.get_installed_languages()}
        if "en" not in langs or "ar" not in langs:
            raise TranslationError("نموذج Argos للعربي غير منزّل")
        self._translation = langs["en"].get_translation(langs["ar"])
        if self._translation is None:
            raise TranslationError("نموذج Argos للعربي غير منزّل")

    def translate(self, texts: list[str], context: str = "") -> list[str]:
        return [self._translation.translate(t) for t in texts]
