import threading
import time

from playtranslate.textproc import Segment
from playtranslate.translate.base import Translator
from playtranslate.translate.cache import TranslationCache
from playtranslate.translate.names import NameLearner, find_names
from playtranslate.translate.service import TranslationService


def test_find_names_mid_sentence_only():
    assert find_names("Meet Jason at the marina in Vice City.") == ["Jason", "Vice City"]
    assert find_names("The car is ready. Where is it?") == []
    assert find_names("I told you, Lucia. Not today.") == ["Lucia"]
    assert find_names("Okay, see you on Monday.") == []


def test_learner_needs_two_sightings_and_skips_known():
    n = NameLearner(known={"Jason"})
    assert n.observe(["Ask Jason and Brian about it."]) == []
    assert n.observe(["Did you call Brian yet?"]) == ["Brian"]
    assert n.observe(["Brian again."]) == []


class NamesEngine(Translator):
    name = "fake"
    supports_tags = False

    def __init__(self):
        self.calls = []

    def translate(self, texts, context=""):
        self.calls.append(list(texts))
        table = {"Brian": "براين"}
        return [table.get(t, f"ع[{t}]") for t in texts]


def test_service_learns_name_and_uses_it():
    engine = NamesEngine()
    svc = TranslationService(TranslationCache(":memory:"), [engine], "g", {})
    learned = []
    done = threading.Event()
    svc.on_name_learned = lambda n, a: (learned.append((n, a)), done.set())
    svc.translate([Segment("Tell Brian to wait.")])
    svc.translate([Segment("Where did Brian go?")])
    assert done.wait(3)
    assert learned == [("Brian", "براين")]
    # Next sentence protects the learned name, so the engine never sees it.
    svc.translate([Segment("Brian is late, call Brian now.")])
    assert "Brian" not in " ".join(engine.calls[-1])


def test_pack_import_and_export(tmp_path):
    import json

    from playtranslate.config import AppConfig
    from playtranslate.packs import apply_new_packs, export_pack

    cfg = AppConfig()
    cfg.normalize()
    cache = TranslationCache(":memory:")
    cache.correct("GTA VI", "keep moving", "Keep moving.", "تصحيحي")
    pack = {"format": 1, "profile": "GTA VI", "glossary": {"Cal": "كال", "Lucia": "خطأ"},
            "translations": {"Keep moving.": "استمر بالتحرك.", "Get in the car.": "اركب السيارة."}}
    results = apply_new_packs([("GTA VI", 3, pack)], cfg, cache)
    assert results == [("GTA VI", 2, 1)]
    gta = cfg.profiles["GTA VI"]
    assert gta.auto_glossary["Cal"] == "كال" and gta.glossary["Lucia"] == "لوسيا"
    assert cache.get("GTA VI", "get in the car")[0] == "اركب السيارة."
    assert cache.get("GTA VI", "keep moving")[0] == "تصحيحي"  # the player's correction wins
    assert cfg.pack_versions["GTA VI"] == 3
    # Packs for games the player does not have are ignored.
    assert apply_new_packs([("Other", 1, {**pack, "profile": "Other"})], cfg, cache) == []

    cfg.active_profile = "GTA VI"
    out = export_pack(cfg, cache, tmp_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert out.name == "gta-vi.json" and data["translations"]["Keep moving."] == "تصحيحي"
    assert data["glossary"]["Lucia"] == "لوسيا"
