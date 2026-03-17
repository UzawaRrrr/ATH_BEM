from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def ensure_directories(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def create_logger(log_dir: Path, prefix: str) -> logging.Logger:
    ensure_directories([log_dir])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{prefix}_{timestamp}.log"

    logger = logging.getLogger(f"waveguide_opt.{prefix}.{timestamp}")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger

