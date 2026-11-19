from __future__ import annotations


class TranslationError(Exception):
    """A translation failed; the message is shown to the user (Arabic)."""


class QuotaExceeded(TranslationError):
    """The free monthly allowance is used up; try the next engine."""


class AuthError(TranslationError):
    """Bad or missing API key."""


class Translator:
    name = "base"
    # True when the engine keeps <x id="n">...</x> tags untouched (used for glossary terms).
    supports_tags = False

    def translate(self, texts: list[str], context: str = "") -> list[str]:
        """English -> Arabic, one output per input, same order."""
        raise NotImplementedError

    def close(self) -> None:
        pass


class EchoTranslator(Translator):
    """Returns the English unchanged; for testing the display without a key."""

    name = "none"
    supports_tags = True

    def translate(self, texts: list[str], context: str = "") -> list[str]:
        return list(texts)
