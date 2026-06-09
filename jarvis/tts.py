"""Синтез речи.

Основной путь — WinRT (Windows.Media.SpeechSynthesis): он видит OneCore-голоса,
в том числе мужской русский «Microsoft Pavel», которого нет в классическом SAPI.
Фолбэк — pyttsx3/SAPI (Ирина).
"""

import asyncio
import logging
import winsound

log = logging.getLogger("jarvis.tts")


class Speaker:
    def __init__(self, voice_hint: str = "Pavel"):
        self._voice_hint = voice_hint
        self._engine = None
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401

            self._mode = "winrt"
            log.info("TTS: WinRT, голос с подсказкой %r", voice_hint)
        except Exception:
            log.exception("WinRT недоступен, переключаюсь на SAPI (pyttsx3)")
            self._init_sapi()

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

    def speak(self, text: str) -> None:
        """Блокирующее проговаривание фразы."""
        if not text:
            return
        log.info("Говорю: %s", text)
        try:
            if self._mode == "winrt":
                wav = asyncio.run(self._synthesize(text))
                winsound.PlaySound(wav, winsound.SND_MEMORY)
            else:
                self._engine.say(text)
                self._engine.runAndWait()
        except Exception:
            log.exception("Ошибка синтеза речи")

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
        stream = await synth.synthesize_text_to_stream_async(text)
        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        return bytes(reader.read_buffer(stream.size))
