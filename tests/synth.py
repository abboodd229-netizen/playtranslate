"""Synthetic game frames with subtitles, for tests without a PS5."""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def background(width: int = 1280, height: int = 720, seed: int = 0, bright: bool = False) -> Image.Image:
    """A busy 'game scene': gradients, shapes and noise."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, height)[:, None]
    x = np.linspace(0, 1, width)[None, :]
    base = 200 if bright else 60
    r = (base + 50 * np.sin(6 * x + seed) * y).clip(0, 255)
    g = (base + 40 * np.cos(4 * y + seed)).clip(0, 255) * np.ones_like(x)
    b = (base * 0.8 + 60 * x * y).clip(0, 255)
    arr = np.stack([r, g, b], axis=-1)
    arr += rng.normal(0, 6, arr.shape)
    img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = int(rng.integers(0, width)), int(rng.integers(0, height))
        size = int(rng.integers(30, 200))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        d.ellipse([x0, y0, x0 + size, y0 + size // 2], fill=color)
    return img


def frame(text: str | None, seed: int = 0, size: int = 34, bright: bool = False, box: bool = False,
          width: int = 1280, height: int = 720) -> np.ndarray:
    """BGR frame with white outlined subtitle text centred near the bottom."""
    img = background(width, height, seed, bright)
    if text:
        d = ImageDraw.Draw(img)
        f = font(size)
        lines = text.split("\n")
        line_h = int(size * 1.35)
        y = int(height * 0.83) - line_h * (len(lines) - 1)
        for line in lines:
            w = d.textlength(line, font=f)
            x = (width - w) / 2
            if box:
                d.rectangle([x - 12, y - 6, x + w + 12, y + line_h], fill=(0, 0, 0))
            d.text((x, y), line, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
            y += line_h
    return np.array(img)[:, :, ::-1].copy()
