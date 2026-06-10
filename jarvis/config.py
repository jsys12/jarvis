"""Загрузка конфигурации из config.json рядом с проектом."""

import json
import logging
from pathlib import Path

log = logging.getLogger("jarvis.config")

DEFAULT_CONFIG = {
    # Варианты, в которые распознавание чаще всего превращает слово «Джарвис»
    "wake_words": ["джарвис", "жарвис", "джервис", "джарвиз", "ярвис", "джарвес", "jarvis"],
    "voice": "Pavel",
    "sample_rate": 16000,
    # null — микрофон по умолчанию; иначе индекс устройства из sounddevice
    "input_device": None,
    # Сколько секунд ждать команду после отклика «Слушаю»
    "command_window_sec": 8,
    # Whisper уточняет команду после wake-слова.
    # device: auto (GPU при наличии CUDA, иначе CPU) / cuda / cpu
    # model: auto (GPU -> large-v3-turbo, CPU -> small) или имя модели
    "use_whisper": True,
    "whisper_model": "auto",
    "whisper_device": "auto",
    # Переопределение путей встроенных приложений: {"discord": "C:\\...\\Discord.exe"}
    "app_paths": {},
    # Свои команды: фразы -> действие (путь к exe, ссылка или steam-URI)
    "custom_commands": [],
}


def load_config(base_dir: Path) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = base_dir / "config.json"
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            cfg.update(user)
        except Exception:
            log.exception("Не удалось прочитать %s, использую настройки по умолчанию", path)
    else:
        path.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("Создан конфиг по умолчанию: %s", path)
    return cfg
