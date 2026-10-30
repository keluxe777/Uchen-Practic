"""История расшифровок: последние файлы, чтобы быстро вернуться к ним."""

import json
import os
from datetime import datetime

MAX_ITEMS = 30


class History:
    def __init__(self, path):
        self.path = path
        self.items = []
        self.load()

    def load(self):
        """Читает историю. Если файл испорчен — начинаем с пустой истории."""
        self.items = []
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.items = [x for x in data if isinstance(x, dict) and "audio_path" in x]
        except (OSError, ValueError):
            self.items = []

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # история — не главное, программа работает и без неё

    def add(self, audio_path, duration, words, model, project_path=""):
        """Добавляет запись в начало списка (старая запись того же файла удаляется)."""
        self.items = [x for x in self.items if x.get("audio_path") != audio_path]
        self.items.insert(0, {
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "audio_path": audio_path,
            "duration": round(duration, 1),
            "words": words,
            "model": model,
            "project_path": project_path,
        })
        del self.items[MAX_ITEMS:]
        self.save()

    def set_project_path(self, audio_path, project_path):
        for x in self.items:
            if x.get("audio_path") == audio_path:
                x["project_path"] = project_path
        self.save()

    def remove(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            self.save()

    def clear(self):
        self.items = []
        self.save()
