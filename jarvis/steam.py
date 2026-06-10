"""Индекс установленных игр Steam: appmanifest -> (название, appid).

Позволяет «запусти сабнатику» для любой игры из библиотеки,
запуск через steam://rungameid/{appid}.
"""

import logging
import re
import winreg
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.steam")

# Служебные «игры», которые запускать не надо
_SKIP = ("redistributable", "proton", "steamworks", "steam linux", "runtime")


def _steam_root() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None


def scan_steam_games() -> list[tuple[str, str]]:
    """[(название, appid), ...] по всем библиотекам Steam."""
    root = _steam_root()
    if root is None or not root.exists():
        return []
    libs = {root}
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for path in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8", errors="ignore")):
            libs.add(Path(path.replace("\\\\", "\\")))
    games = []
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                text = acf.read_text("utf-8", errors="ignore")
            except OSError:
                continue
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            if not appid or not name:
                continue
            title = name.group(1)
            if any(s in title.lower() for s in _SKIP):
                continue
            games.append((title, appid.group(1)))
    log.info("Steam: проиндексировано %d игр", len(games))
    return games


def find_game(games: list[tuple[str, str]], spoken: str,
              threshold: float = 0.72) -> tuple[str, str] | None:
    best, best_score = None, 0.0
    for title, appid in games:
        score = match_score(spoken, title)
        if score > best_score:
            best, best_score = (title, appid), score
    if best and best_score >= threshold:
        log.info("Игра Steam: %r -> %r (score %.2f)", spoken, best[0], best_score)
        return best
    return None
