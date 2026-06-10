"""Точка входа: связывает распознавание, интенты, синтез речи и трей."""

import logging
import threading
import time
from pathlib import Path

from jarvis.matching import match_score

from jarvis import APP_NAME, __version__
from jarvis.apps import build_apps
from jarvis.config import load_config
from jarvis.intents import IntentHandler, normalize
from jarvis.model import ensure_model
from jarvis.stt import Listener
from jarvis.tray import build_tray
from jarvis.tts import Speaker

log = logging.getLogger("jarvis")

BASE_DIR = Path(__file__).resolve().parent.parent


class Jarvis:
    def __init__(self, config: dict, listener: Listener, speaker: Speaker,
                 handler: IntentHandler, base_dir: Path, whisper=None):
        self.config = config
        self.listener = listener
        self.speaker = speaker
        self.handler = handler
        self.base_dir = base_dir
        self.whisper = whisper
        self.listening_enabled = True
        self.stop_event = threading.Event()
        self._awaiting_until = 0.0
        self._wake_words = [normalize(w) for w in config["wake_words"]]

    def say(self, text: str) -> None:
        if not text:
            return
        self.listener.muted = True
        try:
            self.speaker.speak(text)
        finally:
            self.listener.flush()
            self.listener.muted = False

    def shutdown(self) -> None:
        self.stop_event.set()

    def run_loop(self) -> None:
        try:
            for phrase, audio in self.listener.phrases(self.stop_event):
                if not self.listening_enabled:
                    continue
                try:
                    self._process(phrase, audio)
                except Exception:
                    log.exception("Ошибка обработки фразы %r", phrase)
        except Exception:
            log.exception("Аудиопоток упал")
            self.say("Проблема с микрофоном. Проверьте журнал.")

    def _process(self, phrase: str, audio: bytes) -> None:
        awaiting = time.time() < self._awaiting_until
        cmd = self._extract_command(normalize(phrase))
        if cmd is None:
            return  # обращались не к нам
        if cmd == "":
            # Просто «Джарвис» — ждём команду следующей фразой
            self.say("Слушаю.")
            self._awaiting_until = time.time() + self.config["command_window_sec"]
            return
        # Vosk разбудил — точную расшифровку команды даёт Whisper
        if self.whisper is not None and audio:
            refined = self._refine(audio, awaiting)
            if refined:
                cmd = refined
        self._awaiting_until = 0.0
        self.say(self.handler.handle(cmd))

    def _refine(self, audio: bytes, awaiting: bool) -> str | None:
        """Пере-распознаёт фразу Whisper'ом и убирает из неё wake-слово."""
        try:
            text = normalize(self.whisper.transcribe(audio))
        except Exception:
            log.exception("Whisper не справился, использую текст Vosk")
            return None
        if not text:
            return None
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if awaiting:
            return text  # окно после «Слушаю» — wake-слова и не должно быть
        # Vosk слышал wake-слово, а Whisper расслышал его иначе —
        # отбрасываем первый токен, если он похож на огрызок имени
        if tokens and match_score(tokens[0], self._wake_words[0]) >= 0.5:
            return " ".join(tokens[1:])
        return text

    def _extract_command(self, text: str) -> str | None:
        """Команда после wake-слова, '' если только wake-слово, None если его нет."""
        tokens = text.split()
        for i, tok in enumerate(tokens):
            if self._is_wake(tok):
                return " ".join(tokens[i + 1:])
        if time.time() < self._awaiting_until:
            return text  # окно после «Слушаю» — wake-слово не нужно
        return None

    def _is_wake(self, token: str) -> bool:
        # match_score транслитерирует: ловит и «джарвиз», и латинское «jarvis»
        return token in self._wake_words or any(
            match_score(token, w) >= 0.8 for w in self._wake_words
        )


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(BASE_DIR / "jarvis.log", encoding="utf-8"),
        ],
    )


def main() -> None:
    setup_logging()
    log.info("%s v%s запускается", APP_NAME, __version__)

    config = load_config(BASE_DIR)
    model_dir = ensure_model(BASE_DIR / "models")

    # Whisper грузим строго до первого использования WinRT (см. WhisperTranscriber)
    whisper = None
    if config.get("use_whisper", True):
        try:
            from jarvis.stt import WhisperTranscriber

            whisper = WhisperTranscriber(
                config.get("whisper_model", "auto"), config.get("whisper_device", "auto")
            )
        except Exception:
            log.exception("Whisper не завёлся, работаю только на Vosk")

    speaker = Speaker(config["voice"])
    listener = Listener(model_dir, config["sample_rate"], config.get("input_device"))
    handler = IntentHandler(config, build_apps(config))
    jarvis = Jarvis(config, listener, speaker, handler, BASE_DIR, whisper)

    worker = threading.Thread(target=jarvis.run_loop, daemon=True, name="jarvis-listener")
    worker.start()
    jarvis.say("Джарвис запущен и готов к работе.")

    tray = build_tray(jarvis)
    tray.run()  # блокирует до «Выход»
    jarvis.shutdown()
    log.info("Завершение работы")


if __name__ == "__main__":
    main()
