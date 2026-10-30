"""Распознавание речи с помощью готовой модели Whisper (библиотека faster-whisper)."""

import os

from app.models import Segment
from app.paths import models_dir

# Модели от быстрой и простой к медленной и точной.
# На слабом ноутбуке без видеокарты лучше всего подходят tiny и base.
MODELS = {
    "tiny": "tiny — самая быстрая (~75 МБ)",
    "base": "base — оптимальная (~145 МБ)",
    "small": "small — точнее, но медленнее (~480 МБ)",
}

LANGUAGES = {
    "auto": "Определить автоматически",
    "ru": "Русский",
    "en": "Английский",
    "uk": "Украинский",
}

# Названия для показа пользователю, если модель определит другой язык
LANGUAGE_NAMES = {
    **{k: v for k, v in LANGUAGES.items() if k != "auto"},
    "be": "Белорусский", "kk": "Казахский", "de": "Немецкий", "fr": "Французский", "es": "Испанский",
    "it": "Итальянский", "pl": "Польский", "bg": "Болгарский", "el": "Греческий", "tr": "Турецкий",
    "zh": "Китайский", "ja": "Японский",
}


def language_name(code):
    return LANGUAGE_NAMES.get(code, code or "не определён")

# Сколько 30-секундных отрезков слушать при определении языка.
# Раньше слушали только первые 30 секунд — на песнях это музыкальное вступление,
# и язык определялся неверно (дефект D-06: русская песня → «греческий»).
LANGUAGE_DETECTION_SEGMENTS = 4


class TranscriptionCancelled(Exception):
    """Пользователь нажал «Отмена»."""


class ModelLoadError(Exception):
    """Модель не удалось загрузить (обычно нет интернета при первом запуске)."""


class Transcriber:
    """Загружает модель один раз и потом переиспользует её."""

    def __init__(self):
        self._model = None
        self._model_name = None

    def load_model(self, name):
        if name not in MODELS:
            raise ValueError(f"Неизвестная модель: {name}")
        if self._model is not None and self._model_name == name:
            return self._model
        try:
            from faster_whisper import WhisperModel
            # Если модель уже лежит рядом с программой (models/base) — берём её, интернет не нужен
            source = name
            if models_dir():
                local = os.path.join(models_dir(), name)
                if os.path.isfile(os.path.join(local, "model.bin")):
                    source = local
            # int8 на процессоре — быстро и экономно по памяти
            self._model = WhisperModel(source, device="cpu", compute_type="int8",
                                       download_root=models_dir())
            self._model_name = name
        except Exception as exc:
            self._model = None
            self._model_name = None
            raise ModelLoadError(
                "Не удалось загрузить модель распознавания.\n"
                "При первом запуске модель скачивается из интернета — проверьте подключение.\n"
                f"({exc})"
            ) from exc
        return self._model

    def transcribe(self, audio_path, model_name="base", language="auto",
                   on_progress=None, cancel_event=None):
        """Расшифровывает файл и возвращает (список Segment, язык, длительность).

        on_progress(доля от 0 до 1, сегмент) вызывается после каждого фрагмента.
        cancel_event — threading.Event; если он установлен, работа прерывается.
        """
        from faster_whisper import decode_audio

        model = self.load_model(model_name)
        audio = decode_audio(audio_path, sampling_rate=16000)  # читаем файл один раз
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled()
        if language == "auto":
            # Определяем язык только по участкам с голосом и по нескольким отрезкам записи
            lang, _prob, _all = model.detect_language(
                audio, vad_filter=True, language_detection_segments=LANGUAGE_DETECTION_SEGMENTS)
        else:
            lang = language
        segments_iter, info = model.transcribe(
            audio,
            language=lang,
            beam_size=1,                       # быстрее, качество почти такое же
            vad_filter=True,                   # тишину и паузы отсекает фильтр голоса
            # Не выбрасывать «неуверенные» фрагменты: на песнях и записях с музыкой модель
            # иначе отбрасывала почти весь текст (дефект D-07). От тишины защищает vad_filter.
            no_speech_threshold=None,
            log_prob_threshold=None,
            condition_on_previous_text=False,  # меньше риск зацикливания на одной фразе
        )
        duration = info.duration or 0
        result = []
        for seg in segments_iter:  # фрагменты распознаются по одному
            if cancel_event is not None and cancel_event.is_set():
                raise TranscriptionCancelled()
            text = seg.text.strip()
            if not text:
                continue
            segment = Segment(start=seg.start, end=seg.end, text=text)
            result.append(segment)
            if on_progress and duration:
                on_progress(min(seg.end / duration, 1.0), segment)
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled()
        return result, lang, duration
