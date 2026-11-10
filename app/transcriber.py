"""Распознавание речи с помощью готовой модели Whisper (библиотека faster-whisper)."""

import os

from app.models import Segment
from app.paths import bundled_models_dirs, models_dir

# Модели от быстрой и простой к медленной и точной.
# На слабом ноутбуке без видеокарты лучше всего подходят tiny и base.
# large-v3-turbo — облегчённая large-v3: почти та же точность, но в несколько раз быстрее.
MODELS = {
    "tiny": "tiny — самая быстрая (~75 МБ)",
    "base": "base — оптимальная (~145 МБ)",
    "small": "small — точнее, но медленнее (~480 МБ)",
    "large-v3-turbo": "large-v3-turbo — самая точная (~1,6 ГБ)",
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

SAMPLE_RATE = 16000

# Смена языка внутри записи (дефект D-09: 13 с английского вступления перед русской речью
# распознавались «по-русски» и почти пропадали). Язык определяется для каждого отрезка
# речи между паузами; другой язык принимается, только если модель в нём уверена.
CHUNK_PAUSE_SECONDS = 0.4    # пауза, по которой режем речь на отрезки
CHUNK_MAX_SECONDS = 30       # длиннее модель за один раз не слушает
SWITCH_MIN_SECONDS = 2.0     # по более коротким отрезкам язык не определяем
SWITCH_MIN_PROB = 0.7        # насколько модель должна быть уверена в другом языке
DETECT_HEAD_SECONDS = 8      # язык отрезка определяется по его первым секундам (так быстрее)

TRANSCRIBE_OPTIONS = dict(
    beam_size=1,                       # быстрее, качество почти такое же
    vad_filter=True,                   # тишину и паузы отсекает фильтр голоса
    # Не выбрасывать «неуверенные» фрагменты: на песнях и записях с музыкой модель
    # иначе отбрасывала почти весь текст (дефект D-07). От тишины защищает vad_filter.
    no_speech_threshold=None,
    log_prob_threshold=None,
    condition_on_previous_text=False,  # меньше риск зацикливания на одной фразе
)


def plan_language_runs(detected, main_lang, duration):
    """Делит запись на участки с одним языком.

    detected — список (начало, конец, язык, уверенность) для отрезков речи по порядку.
    Возвращает список (начало, конец, язык); участки идут встык и покрывают всю запись.
    Если язык один — один участок на всю запись.
    """
    runs = []
    for start, end, lang, prob in detected:
        sure = lang != main_lang and prob >= SWITCH_MIN_PROB and end - start >= SWITCH_MIN_SECONDS
        lang = lang if sure else main_lang
        if runs and runs[-1][2] == lang:
            runs[-1][1] = end
        else:
            runs.append([start, end, lang])
    if len(runs) <= 1:
        return [(0.0, duration, main_lang)]
    # Границы — посередине паузы между участками, края — начало и конец записи
    cuts = [0.0] + [(a[1] + b[0]) / 2 for a, b in zip(runs, runs[1:])] + [duration]
    return [(cuts[i], cuts[i + 1], run[2]) for i, run in enumerate(runs)]


def clip_to_duration(start, end, duration):
    """Не даёт времени фрагмента выйти за конец записи.

    Модель иногда ставит конец последнего фрагмента позже конца файла
    (дефект D-08: tiny на записи 2:09,8 дала конец 2:10,6) — в субтитрах
    появлялось время, которого в записи нет.
    """
    if duration and duration > 0:
        end = min(end, duration)
        start = min(start, end)
    return start, end


class TranscriptionCancelled(Exception):
    """Пользователь нажал «Отмена»."""


class ModelLoadError(Exception):
    """Модель не удалось загрузить (обычно нет интернета при первом запуске)."""


class Transcriber:
    """Загружает модель один раз и потом переиспользует её."""

    def __init__(self):
        self._model = None
        self._model_name = None
        self.languages = []  # языки последней расшифровки, первый — основной

    def load_model(self, name):
        if name not in MODELS:
            raise ValueError(f"Неизвестная модель: {name}")
        if self._model is not None and self._model_name == name:
            return self._model
        try:
            from faster_whisper import WhisperModel
            # Если модель уже лежит рядом с программой (models/base) — берём её, интернет не нужен
            source = name
            for folder in (*bundled_models_dirs(), models_dir()):
                local = os.path.join(folder, name) if folder else ""
                if local and os.path.isfile(os.path.join(local, "model.bin")):
                    source = local
                    break
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
        audio = decode_audio(audio_path, sampling_rate=SAMPLE_RATE)  # читаем файл один раз
        self._check_cancel(cancel_event)
        duration = len(audio) / SAMPLE_RATE
        runs = None
        if language == "auto":
            # Основной язык — по участкам с голосом и по нескольким отрезкам записи (D-06)
            lang, _prob, _all = model.detect_language(
                audio, vad_filter=True, language_detection_segments=LANGUAGE_DETECTION_SEGMENTS)
            # Язык может меняться внутри записи (например, английское вступление перед русской речью).
            # Модель выбирает один язык на кусок в 30 с и иначе «переводит» чужую речь в транскрипцию.
            runs = self._language_runs(model, audio, lang, cancel_event)
        else:
            lang = language
        self.languages = list(dict.fromkeys([lang] + [r[2] for r in runs or []]))
        result = []
        if not runs or len(runs) == 1:
            segments_iter, _info = model.transcribe(audio, language=lang, **TRANSCRIBE_OPTIONS)
            self._collect(segments_iter, 0.0, duration, duration, result, on_progress, cancel_event)
        else:
            for start, end, run_lang in runs:
                piece = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
                segments_iter, _info = model.transcribe(piece, language=run_lang, **TRANSCRIBE_OPTIONS)
                self._collect(segments_iter, start, end, duration, result, on_progress, cancel_event)
        self._check_cancel(cancel_event)
        return result, lang, duration

    @staticmethod
    def _check_cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled()

    def _collect(self, segments_iter, offset, limit, duration, result, on_progress, cancel_event):
        """Переносит фрагменты модели в result: время сдвигается на offset и не выходит за limit."""
        for seg in segments_iter:  # фрагменты распознаются по одному
            self._check_cancel(cancel_event)
            text = seg.text.strip()
            if not text:
                continue
            start, end = clip_to_duration(seg.start + offset, seg.end + offset, limit)
            segment = Segment(start=start, end=end, text=text)
            result.append(segment)
            if on_progress and duration:
                on_progress(min(end / duration, 1.0), segment)

    def _language_runs(self, model, audio, main_lang, cancel_event):
        """Определяет язык каждого отрезка речи и возвращает участки записи с одним языком.

        Если что-то пошло не так (например, другая версия библиотеки), возвращает None —
        тогда запись расшифровывается целиком на основном языке, как раньше.
        """
        try:
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, speech_pad_ms=100))
            chunks = []
            for s in speech:  # склеиваем куски речи в отрезки, разрезая по паузам
                start, end = s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE
                if chunks and start - chunks[-1][1] < CHUNK_PAUSE_SECONDS and end - chunks[-1][0] < CHUNK_MAX_SECONDS:
                    chunks[-1][1] = end
                else:
                    chunks.append([start, end])
            detected = []
            for start, end in chunks:
                self._check_cancel(cancel_event)
                if end - start < SWITCH_MIN_SECONDS:  # короткий отрезок — язык по нему не определить надёжно
                    detected.append((start, end, main_lang, 0.0))
                    continue
                head = audio[int(start * SAMPLE_RATE):int(min(end, start + DETECT_HEAD_SECONDS) * SAMPLE_RATE)]
                chunk_lang, prob = self._detect_short(model, head)
                detected.append((start, end, chunk_lang, prob))
        except TranscriptionCancelled:
            raise
        except Exception:
            return None
        return plan_language_runs(detected, main_lang, duration=len(audio) / SAMPLE_RATE)

    @staticmethod
    def _detect_short(model, piece):
        """Язык короткого отрезка (до 30 с).

        Обычный model.detect_language дополняет каждый отрезок тишиной до 30 секунд — модель
        тогда тратит на отрезок столько же времени, сколько на 30 секунд записи. Здесь отрезок
        подаётся как есть: в 2–3 раза быстрее, языки определяются так же (проверено на tiny/base/small).
        """
        features = model.feature_extractor(piece)
        features = features[:, : features.shape[-1] - features.shape[-1] % 2]  # чётное число кадров
        lang_token, prob = model.model.detect_language(model.encode(features))[0][0]
        return lang_token[2:-2], prob  # «<|en|>» → «en»
