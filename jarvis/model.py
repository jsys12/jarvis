"""Скачивание и распаковка модели Vosk для русского языка (~45 МБ)."""

import logging
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("jarvis.model")

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def _progress(blocks: int, block_size: int, total: int) -> None:
    if total > 0:
        pct = min(100, blocks * block_size * 100 // total)
        sys.stdout.write(f"\rСкачивание модели: {pct}%")
        sys.stdout.flush()


def ensure_model(models_dir: Path) -> Path:
    """Возвращает путь к модели, при необходимости скачивает её."""
    model_dir = models_dir / MODEL_NAME
    if model_dir.exists():
        return model_dir

    models_dir.mkdir(parents=True, exist_ok=True)
    zip_path = models_dir / f"{MODEL_NAME}.zip"
    log.info("Модель не найдена, скачиваю %s", MODEL_URL)
    try:
        urllib.request.urlretrieve(MODEL_URL, zip_path, reporthook=_progress)
        sys.stdout.write("\n")
        log.info("Распаковка модели...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(models_dir)
    finally:
        zip_path.unlink(missing_ok=True)

    if not model_dir.exists():
        raise RuntimeError(f"После распаковки не найдена папка {model_dir}")
    log.info("Модель готова: %s", model_dir)
    return model_dir
