"""Turn raw OCR lines into clean subtitle segments ready for translation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .ocr.base import OcrLine

# "ARTHUR: text", "Arthur Morgan: text", "Dr. Kim: text"
_SPEAKER_RE = re.compile(r"^\s*([A-Z][A-Za-z0-9.'\- ]{0,28}?)\s*[:：]\s+(\S.*)$")
_DASH_RE = re.compile(r"^\s*[-–—]\s*")
_SPACES = re.compile(r"\s+")

_REPLACEMENTS = [
    (re.compile(r"[‘’`´]"), "'"),
    (re.compile(r"[“”]"), '"'),
    (re.compile(r"…"), "..."),
    # A lone "|" or "l" between spaces is almost always the pronoun I.
    (re.compile(r"(?<![A-Za-z])[|l](?=\s|'m|'ll|'ve|'d\b)"), "I"),
    (re.compile(r"\s+([,.!?;:])"), r"\1"),
    # "0" inside a word is "O" ("C0ME" -> "COME").
    (re.compile(r"(?<=[A-Za-z])0(?=[A-Za-z])"), "O"),
]


@dataclass
class Segment:
    text: str
    speaker: str = ""


def clean_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch.isprintable())
    for pattern, repl in _REPLACEMENTS:
        text = pattern.sub(repl, text)
    return _SPACES.sub(" ", text).strip()


def _is_junk(text: str) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    if letters < 2:
        return True
    visible = sum(not ch.isspace() for ch in text)
    return letters / max(1, visible) < 0.5


def to_segments(lines: list[OcrLine], split_speaker: bool = True) -> list[Segment]:
    """Join wrapped lines into sentences; start a new segment at each speaker or dash.

    A two-line subtitle is one sentence and must be translated as one, while
    "- Hi.\n- Hello." is two people and stays two segments.
    """
    segments: list[Segment] = []
    for raw in lines:
        text = clean_line(raw.text)
        if not text or _is_junk(text):
            continue
        starts_new = False
        speaker = ""
        if _DASH_RE.match(text):
            text = _DASH_RE.sub("", text)
            starts_new = True
        if split_speaker:
            m = _SPEAKER_RE.match(text)
            if m and len(m.group(1).split()) <= 3:
                speaker, text = m.group(1).strip(), m.group(2).strip()
                starts_new = True
        if segments and not starts_new:
            segments[-1].text = f"{segments[-1].text} {text}"
        else:
            segments.append(Segment(text, speaker))
    return segments


def cache_key(text: str) -> str:
    """Stable key so OCR noise in case/spacing/quotes hits the same cache entry."""
    text = clean_line(text).lower()
    return text.rstrip(" .")


def similar(a: str, b: str, threshold: float = 0.9) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


def joined(segments: list[Segment]) -> str:
    return "\n".join(f"{s.speaker}: {s.text}" if s.speaker else s.text for s in segments)
