from playtranslate.config import Region
from playtranslate.detect import DetectorSettings, Gone, Stable, SubtitleDetector

from synth import frame

REGION = Region()


def crop(img):
    h, w = img.shape[:2]
    x, y, cw, ch = REGION.to_pixels(w, h)
    return img[y:y + ch, x:x + cw]


def feed(det, img, times=1):
    events = []
    for _ in range(times):
        ev = det.feed(crop(img))
        if ev is not None:
            events.append(ev)
    return events


def test_no_text_no_events():
    det = SubtitleDetector()
    for seed in range(6):
        assert feed(det, frame(None, seed=seed)) == []


def test_bright_scene_without_text_is_not_text():
    det = SubtitleDetector()
    for seed in range(4):
        assert feed(det, frame(None, seed=seed, bright=True), times=3) == []


def test_appear_stable_once_then_gone():
    det = SubtitleDetector(DetectorSettings(stable_frames=2, gone_frames=3))
    img = frame("We need to leave town before dawn.")
    events = feed(det, img, times=6)
    assert len(events) == 1 and isinstance(events[0], Stable)
    # The tight crop is smaller than the region but holds the text.
    assert events[0].image.shape[0] < crop(img).shape[0]
    events = feed(det, frame(None), times=3)
    assert len(events) == 1 and isinstance(events[0], Gone)


def test_text_change_without_gap_reports_again():
    det = SubtitleDetector()
    a = feed(det, frame("First line of dialogue here."), times=4)
    b = feed(det, frame("A completely different sentence now!"), times=4)
    assert len(a) == 1 and len(b) == 1 and isinstance(b[0], Stable)


def test_typewriter_reports_only_complete_line():
    det = SubtitleDetector(DetectorSettings(stable_frames=2))
    full = "The quick brown fox jumps over"
    events = []
    for n in range(8, len(full) + 1, 4):
        events += feed(det, frame(full[:n]), times=1)
    events += feed(det, frame(full), times=3)
    stables = [e for e in events if isinstance(e, Stable)]
    assert len(stables) == 1


def test_text_on_bright_background_and_box():
    det = SubtitleDetector()
    assert any(isinstance(e, Stable) for e in feed(det, frame("Hello there, stranger.", bright=True), times=3))
    det = SubtitleDetector()
    assert any(isinstance(e, Stable) for e in feed(det, frame("Inside a black box.", box=True), times=3))


def test_overlapping_row_groups_merge_into_one_line():
    from playtranslate.detect import _merge_overlapping

    assert _merge_overlapping([(1, 1, 1156, 87), (795, 36, 259, 45)]) == [(1, 1, 1156, 87)]
    # Two real lines stay separate.
    assert len(_merge_overlapping([(0, 0, 500, 40), (0, 50, 480, 40)])) == 2
