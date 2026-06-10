"""Разбор команды (уже без wake-слова) и выбор действия."""

import datetime
import logging
import random
import re
import threading
import time
from difflib import SequenceMatcher

from jarvis import APP_NAME, __version__, actions
from jarvis.apps import find_app
from jarvis.installed import find_installed, scan_start_menu
from jarvis.steam import find_game, scan_steam_games

log = logging.getLogger("jarvis.intents")

# Основы глаголов: покрывают «открой/откройте/открыть/открою/откроет/запусти...»
# Whisper любит менять форму глагола, поэтому основы максимально короткие
OPEN_STEMS = ("откр", "запус", "включ", "вруб")
CLOSE_STEMS = ("закр", "выключ", "выруб", "заверш", "убей")


def _is_open_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in OPEN_STEMS)


def _is_close_verb(tok: str) -> bool:
    return any(tok.startswith(s) for s in CLOSE_STEMS)
FILLER = {"пожалуйста", "мне", "ка", "давай", "быстро", "срочно", "будь", "добр",
          # предлоги, союзы и огрызки распознавания — в цели команды они только мешают
          "в", "на", "и", "а", "но", "ну", "от", "до", "же", "бы", "то", "это", "там",
          # слова-классификаторы: «запусти игру доту», «открой приложение дискорд»
          "игру", "игра", "приложение", "программу", "программа"}
