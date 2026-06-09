"""Каталог известных приложений: как их зовут голосом, как открыть и как закрыть."""

import logging
import os
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.matching import match_score

log = logging.getLogger("jarvis.apps")


@dataclass
class App:
    key: str
    title: str          # как назвать в ответе («Открываю Дискорд»)
    aliases: list       # как пользователь может назвать приложение
    open_specs: list    # кандидаты ("uri"|"exe"|"cmd", значение) — берётся первый рабочий
    procs: list = field(default_factory=list)  # имена процессов для «закрой»

    def resolve_open(self):
        for kind, value in self.open_specs:
            if kind == "exe":
                if Path(value).exists():
                    return ("exe", value)
            else:
                return (kind, value)
        return None


def _steam_exe() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamExe")[0]
    except OSError:
        return None


def _expand(p: str) -> str:
    return os.path.expandvars(p)


def build_apps(config: dict) -> list[App]:
    steam = _steam_exe() or r"C:\Program Files (x86)\Steam\steam.exe"
    discord_updater = _expand(r"%LOCALAPPDATA%\Discord\Update.exe")

    apps = [
        App(
            "discord", "Дискорд",
            ["дискорд", "дис", "дс", "дэ эс", "discord"],
            [("cmd", [discord_updater, "--processStart", "Discord.exe"])],
            ["Discord.exe"],
        ),
        App(
            "telegram", "Телеграм",
            ["телеграм", "телеграмм", "телега", "тг", "тэ гэ", "telegram"],
            [("exe", _expand(r"%APPDATA%\Telegram Desktop\Telegram.exe"))],
            ["Telegram.exe"],
        ),
        App(
            "steam", "Стим",
            ["стим", "steam"],
            [("exe", steam)],
            ["steam.exe"],
        ),
        App(
            "dota2", "Дота два",
            ["дота", "дота два", "доту", "дотан", "dota"],
            [("uri", "steam://rungameid/570")],
            ["dota2.exe"],
        ),
        App(
            "claude", "Клод Десктоп",
            ["клод", "клауд", "клод десктоп", "клауд десктоп", "claude"],
            [("exe", _expand(r"%LOCALAPPDATA%\AnthropicClaude\claude.exe"))],
            ["claude.exe"],
        ),
        App("calc", "Калькулятор", ["калькулятор"], [("uri", "calc:")], ["CalculatorApp.exe", "Calculator.exe"]),
        App("notepad", "Блокнот", ["блокнот"], [("cmd", ["notepad.exe"])], ["notepad.exe", "Notepad.exe"]),
        App("explorer", "Проводник", ["проводник", "папку", "файлы"], [("cmd", ["explorer.exe"])]),
        App("paint", "Пэйнт", ["пэйнт", "паинт", "пейнт", "рисовалку"], [("cmd", ["mspaint.exe"])], ["mspaint.exe"]),
        App("taskmgr", "Диспетчер задач", ["диспетчер задач", "диспетчер"], [("cmd", ["taskmgr.exe"])], ["Taskmgr.exe"]),
    ]

    # Переопределение путей из config.json: "app_paths": {"discord": "C:\\...\\Discord.exe"}
    overrides = config.get("app_paths") or {}
    for app in apps:
        if app.key in overrides:
            app.open_specs = [("exe", _expand(overrides[app.key]))]
    return apps


def find_app(apps: list[App], target: str) -> App | None:
    """Лучшее совпадение цели с псевдонимами приложений (точное/вхождение/нечёткое)."""
    best, best_score = None, 0.0
    for app in apps:
        for alias in app.aliases:
            if target == alias:
                return app
            score = match_score(target, alias)
            if score > best_score:
                best, best_score = app, score
    if best_score >= 0.75:
        log.info("Цель %r -> %s (score %.2f)", target, best.key, best_score)
        return best
    log.info("Цель %r не сопоставлена (лучший score %.2f)", target, best_score)
    return None
