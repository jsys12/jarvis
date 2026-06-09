"""Индекс установленных программ по ярлыкам меню «Пуск».

Позволяет открывать голосом программы, которые не заложены в каталоге apps.py:
«открой обс» -> OBS Studio.lnk.
"""

import logging
import os
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.installed")

# Служебные ярлыки, которые не надо предлагать к запуску
_EXCLUDE = ("uninstall", "удал", "help", "справк", "readme", "manual",
            "website", "веб-сайт", "документ", "update", "repair", "license")


def scan_start_menu() -> dict[str, Path]:
    """Имя программы (нижний регистр) -> путь к .lnk."""
    roots = [
        Path(os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")),
        Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")),
    ]
    index: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem.strip().lower()
            if not name or any(x in name for x in _EXCLUDE):
                continue
            index.setdefault(name, lnk)
    log.info("Меню «Пуск»: проиндексировано %d программ", len(index))
    return index


def find_installed(index: dict[str, Path], spoken: str,
                   threshold: float = 0.75) -> tuple[str, Path] | None:
    best_name, best_path, best_score = None, None, 0.0
    for name, path in index.items():
        score = match_score(spoken, name)
        if score > best_score:
            best_name, best_path, best_score = name, path, score
    if best_score >= threshold:
        log.info("Установленная программа: %r -> %r (score %.2f)", spoken, best_name, best_score)
        return best_name, best_path
    log.info("В меню «Пуск» не найдено: %r (лучший score %.2f, %r)",
             spoken, best_score, best_name)
    return None
