"""Разбор команды (уже без wake-слова) и выбор действия."""

import datetime
import logging
import random
import re
from difflib import SequenceMatcher

from jarvis import __version__, actions
from jarvis.apps import find_app
from jarvis.installed import find_installed, scan_start_menu

log = logging.getLogger("jarvis.intents")

# Основы глаголов: покрывают «открой/откройте/открыть/запусти/запустите...»
OPEN_STEMS = ("открой", "открыт", "запуст", "включ", "вруб")
CLOSE_STEMS = ("закрой", "закрыт", "выключ", "выруб", "заверш", "убей")


def _is_open_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in OPEN_STEMS)


def _is_close_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in CLOSE_STEMS)
FILLER = {"пожалуйста", "мне", "ка", "давай", "быстро", "срочно", "будь", "добр",
          # предлоги, союзы и огрызки распознавания — в цели команды они только мешают
          "в", "на", "и", "а", "но", "ну", "от", "до", "же", "бы", "то", "это", "там"}
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

# Поисковые движки: основа слова -> (ключ движка, как сказать в ответе)
ENGINES = {
    "ютуб": ("youtube", "на Ютубе"),
    "youtube": ("youtube", "на Ютубе"),
    "википеди": ("wiki", "в Википедии"),
    "вики": ("wiki", "в Википедии"),
    "гугл": ("google", "в Гугле"),
    "интернет": ("google", "в интернете"),
}


def _engine_in(text: str):
    for stem, val in ENGINES.items():
        if stem in text:
            return val
    return None


def parse_search(cmd: str):
    """(движок, 'где сказать', запрос) или None.

    Понимает: «найди котиков», «поищи на ютубе котиков», «найди котиков в ютубе»,
    «загугли погоду», «открой гугл с поиском погода», «открой ютуб с поиском лофи».
    """
    m = re.search(r"\bпоиск\w*\s+(.+)$", cmd)
    if m:
        engine = _engine_in(cmd[:m.start()]) or ENGINES["гугл"]
        return (*engine, m.group(1).strip())

    m = re.match(r"^(?:найди|поищи|ищи|загугли|погугли)\s+(.+)$", cmd)
    if not m:
        return None
    rest = m.group(1).strip()
    m2 = re.match(r"^(?:в|на)\s+(\S+)\s+(.+)$", rest)
    if m2 and _engine_in(m2.group(1)):
        return (*_engine_in(m2.group(1)), m2.group(2).strip())
    m3 = re.match(r"^(.+?)\s+(?:в|на)\s+(\S+)$", rest)
    if m3 and _engine_in(m3.group(2)):
        return (*_engine_in(m3.group(2)), m3.group(1).strip())
    return (*ENGINES["гугл"], rest)


def parse_engine_tail(cmd: str):
    """Движок в середине фразы с хвостом-запросом: «открой на ютубе видео котиков»
    -> поиск на Ютубе «видео котиков». Срабатывает даже на огрызках распознавания."""
    tokens = cmd.split()
    for i, tok in enumerate(tokens):
        engine = _engine_in(tok)
        if engine and i + 1 < len(tokens):
            query = " ".join(t for t in tokens[i + 1:] if t not in FILLER)
            if query:
                return (*engine, query)
    return None


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class IntentHandler:
    def __init__(self, config: dict, apps: list):
        self.apps = apps
        self.installed = scan_start_menu()
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

        # Поиск с запросом — раньше глаголов, чтобы сработало
        # «открой гугл с поиском погода» и «найди на ютубе лофи»
        search = parse_search(cmd) or parse_engine_tail(cmd)
        if search:
            engine, where, query = search
            actions.open_search(engine, query)
            return f"Ищу {where}: {query}."

        tokens = [t for t in cmd.split() if t not in FILLER]
        verb_open = any(_is_open_verb(t) for t in tokens)
        verb_close = any(_is_close_verb(t) for t in tokens)
        target = " ".join(t for t in tokens if not _is_open_verb(t) and not _is_close_verb(t))

        if verb_open:
            return self._do_open(target)
        if verb_close:
            return self._do_close(target)

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

        # «открой сайт хабр» / «открой ссылку на ютуб» — явная просьба про сайт
        site_only = bool(re.match(r"^(сайт|ссылк|страниц)", target))
        site_target = re.sub(r"^(сайт|ссылку|ссылка|страницу)\s*(на)?\s*", "", target).strip() or target

        # 1. Встроенный каталог (стим, дискорд, дота...)
        if not site_only:
            app = find_app(self.apps, target)
            if app:
                spec = app.resolve_open()
                if spec is None:
                    return f"{app.title} не найден на этом компьютере. Укажите путь в конфиге."
                actions.run_spec(spec)
                return f"Открываю {app.title}."

        # 2. Известные сайты
        for key, (title, url) in SITES.items():
            if key in site_target.split() or site_target == key:
                actions.open_url(url)
                return f"Открываю {title}."

        # 3. Любая установленная программа из меню «Пуск» («открой обс»)
        if not site_only:
            hit = find_installed(self.installed, target)
            if hit:
                name, lnk = hit
                actions.open_path(lnk)
                return f"Открываю {name}."

        # 4. Продиктованный домен («хабр точка ру») или угадывание сайта по DNS
        url = actions.spoken_domain(site_target) or actions.guess_site(site_target)
        if url:
            actions.open_url(url)
            return f"Открываю сайт {site_target}."

        # 5. Последний шанс — поиск
        actions.google_search(target)
        return f"Не нашёл {target} на компьютере. Открываю поиск."

    def _do_close(self, target: str) -> str:
        if not target:
            return "Что именно закрыть?"
        if any(w in target for w in ("браузер", "интернет", "хром")):
            return "Закрываю браузер." if actions.close_browser() else "Браузер не запущен."
        app = find_app(self.apps, target)
        if app and app.procs:
            ok = any([actions.kill_process(p) for p in app.procs])
            if ok:
                return f"Закрываю {app.title}."
        # Любой запущенный процесс, похожий на сказанное
        exe = actions.find_process(target)
        if exe:
            actions.kill_process(exe)
            return f"Закрываю {exe.removesuffix('.exe')}."
        if app:
            return f"{app.title} сейчас не запущен."
        return f"Не нашёл запущенной программы {target}."

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
