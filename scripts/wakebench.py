"""Бенчмарк кандидатов в wake-слово: TTS (Pavel) -> Vosk-small -> что услышалось.

Wake-слово ловит Vosk-small в стриме, поэтому слово должно стабильно
распознаваться именно им. Запуск: python scripts/wakebench.py
"""

import asyncio
import io
import json
import sys
import wave
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from vosk import KaldiRecognizer, Model, SetLogLevel  # noqa: E402

from jarvis.matching import match_score  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

CANDIDATES = [
    "джарвис",   # текущее, для сравнения
    "нексус",
    "оракул",
    "феникс",
    "гермес",
    "юпитер",
    "кронос",
    "протон",
    "сокол",
    "вектор",
    "циклоп",
    "альтрон",
]

TEMPLATES = [
    "{w} сделай скриншот",
    "{w} открой стим",
    "эй {w} который час",
]


def recognize(model: Model, wav_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(wav_bytes))
    rec = KaldiRecognizer(model, wf.getframerate())
    while True:
        chunk = wf.readframes(4000)
        if not chunk:
            break
        rec.AcceptWaveform(chunk)
    return json.loads(rec.FinalResult()).get("text", "")


def main() -> None:
    SetLogLevel(-1)
    speaker = Speaker("Pavel")
    model = Model(str(BASE / "models" / "vosk-model-small-ru-0.22"))

    results = []
    for word in CANDIDATES:
        heard_words = []
        exact = fuzzy = 0
        for tpl in TEMPLATES:
            wav = asyncio.run(speaker._synthesize(tpl.format(w=word)))
            heard = recognize(model, wav)
            tokens = heard.split()
            # ищем wake-токен в начале фразы (как в боевом коде)
            tok = ""
            for t in tokens[:2]:  # «эй X ...» — слово может быть вторым
                if match_score(t, word) >= 0.8:
                    tok = t
                    break
            if tok == word:
                exact += 1
                fuzzy += 1
            elif tok:
                fuzzy += 1
            heard_words.append(" ".join(tokens[:2]))
        results.append((word, exact, fuzzy, heard_words))

    print(f"{'слово':<10} {'точно':<6} {'фаззи':<6} услышано (первые 2 токена)")
    for word, exact, fuzzy, heard in sorted(results, key=lambda r: (-r[2], -r[1])):
        print(f"{word:<10} {exact}/3    {fuzzy}/3    {heard}")


if __name__ == "__main__":
    main()
