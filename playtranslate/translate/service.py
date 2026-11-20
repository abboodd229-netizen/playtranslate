"""One place that turns English segments into Arabic.

Order for each segment: user correction > cache > glossary + engine (with
automatic fallback to the next engine if the first fails or runs out of quota).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

from ..textproc import Segment, cache_key
from .base import AuthError, EchoTranslator, QuotaExceeded, TranslationError, Translator
from .cache import TranslationCache
from .glossary import Glossary
from .names import NameLearner

log = logging.getLogger(__name__)


@dataclass
class TranslatedSegment:
    source: str
    target: str
    speaker: str
    speaker_target: str
    origin: str  # user | cache | engine name


@dataclass
class TranslationResult:
    segments: list[TranslatedSegment]
    ms: float
    error: str = ""

    @property
    def text(self) -> str:
        return "\n".join(
            f"{s.speaker_target}: {s.target}" if s.speaker_target else s.target for s in self.segments
        )

    @property
    def origin(self) -> str:
        origins = {s.origin for s in self.segments}
        return origins.pop() if len(origins) == 1 else "mixed"


class TranslationService:
    def __init__(self, cache: TranslationCache, engines: list[Translator], profile: str = "",
                 glossary: dict | None = None, use_context: bool = True, auto_glossary: dict | None = None):
        self.cache = cache
        self.engines = engines or [EchoTranslator()]
        self.profile = profile
        self.use_context = use_context
        self._recent: deque[str] = deque(maxlen=3)
        self._lock = threading.Lock()
        self.last_error = ""
        # Called with (english_name, arabic_name) when a name is learned (from a worker thread).
        self.on_name_learned = lambda name, arabic: None
        self.learn_names = True
        self._user_glossary: dict = {}
        self._auto_glossary: dict = {}
        self.names = NameLearner()
        self.set_profile(profile, glossary or {}, auto_glossary or {})

    def set_profile(self, profile: str, glossary: dict, auto_glossary: dict | None = None) -> None:
        with self._lock:
            changed_profile = profile != self.profile
            self.profile = profile
            self._user_glossary = dict(glossary)
            if auto_glossary is not None:
                self._auto_glossary = dict(auto_glossary)
            # The player's own terms win over learned ones.
            self.glossary = Glossary({**self._auto_glossary, **self._user_glossary})
            if changed_profile:
                self._recent.clear()
            self.names.reset(set(self._user_glossary) | set(self._auto_glossary))

    def set_engines(self, engines: list[Translator]) -> None:
        with self._lock:
            old = self.engines
            self.engines = engines or [EchoTranslator()]
        for e in old:
            if e not in self.engines:
                e.close()

    def translate(self, segments: list[Segment]) -> TranslationResult:
        start = time.perf_counter()
        with self._lock:
            profile, glossary, engines = self.profile, self.glossary, list(self.engines)
            context = " ".join(self._recent) if self.use_context else ""

        results: list[TranslatedSegment | None] = [None] * len(segments)
        pending: list[int] = []
        for i, seg in enumerate(segments):
            hit = self.cache.get(profile, cache_key(seg.text))
            if hit:
                results[i] = TranslatedSegment(seg.text, hit[0], seg.speaker,
                                               glossary.translate_speaker(seg.speaker), hit[1])
            else:
                pending.append(i)

        error = ""
        if pending:
            texts = [segments[i].text for i in pending]
            translated, engine_name, error = self._run_engines(engines, texts, glossary, context)
            for i, target in zip(pending, translated):
                seg = segments[i]
                if engine_name not in ("none", ""):
                    self.cache.put(profile, cache_key(seg.text), seg.text, target, engine_name)
                results[i] = TranslatedSegment(seg.text, target, seg.speaker,
                                               glossary.translate_speaker(seg.speaker), engine_name)

        with self._lock:
            for seg in segments:
                self._recent.append(seg.text)
        self.last_error = error
        if self.learn_names:
            new_names = self.names.observe([s.text for s in segments])
            if new_names:
                threading.Thread(target=self._learn, args=(new_names, profile, engines),
                                 name="learn-names", daemon=True).start()
        return TranslationResult([r for r in results if r is not None], (time.perf_counter() - start) * 1000, error)

    def _run_engines(self, engines: list[Translator], texts: list[str], glossary: Glossary,
                     context: str) -> tuple[list[str], str, str]:
        errors: list[str] = []
        for engine in engines:
            try:
                prepared = [glossary.protect(t, engine.supports_tags) for t in texts]
                out = engine.translate([p[0] for p in prepared], context=context)
                restored = [glossary.restore(o, p[1], engine.supports_tags).strip()
                            for o, p in zip(out, prepared)]
                return restored, engine.name, ""
            except (QuotaExceeded, AuthError, TranslationError) as exc:
                log.warning("Engine %s failed: %s", engine.name, exc)
                errors.append(str(exc))
            except Exception as exc:  # a bug in an engine must not kill the pipeline
                log.exception("Engine %s crashed", engine.name)
                errors.append(f"{engine.name}: {exc}")
        # Every engine failed: show the English so the player is not left with nothing.
        return list(texts), "", "؛ ".join(errors)

    def _learn(self, names: list[str], profile: str, engines: list[Translator]) -> None:
        """Translate new names on their own (one short request) and add them to the auto glossary."""
        engine = next((e for e in engines if not isinstance(e, EchoTranslator)), None)
        if engine is None:
            return
        try:
            out = engine.translate(names, context="")
        except Exception as exc:  # quota, network: try again next time the name shows up
            log.info("Could not learn names %s: %s", names, exc)
            with self._lock:
                for n in names:
                    self.names.known.discard(n.lower())
            return
        learned = {}
        for name, arabic in zip(names, out):
            arabic = arabic.strip().strip(".،")
            # A name must come back as a short Arabic word or two, not a sentence or the English.
            if not arabic or arabic.lower() == name.lower() or len(arabic.split()) > 3:
                continue
            if not any("\u0600" <= ch <= "\u06ff" for ch in arabic):
                continue
            learned[name] = arabic
        if not learned:
            return
        with self._lock:
            if profile != self.profile:
                return
            self._auto_glossary.update(learned)
            self.glossary = Glossary({**self._auto_glossary, **self._user_glossary})
        for name, arabic in learned.items():
            log.info("Learned name %s -> %s", name, arabic)
            try:
                self.on_name_learned(name, arabic)
            except Exception:
                log.exception("on_name_learned failed")

    def correct(self, source: str, target: str) -> None:
        self.cache.correct(self.profile, cache_key(source), source, target.strip())
