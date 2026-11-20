import json
import sys

from playtranslate.config import AppConfig, GameProfile, Region, load_config, save_config


def test_roundtrip_and_tolerant_loading(tmp_path):
    cfg = load_config(tmp_path / "missing.json")
    cfg.deepl_api_key = "secret:fx"
    cfg.profiles["RDR2"] = GameProfile(name="RDR2", region=Region(0.1, 0.8, 0.8, 0.15), glossary={"Arthur": "آرثر"})
    cfg.active_profile = "RDR2"
    path = tmp_path / "config.json"
    save_config(cfg, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if sys.platform == "win32":
        # Encrypted with the Windows account; the key itself never appears in the file.
        assert raw["deepl_api_key"].startswith("dpapi:") and "secret" not in raw["deepl_api_key"]
    else:
        assert raw["deepl_api_key"] == "plain:secret:fx"
    loaded = load_config(path)
    assert loaded.deepl_api_key == "secret:fx"
    assert loaded.profile.name == "RDR2" and loaded.profile.glossary == {"Arthur": "آرثر"}
    assert abs(loaded.profile.region.y - 0.8) < 1e-9

    raw["capture_fps"] = "not a number"
    raw["unknown_future_key"] = 1
    raw["style"]["font_size"] = 9999
    raw["active_profile"] = "gone"
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.capture_fps == AppConfig().capture_fps
    assert loaded.style.font_size == 120
    assert loaded.active_profile in loaded.profiles


def test_broken_file_does_not_crash(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ broken", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.profiles and (tmp_path / "config.broken.json").exists()


def test_region_pixels_stay_inside():
    r = Region(0.9, 0.9, 0.5, 0.5)
    r.normalize()
    x, y, w, h = r.to_pixels(1920, 1080)
    assert x + w <= 1920 and y + h <= 1080 and w > 0 and h > 0
