"""Низкоуровневые действия: запуск, завершение процессов, скриншоты, ссылки."""

import datetime
import logging
import os
import re
import socket
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from PIL import ImageGrab

from jarvis.matching import match_score, translit

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


SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "wiki": "https://ru.wikipedia.org/w/index.php?search={}",
}


def open_search(engine: str, query: str) -> None:
    open_url(SEARCH_URLS.get(engine, SEARCH_URLS["google"]).format(quote_plus(query)))


def open_site_lucky(name: str) -> None:
    """Открывает сайт по названию через DuckDuckGo «мне повезёт» (редирект
    на первый результат). Работает для любого сайта и не зависит от DNS."""
    open_url("https://duckduckgo.com/?q=" + quote_plus("\\" + name))


def google_search(query: str) -> None:
    open_search("google", query)


def open_path(path) -> None:
    log.info("Открываю: %s", path)
    os.startfile(path)


# --- произвольные сайты ---------------------------------------------------

_TLD_WORDS = {"ру": "ru", "ком": "com", "орг": "org", "нет": "net",
              "ио": "io", "рф": "xn--p1ai", "точка": ""}


def spoken_domain(spoken: str) -> str | None:
    """«хабр точка ру» -> https://habr.ru (домен, продиктованный через «точка»)."""
    if "точка" not in spoken:
        return None
    parts = [p.strip() for p in spoken.split("точка") if p.strip()]
    if len(parts) < 2:
        return None
    tld = _TLD_WORDS.get(parts[-1], translit(parts[-1].replace(" ", "")))
    host = ".".join(translit(p.replace(" ", "")) for p in parts[:-1]) + "." + tld
    if re.fullmatch(r"[a-z0-9.\-]+\.[a-z0-9\-]{2,}", host):
        return "https://" + host
    return None


_dns_trust: bool | None = None


def _dns_trustworthy() -> bool:
    """Паркинг/провайдерский DNS «резолвит» любую абракадабру — тогда
    угадывать домены по DNS бессмысленно и опасно. Проверяем один раз."""
    global _dns_trust
    if _dns_trust is None:
        import random
        import string

        junk = "".join(random.choices(string.ascii_lowercase, k=16))
        _dns_trust = True
        for tld in (".ru", ".com"):
            try:
                socket.getaddrinfo(junk + tld, 443)
                log.warning("DNS отвечает на мусорный домен %s — угадывание сайтов отключено", junk + tld)
                _dns_trust = False
                break
            except OSError:
                continue
    return _dns_trust


def guess_site(spoken: str) -> str | None:
    """Пробует превратить «хабр» в живой домен: habr.ru / habr.com / ...

    Только короткие цели: длинная фраза — это почти наверняка ошибка
    распознавания, а паркинг-DNS «отвечает» на любую абракадабру.
    """
    if len(spoken.split()) > 2:
        return None
    base = translit(spoken.replace(" ", "").replace("-", ""))
    if not re.fullmatch(r"[a-z0-9]{2,14}", base):
        return None
    if not _dns_trustworthy():
        return None
    for tld in (".ru", ".com", ".net", ".org", ".io"):
        host = base + tld
        try:
            socket.getaddrinfo(host, 443)
            log.info("Сайт угадан: %r -> %s", spoken, host)
            return "https://" + host
        except OSError:
            continue
    return None


# --- закрытие произвольных программ ----------------------------------------

# Эти процессы нельзя убивать ни при каком совпадении
_KILL_BLACKLIST = {"system", "svchost", "csrss", "winlogon", "wininit", "services",
                   "lsass", "dwm", "smss", "fontdrvhost", "registry", "idle",
                   "explorer", "python", "pythonw", "conhost", "audiodg"}


def list_processes() -> set[str]:
    res = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, encoding="cp866",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    names = set()
    for line in res.stdout.splitlines():
        if line.startswith('"'):
            names.add(line.split('","')[0].strip('"'))
    return names


def find_process(target: str, threshold: float = 0.8) -> str | None:
    """Имя exe запущенного процесса, лучше всего похожего на сказанное."""
    best_exe, best_score = None, 0.0
    for exe in list_processes():
        raw = exe.removesuffix(".exe").removesuffix(".EXE")
        base = raw.lower()
        if base in _KILL_BLACKLIST:
            continue
        clean = re.sub(r"\d+$", "", base)  # obs64 -> obs
        # RobloxPlayerInstaller -> roblox player installer
        spaced = re.sub(r"(?<=[a-zа-я0-9])(?=[A-ZА-Я])", " ", raw).lower()
        score = max(match_score(target, base), match_score(target, clean),
                    match_score(target, spaced))
        if score > best_score:
            best_exe, best_score = exe, score
    if best_score >= threshold:
        log.info("Процесс: %r -> %s (score %.2f)", target, best_exe, best_score)
        return best_exe
    log.info("Процесс для %r не найден (лучший score %.2f, %r)", target, best_score, best_exe)
    return None
