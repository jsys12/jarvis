"""Разбор команды (уже без wake-слова) и выбор действия."""

import datetime
import logging
import random
import re
from difflib import SequenceMatcher

from jarvis import __version__, actions
from jarvis.apps import find_app

log = logging.getLogger("jarvis.intents")

# Основы глаголов: покрывают «открой/откройте/открыть/запусти/запустите...»
OPEN_STEMS = ("открой", "открыт", "запуст", "включ", "вруб")
CLOSE_STEMS = ("закрой", "закрыт", "выключ", "выруб", "заверш", "убей")


def _is_open_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in OPEN_STEMS)


def _is_close_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in CLOSE_STEMS)
FILLER = {"пожалуйста", "мне", "ка", "давай", "быстро", "срочно", "будь", "добр"}
CANCEL = {"отмена", "стоп", "ничего", "забудь", "отбой"}

SITES = {
    "ютуб": ("Ютуб", "https://www.youtube.com"),
    "гугл": ("Гугл", "https://www.google.com"),
    "яндекс": ("Яндекс", "https://ya.ru"),
    "гитхаб": ("Гитхаб", "https://github.com"),
    "вк": ("ВКонтакте", "https://vk.com"),
    "вконтакте": ("ВКонтакте", "https://vk.com"),
    "твич": ("Твич", "https://www.twitch.tv"),
    "кинопоиск": ("Кинопоиск", "https://www.kinopoisk.ru"),
    "википедия": ("Википедию", "https://ru.wikipedia.org"),
    "почта": ("Почту", "https://mail.google.com"),
}

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class IntentHandler:
    def __init__(self, config: dict, apps: list):
        self.apps = apps
        self.custom = []
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip()
            if phrases and action:
                self.custom.append((phrases, action, entry.get("reply", "Выполняю.")))

    def handle(self, cmd: str) -> str:
        """Принимает нормализованную команду, возвращает ответ для озвучки."""
        if cmd in CANCEL:
            return "Хорошо."

        reply = self._match_custom(cmd)
        if reply:
            return reply

        if any(w in cmd for w in ("скриншот", "скрин", "снимок экрана")):
            path = actions.take_screenshot()
            return f"Скриншот сохранён в папку {path.parent.name}."

        tokens = [t for t in cmd.split() if t not in FILLER]
        verb_open = any(_is_open_verb(t) for t in tokens)
        verb_close = any(_is_close_verb(t) for t in tokens)
        target = " ".join(t for t in tokens if not _is_open_verb(t) and not _is_close_verb(t))

        if verb_open:
            return self._do_open(target)
        if verb_close:
            return self._do_close(target)

        for prefix in ("найди", "поищи", "загугли", "погугли"):
            if cmd.startswith(prefix) and len(cmd) > len(prefix) + 1:
                query = cmd[len(prefix):].strip()
                actions.google_search(query)
                return f"Ищу: {query}."

        reply = self._small_talk(cmd)
        if reply:
            return reply
        return "Я не понял команду. Скажите, например: открой стим."

    # --- внутренности -------------------------------------------------

    def _match_custom(self, cmd: str) -> str | None:
        for phrases, action, reply in self.custom:
            for phrase in phrases:
                if cmd == phrase or SequenceMatcher(None, cmd, phrase).ratio() >= 0.85:
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
        return None

    def _do_open(self, target: str) -> str:
        if not target:
            return "Что именно открыть?"
        if any(w in target for w in ("браузер", "интернет", "хром")):
            actions.open_browser()
            return "Открываю браузер."

        # «открой сайт ютуб» / «открой ссылку на ютуб»
        site_target = re.sub(r"^(сайт|ссылку|ссылка|страницу)\s*(на)?\s*", "", target)
        app = find_app(self.apps, target)
        if app:
            spec = app.resolve_open()
            if spec is None:
                return f"{app.title} не найден на этом компьютере. Укажите путь в конфиге."
            actions.run_spec(spec)
            return f"Открываю {app.title}."
        for key, (title, url) in SITES.items():
            if key in site_target.split() or site_target == key:
                actions.open_url(url)
                return f"Открываю {title}."
        return f"Я не знаю, как открыть {target}. Добавьте команду в конфиг."

    def _do_close(self, target: str) -> str:
        if not target:
            return "Что именно закрыть?"
        if any(w in target for w in ("браузер", "интернет", "хром")):
            return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."
        app = find_app(self.apps, target)
        if app and app.procs:
            ok = any([actions.kill_process(p) for p in app.procs])
            return f"Закрываю {app.title}." if ok else f"{app.title} сейчас не запущен."
        return f"Я не знаю, как закрыть {target}."

    def _small_talk(self, cmd: str) -> str | None:
        now = datetime.datetime.now()
        if any(p in cmd for p in ("который час", "сколько времени", "время")):
            return f"Сейчас {now.hour} {_hours(now.hour)} {now.minute} {_minutes(now.minute)}."
        if any(p in cmd for p in ("какое число", "какая дата", "какое сегодня число", "дата")):
            return f"Сегодня {now.day} {MONTHS[now.month - 1]} {now.year} года, {WEEKDAYS[now.weekday()]}."
        if "день недели" in cmd or cmd == "какой сегодня день":
            return f"Сегодня {WEEKDAYS[now.weekday()]}."
        if any(p in cmd for p in ("как дела", "как ты", "как настроение")):
            return random.choice([
                "Все системы функционируют нормально.",
                "Отлично, сэр. Готов к работе.",
                "В полном порядке, спасибо.",
            ])
        if any(p in cmd for p in ("кто ты", "ты кто", "представься", "как тебя зовут")):
            return f"Я Джарвис, локальный голосовой ассистент, версия {__version__}."
        if any(p in cmd for p in ("что ты умеешь", "помощь", "что умеешь", "команды")):
            return ("Я умею открывать и закрывать приложения и сайты, делать скриншоты, "
                    "искать в интернете и отвечать на простые вопросы. "
                    "Свои команды можно добавить в конфиг.")
        if any(p in cmd for p in ("спасибо", "благодарю")):
            return "Всегда пожалуйста."
        if any(p in cmd for p in ("привет", "здравствуй", "добрый день", "доброе утро", "добрый вечер")):
            return "Привет! Чем могу помочь?"
        if any(p in cmd for p in ("пока", "до свидания", "спокойной ночи")):
            return "До связи."
        return None


def _hours(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "час"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "часа"
    return "часов"


def _minutes(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "минуты"
    return "минут"
