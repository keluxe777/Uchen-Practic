"""Распознавание речи с помощью готовой модели Whisper (библиотека faster-whisper)."""

from app.models import Segment

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
}


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
            # int8 на процессоре — быстро и экономно по памяти
            self._model = WhisperModel(name, device="cpu", compute_type="int8")
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
        model = self.load_model(model_name)
        lang = None if language == "auto" else language
        segments_iter, info = model.transcribe(
            audio_path,
            language=lang,
            beam_size=1,       # быстрее, качество почти такое же
            vad_filter=True,   # пропускать тишину
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
        return result, info.language, duration
