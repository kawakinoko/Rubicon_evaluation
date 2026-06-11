"""Logging utilities for the Samsung Rubicon QA automation."""

from __future__ import annotations

import logging
from pathlib import Path


def create_logger(log_path: Path) -> logging.Logger:
    """Create a console and file logger writing UTF-8 logs."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("samsung_rubicon_qa")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if logger.handlers:
        logger.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger
