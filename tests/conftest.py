import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYTRANSLATE_HOME", str(tmp_path / "home"))
    yield


@pytest.fixture(scope="session")
def rapid_engine():
    from playtranslate.ocr.rapid import RapidOcr

    engine = RapidOcr()
    engine.warm_up()
    return engine
