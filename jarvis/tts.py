"""Синтез речи.

Бэкенды по приоритету:
1. xtts — клонирование голоса (XTTS-v2, GPU, ~2-4 с): кладёте референс
   voices/jarvis.wav (10-30 с чистой речи) — Феникс говорит этим голосом;
2. piper — локальный нейро-TTS (ONNX, CPU, ~0.2 с), голоса ru_RU dmitri/ruslan;
3. winrt — системный OneCore-голос Microsoft Pavel (его нет в классическом SAPI);
4. sapi — pyttsx3/Ирина, аварийный.

tts_backend: "auto" (xtts при наличии референса, иначе piper) / xtts / piper / winrt.
Скорость дикции: voice_rate (1.0 = обычная).
"""

import asyncio
import io
import logging
import os
import wave
import winsound
from pathlib import Path

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"
BASE_DIR = Path(__file__).resolve().parent.parent


class Speaker:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None

        backend = cfg.get("tts_backend", "auto")
        ref = BASE_DIR / cfg.get("xtts_ref", "voices/jarvis.wav")
        if backend in ("auto", "xtts"):
            if ref.exists():
                try:
                    self._init_xtts(ref)
                except Exception:
                    log.exception("XTTS не завёлся, переключаюсь на piper")
            elif backend == "xtts":
                log.warning("Референс голоса не найден: %s — переключаюсь на piper", ref)
        if self._mode is None and backend in ("auto", "xtts", "piper"):
            try:
                self._init_piper(cfg.get("tts_voice", "ruslan"))
            except Exception:
                log.exception("Piper не завёлся, переключаюсь на WinRT")
        if self._mode is None:
            try:
                from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401

                self._mode = "winrt"
                log.info("TTS: WinRT, голос с подсказкой %r, скорость %.2f",
                         self._voice_hint, self.rate)
            except Exception:
                log.exception("WinRT недоступен, переключаюсь на SAPI (pyttsx3)")
                self._init_sapi()

    # --- xtts (клонирование голоса) --------------------------------------

    def _init_xtts(self, ref: Path) -> None:
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        import torch
        from TTS.api import TTS as CoquiTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        log.info("Загрузка XTTS-v2 на %s (это десятки секунд)...", device)
        self._xtts = CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        self._xtts_ref = str(ref)
        self._mode = "xtts"
        log.info("TTS: XTTS-v2, клон голоса из %s", ref.name)

    def _speak_xtts(self, text: str) -> None:
        import numpy as np

        samples = self._xtts.tts(text=text, speaker_wav=self._xtts_ref,
                                 language="ru", speed=self.rate)
        pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm.tobytes())
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    # --- piper ---------------------------------------------------------

    def _init_piper(self, voice: str) -> None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice, SynthesisConfig

        rel = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium.onnx"
        onnx = hf_hub_download(PIPER_REPO, rel)
        hf_hub_download(PIPER_REPO, rel + ".json")
        self._piper = PiperVoice.load(onnx)
        self._piper_cfg = SynthesisConfig(length_scale=round(1.0 / self.rate, 2))
        self._mode = "piper"
        log.info("TTS: piper, голос %s, скорость %.2f", voice, self.rate)

    def _speak_piper(self, text: str) -> None:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper.synthesize_wav(text, wf, self._piper_cfg)
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    # --- winrt / sapi ---------------------------------------------------

    def _init_sapi(self) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()
        for v in self._engine.getProperty("voices"):
            ident = f"{v.id} {v.name}".lower()
            if self._voice_hint.lower() in ident or "ru" in ident or "irina" in ident:
                self._engine.setProperty("voice", v.id)
                log.info("TTS: SAPI, голос %s", v.name)
                break
        self._mode = "sapi"

    async def _synthesize(self, text: str) -> bytes:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader

        synth = SpeechSynthesizer()
        voices = list(SpeechSynthesizer.all_voices)
        voice = next(
            (v for v in voices if self._voice_hint.lower() in v.display_name.lower()),
            None,
        ) or next((v for v in voices if v.language.lower().startswith("ru")), None)
        if voice is not None:
            synth.voice = voice
        try:
            synth.options.speaking_rate = self.rate
        except Exception:
            pass  # старые сборки Windows без опции — говорим с обычной скоростью
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))

    # --- общий вход ------------------------------------------------------

    def speak(self, text: str) -> None:
        """Блокирующее проговаривание фразы."""
        if not text:
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "xtts":
                self._speak_xtts(text)
            elif self._mode == "piper":
                self._speak_piper(text)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                winsound.PlaySound(wav, winsound.SND_MEMORY)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")
