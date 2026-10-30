"""Проверка аудиофайла перед расшифровкой и сведения о нём."""

import os

# Форматы, которые умеет читать библиотека av (входит в faster-whisper)
SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".wma", ".opus", ".webm", ".mp4")

MAX_FILE_SIZE_MB = 500       # больше — точно не «короткая запись»
LONG_AUDIO_SECONDS = 30 * 60  # о записях длиннее 30 минут предупреждаем


class AudioFileError(Exception):
    """Файл нельзя расшифровать. Текст ошибки показывается пользователю."""


def check_audio_file(path):
    """Проверяет путь, расширение и размер. При ошибке бросает AudioFileError."""
    if not path or not str(path).strip():
        raise AudioFileError("Файл не выбран.")
    if not os.path.exists(path):
        raise AudioFileError(f"Файл не найден:\n{path}")
    if not os.path.isfile(path):
        raise AudioFileError("Выбран не файл, а папка.")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(e.lstrip(".") for e in SUPPORTED_EXTENSIONS)
        raise AudioFileError(f"Формат «{ext or 'без расширения'}» не поддерживается.\nПодходят: {allowed}")
    size = os.path.getsize(path)
    if size == 0:
        raise AudioFileError("Файл пустой (0 байт).")
    if size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise AudioFileError(f"Файл слишком большой (больше {MAX_FILE_SIZE_MB} МБ).")


def get_audio_info(path):
    """Возвращает словарь: длительность (сек), размер (МБ), формат, частота, каналы.

    Если файл повреждён или это не аудио — бросает AudioFileError.
    """
    check_audio_file(path)
    import av  # импорт здесь, чтобы тесты без av тоже могли проверять пути

    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise AudioFileError("В файле нет звуковой дорожки.")
            stream = container.streams.audio[0]
            duration = None
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / av.time_base
            if not duration:
                # Длительность не записана в заголовке — считаем по кадрам
                duration = 0.0
                for frame in container.decode(stream):
                    duration += frame.samples / frame.sample_rate
            info = {
                "duration": float(duration),
                "size_mb": os.path.getsize(path) / (1024 * 1024),
                "format": os.path.splitext(path)[1].lstrip(".").upper(),
                "sample_rate": stream.rate or 0,
                "channels": stream.channels or 0,
            }
    except AudioFileError:
        raise
    except Exception as exc:  # av бросает свои ошибки для битых файлов
        raise AudioFileError(f"Не удалось прочитать файл — возможно, он повреждён.\n({exc})") from exc

    if info["duration"] <= 0.1:
        raise AudioFileError("Запись слишком короткая или пустая.")
    return info
