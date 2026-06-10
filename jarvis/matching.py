"""Нечёткое сопоставление речи с названиями: транслитерация + difflib.

Vosk выдаёт только кириллицу («обс студио»), а программы называются латиницей
(«OBS Studio»), поэтому сравниваем и оригинал, и транслит.
"""

import re
from difflib import SequenceMatcher

_RU_DIGRAPHS = {"дж": "j"}  # фонетика: «джарвис» -> jarvis, а не dzharvis
_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    text = text.lower()
    for ru, lat in _RU_DIGRAPHS.items():
        text = text.replace(ru, lat)
    return "".join(_RU_LAT.get(ch, ch) for ch in text)


def wake_score(token: str, wake_word: str) -> float:
    """Строгая похожесть для wake-слова: только полный ratio (с транслитом),
    без бонусов за подстроку/слова — иначе «фен» будил бы «феникса»."""
    return max(
        SequenceMatcher(None, a, b).ratio()
        for a in {token, translit(token)}
        for b in {wake_word, translit(wake_word)}
    )


def _skeleton(s: str) -> str:
    """Согласный скелет: stim/steam -> stm. Гласные между языками плавают,
    согласные при транслитерации сохраняются."""
    return re.sub(r"[aeiouy\s]", "", translit(s))


def match_score(spoken: str, candidate: str) -> float:
    """Похожесть сказанного на название (0..1). Оба сравниваются в нижнем регистре,
    сказанное — ещё и в транслите; пробуем целиком, без пробелов и по словам."""
    cand = re.sub(r"\(.*?\)", " ", candidate.lower()).strip()
    cand = re.sub(r"\s+", " ", cand)
    if not spoken or not cand:
        return 0.0
    best = 0.0
    # Whisper может выдать латиницу («открой discord»), псевдонимы бывают
    # кириллицей — поэтому транслитерируем обе стороны
    for s in {spoken, translit(spoken)}:
        for c in {cand, translit(cand)}:
            if s == c:
                return 1.0
            if len(s) >= 3 and (s in c or c in s):
                best = max(best, 0.9)
            best = max(best, SequenceMatcher(None, s, c).ratio())
            best = max(best, SequenceMatcher(None, s.replace(" ", ""), c.replace(" ", "")).ratio())
            for word in c.split():
                best = max(best, SequenceMatcher(None, s, word).ratio())
    sk_s, sk_c = _skeleton(spoken), _skeleton(cand)
    if len(sk_s) >= 3 and sk_s == sk_c:
        best = max(best, 0.8)
    return best
