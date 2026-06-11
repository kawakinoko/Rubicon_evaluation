"""Optional OCR fallback used only when DOM extraction fails."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


def extract_text_from_image(image_path: Path, logger: Any) -> tuple[str, float]:
    """Attempt OCR on a screenshot and return text with average confidence."""

    try:
        image_module = importlib.import_module("PIL.Image")
        pytesseract = importlib.import_module("pytesseract")
    except ImportError:
        logger.warning("OCR fallback requested but Pillow/pytesseract is not installed")
        return "", 0.0

    if not image_path.exists():
        logger.warning("OCR fallback requested but screenshot does not exist: %s", image_path)
        return "", 0.0

    try:
        image = image_module.open(image_path)
        ocr_data = pytesseract.image_to_data(
            image,
            lang="kor+eng",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        logger.exception("OCR execution failed: %s", exc)
        return "", 0.0

    words: list[str] = []
    scores: list[float] = []
    for text, confidence in zip(ocr_data.get("text", []), ocr_data.get("conf", [])):
        normalized = str(text).strip()
        if not normalized:
            continue
        try:
            numeric_confidence = float(confidence)
        except (TypeError, ValueError):
            numeric_confidence = -1.0
        if numeric_confidence >= 0:
            scores.append(numeric_confidence)
        words.append(normalized)

    joined_text = " ".join(words).strip()
    average_confidence = round(sum(scores) / len(scores) / 100.0, 3) if scores else 0.0
    return joined_text, average_confidence
