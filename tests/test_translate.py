import pytest
import requests

from playtranslate.textproc import Segment
from playtranslate.translate.base import QuotaExceeded, Translator
from playtranslate.translate.cache import TranslationCache
from playtranslate.translate.deepl import FREE_URL, PRO_URL, DeepLTranslator
from playtranslate.translate.glossary import Glossary
from playtranslate.translate.service import TranslationService


class FakeEngine(Translator):
    name = "fake"
    supports_tags = True

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def translate(self, texts, context=""):
        self.calls.append((list(texts), context))
        if self.fail:
            raise self.fail
        # Pretend translation: prefix, keep tags untouched like DeepL does.
        return [f"AR[{t}]" for t in texts]


class PlainEngine(FakeEngine):
    name = "plain"
    supports_tags = False


def test_glossary_tags_roundtrip_with_escaping():
    g = Glossary({"Arthur": "آرثر", "Saint Denis": "سانت دينيس", "Saint": "قديس"})
    sent, reps = g.protect("Arthur & Dutch go to Saint Denis <now>", use_tags=True)
    assert "&amp;" in sent and "&lt;now&gt;" in sent
    assert sent.count("<x id=") == 2
    out = g.restore(f"AR[{sent}]", reps, use_tags=True)
    assert out == "AR[آرثر & Dutch go to سانت دينيس <now>]"


def test_glossary_placeholders_and_word_boundaries():
    g = Glossary({"Art": "فن"})
    sent, reps = g.protect("Arthur likes Art.", use_tags=False)
    assert sent == "Arthur likes ⟦0⟧."
    assert g.restore("آرثر يحب ⟦ 0 ⟧.", reps, use_tags=False) == "آرثر يحب فن."


def test_cache_corrections_win_and_survive_clear(tmp_path):
    c = TranslationCache(tmp_path / "c.sqlite3")
    c.put("g", "hello", "Hello", "مرحبا", "fake")
    assert c.get("g", "hello") == ("مرحبا", "cache")
    c.correct("g", "hello", "Hello", "أهلًا")
    assert c.get("g", "hello") == ("أهلًا", "user")
    c.clear_machine("g")
    assert c.get("g", "hello") == ("أهلًا", "user")
    assert c.get("other", "hello") is None
    c.close()


def test_service_caches_uses_context_and_glossary(tmp_path):
    engine = FakeEngine()
    svc = TranslationService(TranslationCache(":memory:"), [engine], "g", {"Arthur": "آرثر"})
    r1 = svc.translate([Segment("Hello Arthur.", "ARTHUR")])
    assert r1.segments[0].target == "AR[Hello آرثر.]"
    assert r1.segments[0].speaker_target == "آرثر"
    assert r1.origin == "fake"
    r2 = svc.translate([Segment("hello  arthur", "")])
    assert r2.origin == "cache" and len(engine.calls) == 1
    svc.translate([Segment("Next line.")])
    assert "Hello Arthur." in engine.calls[-1][1]  # previous lines sent as context


def test_service_falls_back_and_never_returns_nothing():
    first = FakeEngine(fail=QuotaExceeded("quota"))
    second = PlainEngine()
    svc = TranslationService(TranslationCache(":memory:"), [first, second], "g")
    r = svc.translate([Segment("Go.")])
    assert r.segments[0].target == "AR[Go.]" and r.origin == "plain"

    broken = FakeEngine(fail=RuntimeError("bug"))
    svc = TranslationService(TranslationCache(":memory:"), [broken], "g")
    r = svc.translate([Segment("Go now.")])
    assert r.segments[0].target == "Go now." and r.error
    # Failures are not cached.
    assert svc.cache.get("g", "go now") is None


def test_user_correction_applies():
    engine = FakeEngine()
    svc = TranslationService(TranslationCache(":memory:"), [engine], "g")
    svc.correct("Hold on!", "انتظر!")
    r = svc.translate([Segment("Hold on!")])
    assert r.segments[0].target == "انتظر!" and r.origin == "user" and not engine.calls


class FakeResp:
    def __init__(self, status, data=None, text=""):
        self.status_code = status
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


def test_deepl_request_shape_and_errors(monkeypatch):
    t = DeepLTranslator("abc:fx")
    assert t.base == FREE_URL
    assert DeepLTranslator("abc").base == PRO_URL
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, json=json)
        return FakeResp(200, {"translations": [{"text": "مرحبا"}]})

    monkeypatch.setattr(t._session, "post", fake_post)
    assert t.translate(["Hello"], context="a < b") == ["مرحبا"]
    assert seen["url"].endswith("/v2/translate")
    assert seen["json"]["target_lang"] == "AR" and seen["json"]["ignore_tags"] == ["x"]
    assert seen["json"]["context"] == "a &lt; b"
    assert t._session.headers["Authorization"] == "DeepL-Auth-Key abc:fx"

    monkeypatch.setattr(t._session, "post", lambda *a, **k: FakeResp(456))
    with pytest.raises(QuotaExceeded):
        t.translate(["x"])

    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("boom")
        return FakeResp(200, {"translations": [{"text": "تم"}]})

    monkeypatch.setattr(t._session, "post", flaky)
    assert t.translate(["Done"]) == ["تم"]
