"""Распознавание речи.

Гибридная схема: Vosk (стриминг, лёгкий) непрерывно слушает и ловит wake-слово,
а точную расшифровку команды делает Whisper (faster-whisper, int8, CPU) по
аудиобуферу той же фразы. Если Whisper выключен/не встал — работаем по Vosk.
"""

import json
import logging
import os
import queue
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel

log = logging.getLogger("jarvis.stt")

# CT2-конверсия large-v3-turbo: на GPU быстрее и точнее, чем small на CPU
TURBO_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"


def _enable_cuda_dlls() -> None:
    """Добавляет cuBLAS/cuDNN из pip-пакетов nvidia-* в PATH.

    ctranslate2 ищет cublas64_12.dll через обычный порядок поиска DLL (PATH),
    os.add_dll_directory ему недостаточно.
    """
    try:
        import nvidia
    except ImportError:
        return
    base = Path(nvidia.__path__[0])
    dirs = [str(p) for p in (base / "cublas" / "bin", base / "cudnn" / "bin") if p.exists()]
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ["PATH"]


class Listener:
    def __init__(self, model_dir: Path, sample_rate: int = 16000, device=None):
        SetLogLevel(-1)
        log.info("Загрузка модели Vosk из %s", model_dir)
        self._model = Model(str(model_dir))
        self._rec = KaldiRecognizer(self._model, sample_rate)
        self._sample_rate = sample_rate
        self._device = device
        self._audio: queue.Queue[bytes] = queue.Queue()
        self._utt_buf: list[bytes] = []  # сырое аудио текущей фразы (для Whisper)
        self._utt_len = 0
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
        self._utt_buf.clear()
        self._utt_len = 0
        self._rec.Reset()

    def phrases(self, stop_event):
        """Генератор (текст Vosk, сырое аудио фразы int16 PCM)."""
        max_buf = self._sample_rate * 2 * 30  # не больше 30 секунд аудио
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
                self._utt_buf.append(data)
                self._utt_len += len(data)
                while self._utt_len > max_buf and len(self._utt_buf) > 1:
                    self._utt_len -= len(self._utt_buf.pop(0))
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    audio = b"".join(self._utt_buf)
                    self._utt_buf.clear()
                    self._utt_len = 0
                    if text:
                        log.info("Распознано (vosk): %s", text)
                        yield text, audio


class WhisperTranscriber:
    """Точная расшифровка короткого фрагмента аудио (faster-whisper, CPU, int8).

    ВАЖНО: создавать ДО первого вызова WinRT-синтеза речи — загрузка CTranslate2
    после использования WinRT роняет процесс (access violation 0xC0000005).
    """

    def __init__(self, model_name: str = "auto", device: str = "auto"):
        _enable_cuda_dlls()
        import ctranslate2
        from faster_whisper import WhisperModel

        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if device == "cuda":
            name = TURBO_MODEL if model_name == "auto" else model_name
            try:
                log.info("Загрузка Whisper (%s) на GPU... при первом запуске модель скачается", name)
                self._model = WhisperModel(name, device="cuda", compute_type="int8_float16")
                log.info("Whisper готов (GPU)")
                return
            except Exception:
                log.exception("GPU не завёлся, откатываюсь на CPU")
        name = "small" if model_name == "auto" else model_name
        log.info("Загрузка Whisper (%s) на CPU...", name)
        self._model = WhisperModel(name, device="cpu", compute_type="int8")
        log.info("Whisper готов (CPU)")

    def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        import numpy as np

        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if sample_rate != 16000 and len(audio) > 1:
            n = int(len(audio) * 16000 / sample_rate)
            audio = np.interp(
                np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
            ).astype(np.float32)
        segments, _ = self._model.transcribe(
            audio,
            language="ru",
            beam_size=2,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        log.info("Распознано (whisper): %s", text)
        return text
