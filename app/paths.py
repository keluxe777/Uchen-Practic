"""Где лежат данные программы — и при запуске из Python, и в собранном exe."""

import os
import sys


def is_frozen():
    """True, если программа запущена как exe (собрана PyInstaller)."""
    return getattr(sys, "frozen", False)


def app_dir():
    """Папка программы: рядом с exe или корень проекта."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    """Файл, упакованный внутрь exe (иконка). В exe распаковывается во временную папку."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def data_dir():
    """Папка для истории расшифровок."""
    return os.path.join(app_dir(), "data")


def models_dir():
    """Папка для моделей распознавания.

    В exe модели хранятся рядом с ним, в папке models — так программу можно
    перенести на другой компьютер вместе с моделью и работать без интернета.
    При запуске из Python — общий кэш (None = стандартное место).
    """
    if is_frozen():
        return os.path.join(app_dir(), "models")
    return None
