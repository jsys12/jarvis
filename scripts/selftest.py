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
from jarvis.installed import find_installed, scan_start_menu  # noqa: E402
from jarvis.intents import (IntentHandler, _is_close_verb, _is_open_verb,  # noqa: E402
                            normalize, parse_engine_tail, parse_search)
from jarvis.matching import match_score  # noqa: E402
from jarvis.actions import find_process, spoken_domain  # noqa: E402
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
    # Whisper — строго до первого использования WinRT (иначе access violation)
    from jarvis.stt import WhisperTranscriber
    whisper = WhisperTranscriber("auto", "auto")
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

    # Глагольные формы (Whisper меняет форму: «закрой» -> «закроет»)
    for tok, fn, exp in [("закроет", _is_close_verb, True), ("открою", _is_open_verb, True),
                         ("откройте", _is_open_verb, True), ("выключи", _is_close_verb, True),
                         ("включи", _is_open_verb, True), ("скриншот", _is_open_verb, False)]:
        ok = fn(tok) == exp
        print(f"[{'OK' if ok else '!!'}] глагол: {tok!r} -> {fn(tok)}")
        failed += 0 if ok else 1

    # Латинское wake-слово от Whisper («Jarvis открой VSCode»)
    ok = match_score("jarvis", "джарвис") >= 0.8
    print(f"[{'OK' if ok else '!!'}] wake латиницей: jarvis ~ джарвис = {match_score('jarvis', 'джарвис'):.2f}")
    failed += 0 if ok else 1

    # Разбор целей без запуска приложений
    for target, expected in [("стим", "steam"), ("дискорд", "discord"),
                             ("доту", "dota2"), ("телегу", "telegram"), ("клауд", "claude"),
                             ("вс код", "vscode"), ("vscode", "vscode")]:
        app = find_app(apps, target)
        ok = app is not None and app.key == expected
        print(f"[{'OK' if ok else '!!'}] цель {target!r} -> {app.key if app else None}")
        failed += 0 if ok else 1

    # Болталка (без побочных эффектов)
    handler = IntentHandler({"custom_commands": []}, apps)
    for q in ["сколько времени", "какое сегодня число", "кто ты", "как дела"]:
        print(f"[..] {q!r} -> {handler._small_talk(normalize(q))!r}")

    # Разбор поисковых запросов (чистая функция, без открытия браузера)
    for q, expected in [
        ("найди рецепт борща", ("google", "рецепт борща")),
        ("поищи на ютубе лофи музыку", ("youtube", "лофи музыку")),
        ("найди котиков в ютубе", ("youtube", "котиков")),
        ("открой гугл с поиском погода в хельсинки", ("google", "погода в хельсинки")),
        ("открой ютуб с поиском обзор дота два", ("youtube", "обзор дота два")),
        ("загугли что такое vosk", ("google", "что такое vosk")),
    ]:
        res = parse_search(normalize(q))
        got = (res[0], res[2]) if res else None
        ok = got == expected
        print(f"[{'OK' if ok else '!!'}] поиск: {q!r} -> {got}")
        failed += 0 if ok else 1

    # Транслит-сопоставление (русская речь -> латинские названия)
    for spoken, candidate in [("обс", "OBS Studio"), ("дискорд", "Discord"),
                              ("телеграм", "Telegram Desktop"), ("стим", "Steam"),
                              ("блендер", "Blender"), ("гит хаб десктоп", "GitHub Desktop")]:
        score = match_score(spoken, candidate)
        ok = score >= 0.75
        print(f"[{'OK' if ok else '!!'}] транслит: {spoken!r} ~ {candidate!r} = {score:.2f}")
        failed += 0 if ok else 1

    # Движок в середине фразы + защита от мусорных доменов
    res = parse_engine_tail(normalize("открой на ютубе видео котиков"))
    ok = res is not None and res[0] == "youtube" and res[2] == "видео котиков"
    print(f"[{'OK' if ok else '!!'}] хвост: 'открой на ютубе видео котиков' -> {res}")
    failed += 0 if ok else 1
    res = parse_engine_tail(normalize("от к но ютубе видео котиков"))  # каша из лога
    ok = res is not None and res[0] == "youtube"
    print(f"[{'OK' if ok else '!!'}] хвост (каша vosk): -> {res}")
    failed += 0 if ok else 1
    from jarvis.actions import guess_site
    bad = guess_site("от к но ютубе видео котиков")
    ok = bad is None
    print(f"[{'OK' if ok else '!!'}] мусорный домен не угадывается -> {bad}")
    failed += 0 if ok else 1

    # Продиктованный домен
    dom = spoken_domain("хабр точка ру")
    ok = dom == "https://habr.ru"
    print(f"[{'OK' if ok else '!!'}] домен: 'хабр точка ру' -> {dom}")
    failed += 0 if ok else 1

    # Whisper: точная расшифровка фразы, на которой Vosk ошибался
    import time as _t
    for phrase in ["джарвис открой на ютубе видео котиков", "джарвис открой дискорд",
                   "джарвис закрой яндекс музыку"]:
        wav_bytes = asyncio.run(speaker._synthesize(phrase))
        wf = wave.open(io.BytesIO(wav_bytes))
        pcm = wf.readframes(wf.getnframes())
        t0 = _t.time()
        heard = normalize(whisper.transcribe(pcm, wf.getframerate()))
        dt = _t.time() - t0
        ok = any(w in heard for w in ("ютуб", "дискорд", "discord", "яндекс музыку"))
        print(f"[{'OK' if ok else '!!'}] whisper ({dt:.1f}с): {phrase!r} -> {heard!r}")
        failed += 0 if ok else 1

    # Живой индекс меню «Пуск» и процессы (информативно, зависит от машины)
    index = scan_start_menu()
    print(f"[..] меню «Пуск»: {len(index)} программ")
    for spoken in ["обс", "телеграм", "клод"]:
        hit = find_installed(index, spoken)
        print(f"[..] установлено: {spoken!r} -> {hit[0] if hit else None}")
    print(f"[..] процесс 'хром' -> {find_process('хром')}")

    print("\nИтог:", "ВСЁ ОК" if failed == 0 else f"ОШИБОК: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
