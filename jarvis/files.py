"""Файлы и папки: открыть, посмотреть содержимое, создать."""

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("jarvis.files")

# Основа слова -> папка пользователя. У «музыки» и «видео» намеренно нет
# коротких основ: «открой музыку» — это про плеер, папка только со словом «папка».
_FOLDER_STEMS = {
    "рабоч": "Desktop", "стол": "Desktop",
    "загрузк": "Downloads", "скачанн": "Downloads", "скачк": "Downloads",
    "документ": "Documents",
    "изображен": "Pictures", "картин": "Pictures", "фотограф": "Pictures", "фотк": "Pictures",
    "скриншот": Path("Pictures") / "Screenshots", "скрин": Path("Pictures") / "Screenshots",
}
_FOLDER_STEMS_EXPLICIT = {  # только при явном слове «папка»
    "музык": "Music", "видео": "Videos", "загруз": "Downloads",
}

_EXT_WORDS = {"текст": ".txt", "заметк": ".txt", "маркдаун": ".md",
              "питон": ".py", "джейсон": ".json"}


def resolve_folder(spoken: str, explicit: bool = False) -> Path | None:
    """«загрузки», «рабочем столе» -> реальная папка пользователя."""
    stems = dict(_FOLDER_STEMS)
    if explicit:
        stems.update(_FOLDER_STEMS_EXPLICIT)
    for word in spoken.split():
        for stem, sub in stems.items():
            if word.startswith(stem):
                path = Path.home() / sub
                if path.exists():
                    return path
    return None


def open_folder(path: Path) -> None:
    log.info("Открываю папку: %s", path)
    subprocess.Popen(["explorer", str(path)])


def describe_folder(path: Path, limit: int = 5) -> str:
    """Человеческое описание содержимого папки для озвучки."""
    try:
        entries = list(path.iterdir())
    except OSError:
        return f"Не могу заглянуть в папку {path.name}."
    files = [e for e in entries if e.is_file()]
    dirs = [e for e in entries if e.is_dir()]
    if not entries:
        return f"Папка {path.name} пуста."
    recent = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    names = ", ".join(f.stem for f in recent)
    parts = []
    if files:
        parts.append(f"{len(files)} {_plural(len(files), 'файл', 'файла', 'файлов')}")
    if dirs:
        parts.append(f"{len(dirs)} {_plural(len(dirs), 'папка', 'папки', 'папок')}")
    reply = f"Здесь {' и '.join(parts)}."
    if names:
        reply += f" Последние: {names}."
    return reply


def create_file(folder: Path, name: str, ext: str = ".txt") -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новый файл"
    if not Path(name).suffix:
        name += ext
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{Path(name).stem} {n}{Path(name).suffix}"
    path.touch()
    log.info("Создан файл: %s", path)
    return path


def create_folder(folder: Path, name: str) -> Path:
    name = re.sub(r'[<>:"/\\|?*]', "", name).strip() or "новая папка"
    path = folder / name
    n = 1
    while path.exists():
        n += 1
        path = folder / f"{name} {n}"
    path.mkdir(parents=True)
    log.info("Создана папка: %s", path)
    return path


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many
