"""Per-game terms that must always translate the same way.

Before sending a sentence, each glossary term is wrapped in a tag the
translator is told to leave alone; afterwards the tag is replaced by the
Arabic term. This keeps names and game words consistent ("Stamina" is always
"القدرة على التحمل", "Arthur" is always "آرثر") without hoping the engine
guesses right.
"""

from __future__ import annotations

import html
import re


class Glossary:
    def __init__(self, terms: dict[str, str] | None = None):
        self.terms = {k.strip(): v.strip() for k, v in (terms or {}).items() if k.strip() and v.strip()}
        # Longest first so "Saint Denis" wins over "Saint".
        ordered = sorted(self.terms, key=len, reverse=True)
        self._lookup = {k.lower(): self.terms[k] for k in ordered}
        if ordered:
            alternatives = "|".join(re.escape(k) for k in ordered)
            self._pattern = re.compile(rf"(?<![\w])({alternatives})(?![\w])", re.IGNORECASE)
        else:
            self._pattern = None

    def __bool__(self) -> bool:
        return bool(self.terms)

    def protect(self, text: str, use_tags: bool) -> tuple[str, list[str]]:
        """Returns the text to send and the Arabic replacements in order.

        With use_tags the text is XML-escaped and terms become
        <x id="n">term</x> (for DeepL's tag_handling=xml + ignore_tags=x).
        Without tags, terms become placeholders like ⟦0⟧.
        """
        replacements: list[str] = []

        def sub(match: re.Match) -> str:
            idx = len(replacements)
            replacements.append(self._lookup[match.group(1).lower()])
            if use_tags:
                return f'<x id="{idx}">{html.escape(match.group(1), quote=False)}</x>'
            return f"⟦{idx}⟧"

        if use_tags:
            # Escape the plain parts, then tag the terms.
            if self._pattern is None:
                return html.escape(text, quote=False), replacements
            out = []
            last = 0
            for m in self._pattern.finditer(text):
                out.append(html.escape(text[last:m.start()], quote=False))
                out.append(sub(m))
                last = m.end()
            out.append(html.escape(text[last:], quote=False))
            return "".join(out), replacements

        if self._pattern is None:
            return text, replacements
        return self._pattern.sub(sub, text), replacements

    @staticmethod
    def restore(text: str, replacements: list[str], use_tags: bool) -> str:
        if use_tags:
            def tag_sub(m: re.Match) -> str:
                idx = int(m.group(1))
                return replacements[idx] if idx < len(replacements) else html.unescape(m.group(2))

            text = re.sub(r'<x id="(\d+)">(.*?)</x>', tag_sub, text, flags=re.DOTALL)
            # Any stray self-closing or lone tags from the engine.
            text = re.sub(r"</?x[^>]*>", "", text)
            return html.unescape(text)

        def ph_sub(m: re.Match) -> str:
            idx = int(m.group(1))
            return replacements[idx] if idx < len(replacements) else ""

        return re.sub(r"⟦\s*(\d+)\s*⟧", ph_sub, text)

    def translate_speaker(self, name: str) -> str:
        return self._lookup.get(name.strip().lower(), name)
