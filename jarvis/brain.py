"""LLM-фолбэк: локальная нейронка (Ollama) разбирает команду в структурный интент.

Архитектура двухслойная: быстрые правила (intents.py) обрабатывают типовые
команды за миллисекунды; если они не справились — фраза уходит маленькой LLM
(Qwen2.5 1.5B, ~1 ГБ VRAM, ~0.3 с на разбор после прогрева).
"""

import json
import logging
import subprocess
import threading
import time
import urllib.request

log = logging.getLogger("jarvis.brain")

SYSTEM = """Ты разбираешь команды голосового ассистента на Windows. Отвечай ТОЛЬКО JSON.
Действия: open_app (открыть программу или игру), close_app (закрыть), open_site (открыть сайт), search (поиск в интернете), screenshot, answer (короткий ответ на вопрос), none (бессмыслица).
Поля: action; target — название программы или домен сайта; query — поисковый запрос; engine — google|youtube|wiki; reply — ответ для answer.
Примеры:
открой стим -> {"action":"open_app","target":"стим"}
запусти сабнатику -> {"action":"open_app","target":"сабнатика"}
выключи музыку -> {"action":"close_app","target":"музыка"}
открой порно хаб -> {"action":"open_site","target":"pornhub.com"}
найди на ютубе котиков -> {"action":"search","engine":"youtube","query":"котики"}
что такое чёрная дыра -> {"action":"search","engine":"google","query":"что такое чёрная дыра"}
сколько будет два плюс два -> {"action":"answer","reply":"Четыре"}"""

ACTIONS = {"open_app", "close_app", "open_site", "search", "screenshot", "answer", "none"}


class Brain:
    def __init__(self, model: str = "qwen2.5:1.5b-instruct",
                 url: str = "http://127.0.0.1:11434", timeout: float = 20.0):
        self.model = model
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.available = self._ping() or self._try_start()
        if self.available:
            log.info("LLM-фолбэк включён: %s через Ollama", model)
            threading.Thread(target=self._warmup, daemon=True, name="brain-warmup").start()
        else:
            log.warning("Ollama недоступна — LLM-фолбэк выключен (установка: winget install Ollama.Ollama)")

    def _ping(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/version", timeout=2):
                return True
        except OSError:
            return False

    def _try_start(self) -> bool:
        """Ollama не отвечает — пробуем поднять сервис самостоятельно."""
        try:
            subprocess.Popen(["ollama", "serve"], creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        for _ in range(10):
            time.sleep(0.5)
            if self._ping():
                return True
        return False

    def _chat(self, cmd: str, timeout: float):
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": cmd}],
            "stream": False,
            "format": "json",
            "keep_alive": -1,  # держим модель в VRAM, иначе каждый раз ~десятки секунд загрузки
            "options": {"temperature": 0, "num_predict": 120},
        }).encode()
        req = urllib.request.Request(self.url + "/api/chat", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["message"]["content"]

    def _warmup(self) -> None:
        try:
            t0 = time.time()
            self._chat("привет", timeout=120)
            log.info("LLM прогрета за %.1f с", time.time() - t0)
        except Exception:
            log.exception("Прогрев LLM не удался")
            self.available = False

    def parse(self, cmd: str) -> dict | None:
        """Интент {'action': ..., ...} или None, если LLM недоступна/невалидна."""
        if not self.available:
            return None
        try:
            t0 = time.time()
            raw = self._chat(cmd, timeout=self.timeout)
            intent = json.loads(raw)
            log.info("LLM (%.2f с): %r -> %s", time.time() - t0, cmd,
                     json.dumps(intent, ensure_ascii=False))
        except Exception:
            log.exception("LLM не справилась с %r", cmd)
            return None
        if not isinstance(intent, dict) or intent.get("action") not in ACTIONS:
            return None
        return intent
