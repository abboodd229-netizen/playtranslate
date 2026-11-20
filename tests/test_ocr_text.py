import time

from playtranslate.config import Region
from playtranslate.detect import Stable, SubtitleDetector
from playtranslate.ocr.base import OcrLine, sort_lines
from playtranslate.textproc import cache_key, clean_line, joined, similar, to_segments

from synth import frame


def L(text, y, x=0, h=20, w=200):
    return OcrLine(text, (x, y, w, h))


def test_clean_line_fixes_common_ocr_errors():
    assert clean_line("|  think  so .") == "I think so."
    assert clean_line("l'm here") == "I'm here"
    assert clean_line("C0ME  BACK") == "COME BACK"
    assert clean_line("It’s fine…") == "It's fine..."


def test_wrapped_lines_join_and_speakers_split():
    segs = to_segments([L("ARTHUR: We should get", 0), L("going before dark.", 30), L("DUTCH: Agreed.", 60)])
    assert [(s.speaker, s.text) for s in segs] == [("ARTHUR", "We should get going before dark."),
                                                    ("DUTCH", "Agreed.")]
    segs = to_segments([L("- Hi.", 0), L("- Hello.", 30)])
    assert [s.text for s in segs] == ["Hi.", "Hello."]


def test_speaker_split_can_be_disabled_and_junk_dropped():
    segs = to_segments([L("Note: keep this", 0), L("|| ..", 30)], split_speaker=False)
    assert joined(segs) == "Note: keep this"


def test_sort_lines_merges_same_row():
    lines = sort_lines([L("world", 0, x=300), L("Second", 40), L("Hello", 2, x=0)])
    assert [l.text for l in lines] == ["Hello world", "Second"]


def test_cache_key_and_similarity():
    assert cache_key("Hello  there.") == cache_key("hello there")
    assert similar("We need to leave town.", "We need to leave t0wn.")
    assert not similar("We need to leave town.", "Where is the horse?")


def test_rapidocr_reads_detector_crop(rapid_engine):
    det = SubtitleDetector()
    text = "Arthur: We need to leave town before dawn."
    img = frame(text, seed=3)
    h, w = img.shape[:2]
    x, y, cw, ch = Region().to_pixels(w, h)
    ev = None
    for _ in range(3):
        ev = det.feed(img[y:y + ch, x:x + cw]) or ev
    assert isinstance(ev, Stable)
    t = time.perf_counter()
    lines = rapid_engine.recognize(ev.image, ev.rows)
    elapsed = (time.perf_counter() - t) * 1000
    segs = to_segments(lines)
    assert len(segs) == 1
    assert segs[0].speaker == "Arthur"
    assert similar(segs[0].text, "We need to leave town before dawn.", 0.92), segs[0].text
    print(f"RapidOCR on crop {ev.image.shape}: {elapsed:.0f} ms")


def test_rapidocr_two_line_subtitle(rapid_engine):
    det = SubtitleDetector()
    img = frame("If we don't find the horses soon,\nwe will never make it home.", seed=5)
    h, w = img.shape[:2]
    x, y, cw, ch = Region().to_pixels(w, h)
    ev = None
    for _ in range(3):
        ev = det.feed(img[y:y + ch, x:x + cw]) or ev
    assert isinstance(ev, Stable)
    segs = to_segments(rapid_engine.recognize(ev.image, ev.rows))
    assert len(ev.rows) == 2
    assert len(segs) == 1
    assert similar(segs[0].text, "If we don't find the horses soon, we will never make it home.", 0.9), segs[0].text


def test_garble_score_and_second_opinion():
    import numpy as np

    from playtranslate.ocr import SecondOpinion, garble_score
    from playtranslate.ocr.base import OcrEngine, OcrLine

    assert garble_score("Meet me at the marina in Vice City.") == 0
    assert garble_score("We got 2nd place, 100% sure.") == 0
    assert garble_score("Me|et m3e at th~e mAri") > 0.5

    class Fixed(OcrEngine):
        def __init__(self, text):
            self.name, self.text = "fixed", text

        def recognize(self, image, rows=None):
            return [OcrLine(self.text, (0, 0, 10, 10), 1.0)]

        def warm_up(self):
            pass

    eng = SecondOpinion(Fixed("Me|et m3e at th~e mAri"), "rapid")
    eng._secondary = Fixed("Meet me at the marina")
    seen = []
    eng.on_doubt = lambda img, a, b: seen.append((a[0].text, b[0].text))
    out = eng.recognize(np.zeros((10, 10, 3), np.uint8))
    assert out[0].text == "Meet me at the marina" and seen
    clean = SecondOpinion(Fixed("All good here."), "rapid")
    assert clean.recognize(np.zeros((10, 10, 3), np.uint8))[0].text == "All good here."


def test_report_zip_hides_key(tmp_path, monkeypatch):
    import json
    import zipfile

    import numpy as np

    monkeypatch.setenv("PLAYTRANSLATE_HOME", str(tmp_path / "home"))
    from playtranslate import report
    from playtranslate.config import AppConfig
    from playtranslate.ocr.base import OcrLine

    report.save_case(np.zeros((20, 40, 3), np.uint8), [OcrLine("x|y", (0, 0, 1, 1), 0.4)], [], "GTA VI")
    cfg = AppConfig()
    cfg.deepl_api_key = "secret-key:fx"
    cfg.normalize()
    out = report.build_report(cfg, tmp_path)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        settings = json.loads(z.read("settings.json"))
    assert any(n.endswith(".png") for n in names)
    assert "secret" not in json.dumps(settings)
