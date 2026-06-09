"""Низкоуровневые действия: запуск, завершение процессов, скриншоты, ссылки."""

import datetime
import logging
import os
import subprocess
import webbrowser
from pathlib import Path

from PIL import ImageGrab

log = logging.getLogger("jarvis.actions")

BROWSER_PROCS = ["chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "browser.exe"]
SCREENSHOTS_DIR = Path.home() / "Pictures" / "Screenshots"


def run_spec(spec) -> None:
    """Выполняет открывающее действие: ("uri"|"exe"|"cmd", значение)."""
    kind, value = spec
    log.info("Запуск: %s %s", kind, value)
    if kind == "cmd":
        subprocess.Popen(value)
    elif kind == "exe":
        os.startfile(value)
    else:  # uri / ссылка / всё, что умеет оболочка
        os.startfile(value)


def spec_from_string(action: str):
    """Превращает строку из config.json в spec для run_spec."""
    action = os.path.expandvars(action.strip())
    if "://" in action:
        return ("uri", action)
    return ("exe", action)


def open_url(url: str) -> None:
    log.info("Открываю ссылку: %s", url)
    webbrowser.open(url, new=2)


def open_browser() -> None:
    webbrowser.open("https://www.google.com", new=1)


def kill_process(image_name: str) -> bool:
    res = subprocess.run(
        ["taskkill", "/IM", image_name, "/F", "/T"],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    ok = res.returncode == 0
    log.info("taskkill %s -> %s", image_name, "ok" if ok else "не запущен")
    return ok


def close_browser() -> bool:
    return any([kill_process(p) for p in BROWSER_PROCS])


def take_screenshot() -> Path:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOTS_DIR / f"jarvis_{stamp}.png"
    img = ImageGrab.grab(all_screens=True)
    img.save(path)
    log.info("Скриншот: %s", path)
    return path


def google_search(query: str) -> None:
    open_url("https://www.google.com/search?q=" + query.replace(" ", "+"))
