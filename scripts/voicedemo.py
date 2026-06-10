"""Прослушка голосов: проигрывает одну фразу всеми доступными голосами.

Запуск: python scripts/voicedemo.py [текст]
"""

import io
import sys
import wave
import winsound
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

TEXT = " ".join(sys.argv[1:]) or "Феникс на связи. Открываю Стим, сэр. Скриншот сохранён."


def main() -> None:
    from huggingface_hub import hf_hub_download
    from piper import PiperVoice, SynthesisConfig

    for v in ["ruslan", "dmitri"]:
        rel = f"ru/ru_RU/{v}/medium/ru_RU-{v}-medium.onnx"
        voice = PiperVoice.load(hf_hub_download("rhasspy/piper-voices", rel))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(TEXT, wf, SynthesisConfig(length_scale=0.87))
        print(f"piper/{v}...")
        winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY)

    import asyncio

    from jarvis.tts import Speaker

    s = Speaker({"tts_backend": "winrt", "voice": "Pavel", "voice_rate": 1.15})
    print("winrt/Pavel...")
    winsound.PlaySound(asyncio.run(s._synthesize(TEXT)), winsound.SND_MEMORY)


if __name__ == "__main__":
    main()