BROWSER_WORDS = {"браузер", "браузере", "браузером", "хром", "хроме", "интернет", "интернете"}
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
    """Движок с запросом в любом порядке: «открой на ютубе видео котиков»
    и «открой видео котят на ютубе» -> поиск на Ютубе. Работает на огрызках."""
    tokens = cmd.split()
    for i, tok in enumerate(tokens):
        engine = _engine_in(tok)
        if not engine:
            continue
        # запрос после движка: «... на ютубе видео котиков»
        query = " ".join(t for t in tokens[i + 1:] if t not in FILLER)
        if query:
            return (*engine, query)
        # запрос до движка: «... видео котят на ютубе»
        query = " ".join(
            t for t in tokens[:i]
            if t not in FILLER and not _is_open_verb(t) and not _is_close_verb(t)
        )
        if query:
            return (*engine, query)
    return None


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class IntentHandler:
    def __init__(self, config: dict, apps: list, brain=None):
        self.apps = apps
        self.brain = brain
        self.installed = scan_start_menu()
        self.steam_games = scan_steam_games()
        self.music_app = config.get("music_app", "яндекс музыка")
        self.music_wait = float(config.get("music_wait_sec", 6))
        self.last_file = None  # последний созданный файл — для «открой его»
        self.custom = []
        for entry in config.get("custom_commands", []):
            phrases = [normalize(p) for p in entry.get("phrases", []) if p.strip()]
            action = entry.get("action", "").strip() or entry.get("steps")
            if phrases and action:
                self.custom.append((phrases, action, entry.get("reply", "Выполняю.")))

    # --- цепочки: «сделай скриншот и открой его» -------------------------

    _CHAIN_SEP = re.compile(r"\s+(?:а\s+)?(?:и|потом|затем|после этого)\s+")
    _CHAIN_STARTERS = {"сделай", "сними", "найди", "поищи", "загугли", "погугли",
                       "скажи", "поставь", "переключи", "покажи"}

    def _split_chain(self, cmd: str) -> list[str]:
        parts = [p.strip() for p in self._CHAIN_SEP.split(cmd) if p.strip()]
        if len(parts) < 2:
            return [cmd]
        # делим, только если каждая следующая часть начинается с команды —
        # иначе «найди кошки и собаки» развалится на бессмыслицу
        for part in parts[1:]:
            first = part.split()[0]
            if not (_is_open_verb(first) or _is_close_verb(first)
                    or first in self._CHAIN_STARTERS or "скрин" in first):
                return [cmd]
        return parts

    def handle(self, cmd: str) -> str:
        """Принимает нормализованную команду, возвращает ответ для озвучки."""
        parts = self._split_chain(cmd)
        if len(parts) > 1:
            log.info("Цепочка из %d шагов: %s", len(parts), parts)
            replies = [self._handle_single(p) for p in parts]
            return " ".join(r for r in replies if r)
        return self._handle_single(cmd)

    def _handle_single(self, cmd: str) -> str:
        if cmd in CANCEL:
            return "Хорошо."

        reply = self._match_custom(cmd)
        if reply:
            return reply

        # Музыка и медиа-клавиши — до глаголов («включи музыку» это не open_app)
        reply = self._media(cmd)
        if reply:
            return reply

        if re.search(r"скрин|снимок экрана", cmd):
            tokens_ = cmd.split()
            if any(_is_open_verb(t) or t == "покажи" for t in tokens_):
                # «открой скриншот / открой его» — показать последний
                return self._open_last_file()
            path = actions.take_screenshot()
            self.last_file = path
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

        # Правила не справились — спрашиваем локальную нейронку
        if self.brain is not None:
            intent = self.brain.parse(cmd)
            if intent:
                if isinstance(intent.get("steps"), list):
                    reply = self._execute_steps(intent["steps"])
                else:
                    reply = self._execute_intent(intent)
                if reply:
                    return reply
        return "Я не понял команду. Скажите, например: открой стим."

    def _execute_steps(self, steps: list) -> str | None:
        """Выполняет цепочку шагов (от LLM или из custom_commands)."""
        reply = None
        for step in steps[:6]:
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            if action == "wait":
                time.sleep(min(float(step.get("seconds", 1) or 1), 15))
                continue
            if action == "media_key":
                actions.media_key(str(step.get("key", "")), int(step.get("times", 1) or 1))
                continue
            r = self._execute_intent(step)
            if r:
                reply = r
        return reply

    def _execute_intent(self, intent: dict) -> str | None:
        """Выполняет интент от LLM средствами обычного пайплайна."""
        action = intent.get("action")
        target = normalize(str(intent.get("target") or ""))
        query = str(intent.get("query") or "").strip()
        if action == "open_app" and target:
            if intent.get("minimized"):
                hit = find_installed(self.installed, target)
                if hit:
                    actions.open_path(hit[1], minimized=True)
                    return f"Открываю {hit[0]}."
            return self._do_open(target)
        if action == "open_file":
            return self._open_last_file()
        if action == "close_app" and target:
            return self._do_close(target)
        if action == "open_site" and (target or query):
            site = target or query
            if "." in (intent.get("target") or ""):  # LLM знает домен: pornhub.com
                actions.open_url("https://" + str(intent["target"]).strip().lower())
                return f"Открываю {site}."
            return self._open_site(site)
        if action == "search" and (query or target):
            engine = intent.get("engine") if intent.get("engine") in ("google", "youtube", "wiki") else "google"
            q = query or target
            actions.open_search(engine, q)
            return f"Ищу: {q}."
        if action == "screenshot":
            path = actions.take_screenshot()
            self.last_file = path
            return f"Скриншот сохранён в папку {path.parent.name}."
        if action == "answer" and intent.get("reply"):
            return str(intent["reply"])[:300]
        return None

    # --- внутренности -------------------------------------------------

    def _match_custom(self, cmd: str) -> str | None:
        for phrases, action, reply in self.custom:
            for phrase in phrases:
                if cmd == phrase or SequenceMatcher(None, cmd, phrase).ratio() >= 0.85:
                    if isinstance(action, list):  # цепочка шагов из конфига
                        return self._execute_steps(action) or reply
                    actions.run_spec(actions.spec_from_string(action))
                    return reply
        return None

    # --- музыка и медиа ---------------------------------------------------

    def _media(self, cmd: str) -> str | None:
        if re.search(r"(включ|вруб|постав|запуст|игра)\w*\s.*музык", cmd) or \
                re.search(r"включ\w*\s+(мою\s+)?волну", cmd):
            return self._music_on()
        if re.search(r"(выключ|выруб|останов|стоп)\w*\s.*музык", cmd):
            actions.media_key("play")  # toggle: ставит на паузу
            return "Ставлю на паузу."
        if re.search(r"^(пауза|на паузу|постав\w* на паузу|продолж\w*|плей)$", cmd):
            actions.media_key("play")
            return "Готово."
        if re.search(r"(следующ|дальше|некст)", cmd) and re.search(r"трек|песн|музык|дальше", cmd):
            actions.media_key("next")
            return "Переключаю."
        if re.search(r"предыдущ\w*\s+(трек|песн)", cmd):
            actions.media_key("prev")
            return "Возвращаю."
        if re.search(r"^(сделай\s+)?(по)?громче$", cmd) or "громкость выше" in cmd:
            actions.media_key("vol_up", 5)
            return "Громче."
        if re.search(r"^(сделай\s+)?(по)?тише$", cmd) or "громкость ниже" in cmd:
            actions.media_key("vol_down", 5)
            return "Тише."
        if re.search(r"без звука|отключи звук|мьют", cmd):
            actions.media_key("mute")
            return "Без звука."
        return None

    def _music_on(self) -> str:
        hit = find_installed(self.installed, self.music_app)
        if hit:
            name, lnk = hit
            actions.open_path(lnk, minimized=True)
            # даём плееру запуститься и жмём play — обычно стартует «Моя волна»
            threading.Timer(self.music_wait, actions.media_key, args=("play",)).start()
            return "Включаю музыку."
        actions.open_url("https://music.yandex.ru/personal/my-wave")
        return "Плеер не найден, открываю Мою волну в браузере."

    def _open_last_file(self) -> str:
        if self.last_file:
            actions.open_path(self.last_file)
            return "Открываю."
        return "Пока нечего открывать."

    def _do_open(self, target: str) -> str:
        if not target:
            return "Что именно открыть?"

        # «сделай скриншот и открой его» — местоимения указывают на последний файл
        if target in {"его", "ее", "это", "этот файл", "файл", "последний файл"}:
            return self._open_last_file()

        # «открой в браузере порнхаб» — браузер + сайт; голый «браузер» — просто браузер
        tokens = target.split()
        rest = [t for t in tokens if t not in BROWSER_WORDS]
        if len(rest) < len(tokens):
            if not rest:
                actions.open_browser()
                return "Открываю браузер."
            return self._open_site(" ".join(rest))

        # «открой сайт хабр» / «открой ссылку на ютуб» — явная просьба про сайт
        site_only = bool(re.match(r"^(сайт|ссылк|страниц)", target))
        site_target = re.sub(r"^(сайт\w*|ссылку|ссылка|страницу)\s*(на)?\s*", "", target).strip() or target
        if site_only:
            return self._open_site(site_target)

        # 1. Встроенный каталог (стим, дискорд, дота...)
        app = find_app(self.apps, target)
        if app:
            spec = app.resolve_open()
            if spec is None:
                return f"{app.title} не найден на этом компьютере. Укажите путь в конфиге."
            actions.run_spec(spec)
            return f"Открываю {app.title}."

        # 2. Известные сайты
        for key, (title, url) in SITES.items():
            if key in target.split() or target == key:
                actions.open_url(url)
                return f"Открываю {title}."

        # 3. Игры из библиотеки Steam («запусти сабнатику»)
        game = find_game(self.steam_games, target)
        if game:
            title, appid = game
            actions.run_spec(("uri", f"steam://rungameid/{appid}"))
            return f"Запускаю {title}."

        # 4. Любая установленная программа из меню «Пуск» («открой обс»)
        hit = find_installed(self.installed, target)
        if hit:
            name, lnk = hit
            actions.open_path(lnk)
            return f"Открываю {name}."

        # 5. Не нашли на компьютере — пробуем как сайт
        return self._open_site(target)

    def _open_site(self, name: str) -> str:
        if not name:
            return "Какой сайт открыть?"
        for key, (title, url) in SITES.items():
            if name == key or key in name.split():
                actions.open_url(url)
                return f"Открываю {title}."
        # продиктованный домен («хабр точка ру») или DNS-угадывание
        url = actions.spoken_domain(name) or actions.guess_site(name)
        if url:
            actions.open_url(url)
            return f"Открываю сайт {name}."
        # универсальный путь: DuckDuckGo «мне повезёт» — первый результат
        if len(name.split()) <= 3:
            actions.open_site_lucky(name)
            return f"Открываю {name}."
        actions.google_search(name)
        return f"Ищу {name}."

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
            return f"Я {APP_NAME}, локальный голосовой ассистент, версия {__version__}."
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
