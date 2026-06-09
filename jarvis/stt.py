"""Распознавание речи: микрофон -> Vosk -> текст."""

import json
import logging
import queue
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")


class Listener:
    def __init__(self, model_dir: Path, sample_rate: int = 16000, device=None):
        SetLogLevel(-1)
        log.info("Загрузка модели Vosk из %s", model_dir)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = device
        self._audio: queue.Queue[bytes] = queue.Queue()
        # Пока ассистент говорит — микрофон игнорируется, чтобы он не слышал сам себя
        self.muted = False

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.warning("Аудиопоток: %s", status)
        if not self.muted:
            self._audio.put(bytes(indata))

    def flush(self) -> None:
        """Сброс буфера и распознавателя (после собственной речи)."""
        while not self._audio.empty():
            try:
                self._audio.get_nowait()
            except queue.Empty:
                break
        self._rec.Reset()

    def phrases(self, stop_event):
        """Генератор законченных распознанных фраз."""
        with sd.RawInputStream(
            samplerate=self._sample_rate,
            blocksize=8000,
            dtype="int16",
            channels=1,
            device=self._device,
            callback=self._callback,
        ):
            log.info("Микрофон открыт, слушаю...")
            while not stop_event.is_set():
                try:
                    data = self._audio.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    if text:
                        log.info("Распознано: %s", text)
                        yield text
