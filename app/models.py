"""Данные программы: фрагмент расшифровки (сегмент) и проект."""

from dataclasses import dataclass, field


@dataclass
class Segment:
    """Один фрагмент речи: время начала, время конца (в секундах) и текст."""
    start: float
    end: float
    text: str

    def to_dict(self):
        return {"start": round(self.start, 3), "end": round(self.end, 3), "text": self.text}

    @staticmethod
    def from_dict(data):
        start = float(data["start"])
        end = float(data["end"])
        text = str(data["text"])
        if start < 0 or end < start:
            raise ValueError(f"Неверное время сегмента: {start}–{end}")
        return Segment(start, end, text)


@dataclass
class Project:
    """Проект: какой файл расшифрован, с какими настройками и что получилось."""
    audio_path: str = ""
    duration: float = 0.0
    language: str = ""
    model: str = ""
    segments: list = field(default_factory=list)

    def to_dict(self):
        return {
            "format": "audio-transcriber-project",
            "version": 1,
            "audio_path": self.audio_path,
            "duration": round(self.duration, 3),
            "language": self.language,
            "model": self.model,
            "segments": [s.to_dict() for s in self.segments],
        }

    @staticmethod
    def from_dict(data):
        if not isinstance(data, dict) or data.get("format") != "audio-transcriber-project":
            raise ValueError("Файл не является проектом расшифровщика")
        segments = [Segment.from_dict(s) for s in data.get("segments", [])]
        return Project(
            audio_path=str(data.get("audio_path", "")),
            duration=float(data.get("duration", 0)),
            language=str(data.get("language", "")),
            model=str(data.get("model", "")),
            segments=segments,
        )


def format_time(seconds, srt=False):
    """Превращает секунды в строку времени.

    format_time(75.5)            -> '01:15'
    format_time(3675.5)          -> '1:01:15'
    format_time(75.5, srt=True)  -> '00:01:15,500'
    """
    if seconds < 0:
        seconds = 0
    total_ms = int(round(seconds * 1000))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    if srt:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
