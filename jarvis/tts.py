"""Синтез речи.

Бэкенды по приоритету:
1. piper — локальный нейро-TTS (ONNX, CPU, ~0.2 с), голоса ru_RU dmitri/ruslan;
2. winrt — системный OneCore-голос Microsoft Pavel (его нет в классическом SAPI);
3. sapi — pyttsx3/Ирина, аварийный.

Скорость дикции: voice_rate (1.0 = обычная). Для piper это 1/length_scale,
для WinRT — SpeechSynthesizerOptions.SpeakingRate.
"""

import asyncio
import io
import logging
import wave
import winsound

log = logging.getLogger("jarvis.tts")

PIPER_REPO = "rhasspy/piper-voices"


class Speaker:
    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.rate = float(cfg.get("voice_rate", 1.15))
        self._voice_hint = cfg.get("voice", "Pavel")
        self._mode = None
        self._engine = None

        if cfg.get("tts_backend", "piper") == "piper":
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
            if self._mode == "piper":
                self._speak_piper(text)
            elif self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                winsound.PlaySound(wav, winsound.SND_MEMORY)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")
