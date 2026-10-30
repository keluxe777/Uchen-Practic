"""Поиск, замена и статистика по тексту расшифровки."""

import re


def find_segments(segments, query, match_case=False):
    """Возвращает номера сегментов (с 0), в которых встречается query."""
    if not query:
        return []
    if match_case:
        return [i for i, s in enumerate(segments) if query in s.text]
    q = query.lower()
    return [i for i, s in enumerate(segments) if q in s.text.lower()]


def replace_in_segments(segments, query, replacement, match_case=False):
    """Заменяет все вхождения query на replacement. Возвращает число замен."""
    if not query:
        return 0
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile(re.escape(query), flags)
    total = 0
    for s in segments:
        # lambda — чтобы символы вроде «\1» в замене не считались спецсимволами
        new_text, count = pattern.subn(lambda _m: replacement, s.text)
        if count:
            s.text = new_text
            total += count
    return total


def count_words(text):
    return len(re.findall(r"\w+", text))


def get_stats(segments, duration):
    """Статистика: число фрагментов, слов, символов и темп речи (слов в минуту)."""
    words = sum(count_words(s.text) for s in segments)
    chars = sum(len(s.text) for s in segments)
    speech_time = sum(max(s.end - s.start, 0) for s in segments)
    per_minute = round(words / (speech_time / 60)) if speech_time > 0 else 0
    return {
        "segments": len(segments),
        "words": words,
        "chars": chars,
        "duration": duration,
        "words_per_minute": per_minute,
    }
