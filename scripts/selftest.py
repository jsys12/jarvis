"""Самопроверка без микрофона: TTS -> Vosk -> разбор команды.

Запуск: python scripts/selftest.py
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

from jarvis.apps import build_apps, find_app  # noqa: E402
from jarvis.intents import IntentHandler, _is_close_verb, _is_open_verb, normalize  # noqa: E402
from jarvis.tts import Speaker  # noqa: E402

PHRASES = [
    "джарвис открой стим",
    "джарвис закрой дискорд",
    "джарвис сколько времени",
    "джарвис открой ютуб",
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
    assert speaker._mode == "winrt", "Pavel/WinRT недоступен"
    model = Model(str(BASE / "models" / "vosk-model-small-ru-0.22"))
    apps = build_apps({})
    wake = ["джарвис", "жарвис", "джервис", "джарвиз"]

    failed = 0
    for phrase in PHRASES:
        wav = asyncio.run(speaker._synthesize(phrase))
        heard = normalize(recognize(model, wav))
        tokens = heard.split()
        woke = tokens and tokens[0] in wake
        cmd = " ".join(tokens[1:]) if woke else ""
        # «сухой» разбор: что бы сделал ассистент (без запуска приложений)
        ctoks = cmd.split()
        verb = "open" if any(_is_open_verb(t) for t in ctoks) else \
               "close" if any(_is_close_verb(t) for t in ctoks) else "-"
        target = " ".join(t for t in ctoks if not _is_open_verb(t) and not _is_close_verb(t))
        app = find_app(apps, target) if verb != "-" and target else None
        print(f"[{'OK' if woke else '!!'}] сказано: {phrase!r} -> услышано: {heard!r} "
              f"-> {verb} {app.key if app else target!r}")
        if not woke:
            failed += 1

    # Разбор целей без запуска приложений
    for target, expected in [("стим", "steam"), ("дискорд", "discord"),
                             ("доту", "dota2"), ("телегу", "telegram"), ("клауд", "claude")]:
        app = find_app(apps, target)
        ok = app is not None and app.key == expected
        print(f"[{'OK' if ok else '!!'}] цель {target!r} -> {app.key if app else None}")
        failed += 0 if ok else 1

    # Болталка (без побочных эффектов)
    handler = IntentHandler({"custom_commands": []}, apps)
    for q in ["сколько времени", "какое сегодня число", "кто ты", "как дела"]:
        print(f"[..] {q!r} -> {handler._small_talk(normalize(q))!r}")

    print("\nИтог:", "ВСЁ ОК" if failed == 0 else f"ОШИБОК: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
