"""Run once before PyInstaller so RapidOCR's model files exist inside the package folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from playtranslate.ocr.rapid import RapidOcr  # noqa: E402

engine = RapidOcr()
engine.warm_up()
engine.recognize(np.zeros((64, 256, 3), np.uint8))
print("RapidOCR models ready")
