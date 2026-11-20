"""Learn character and place names by themselves, so they always read the same.

A capitalised word in the middle of an English sentence is almost always a
name ("Meet Jason at the marina"). When the same name has been seen twice, it
is translated once on its own and added to the game's automatic glossary.
From then on every sentence uses that one Arabic spelling, without the player
typing anything.
"""

from __future__ import annotations

import re
from collections import Counter

# Capitalised words that are not names even mid-sentence.
_NOT_NAMES = {
    "I", "I'm", "I'll", "I've", "I'd", "OK", "Okay", "Mr", "Mrs", "Ms", "Dr", "Sir", "Miss",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "God", "Christmas", "English", "American", "TV",
    "Hey", "Yeah", "Yes", "No", "Oh", "Well", "So", "But", "And", "The", "What", "Why", "How",
}

# A run of one or two capitalised words (letters only, at least 3 long).
_NAME_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?)\b")
# Where a new sentence (or a speaker label) starts: the first word there is capitalised anyway.
_SENTENCE_START = re.compile(r"(^|[.!?…]\s+|:\s+|[\"“(]\s*)$")


def find_names(text: str) -> list[str]:
    names = []
    for m in _NAME_RE.finditer(text):
        name = m.group(1)
        if _SENTENCE_START.search(text[:m.start()]):
            # "Jason, wait" at the start is ambiguous; only count a following second word.
            parts = name.split()
            if len(parts) < 2:
                continue
            name = parts[1]
        if name in _NOT_NAMES or name.split()[0] in _NOT_NAMES:
            continue
        names.append(name)
    return names


class NameLearner:
    def __init__(self, known: set[str] | None = None, threshold: int = 2, limit: int = 400):
        self.known = {k.lower() for k in (known or set())}
        self.threshold = threshold
        self.limit = limit
        self._seen: Counter[str] = Counter()

    def reset(self, known: set[str]) -> None:
        self.known = {k.lower() for k in known}
        self._seen.clear()

    def observe(self, texts: list[str]) -> list[str]:
        """Names that just reached the threshold and are not in any glossary yet."""
        ready = []
        if len(self.known) >= self.limit:
            return ready
        for text in texts:
            for name in find_names(text):
                key = name.lower()
                if key in self.known:
                    continue
                self._seen[key] += 1
                if self._seen[key] >= self.threshold:
                    self.known.add(key)
                    ready.append(name)
        return ready
