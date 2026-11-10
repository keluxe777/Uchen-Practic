"""Где лежат данные программы — и при запуске из Python, и в собранном exe."""

import os
import sys
import tempfile

from app import APP_NAME


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


def user_dir():
    """Личная папка программы: %LOCALAPPDATA%\\Расшифровщик аудио."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def is_onefile():
    """True для exe «одним файлом»: он распаковывается во временную папку, а не лежит рядом."""
    meipass = getattr(sys, "_MEIPASS", None)
    return bool(is_frozen() and meipass
                and os.path.normcase(os.path.dirname(os.path.abspath(meipass))) != os.path.normcase(app_dir()))


def is_writable(folder):
    """Можно ли создать файл в папке. Саму папку не создаёт: если её нет,
    проверяет ближайшую существующую папку выше."""
    folder = os.path.abspath(folder)
    while not os.path.exists(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            return False
        folder = parent
    try:
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


def _own_or_user(name):
    """Папка name рядом с exe. В личной папке пользователя — если туда писать нельзя
    (установка в Program Files) или это exe одним файлом (его часто запускают
    прямо из «Загрузок», и лишние папки рядом с ним ни к чему)."""
    own = os.path.join(app_dir(), name)
    if not is_frozen() or (not is_onefile() and is_writable(own)):
        return own
    return os.path.join(user_dir(), name)


def data_dir():
    """Папка для истории расшифровок и настроек."""
    return _own_or_user("data")


def bundled_models_dirs():
    """Где искать готовые модели, чтобы не скачивать их из интернета.

    - рядом с exe (установщик и zip-архив кладут туда base, туда же скачиваются другие);
    - внутри одиночного exe (base упакована в него и распаковывается при запуске).
    При запуске из Python — пусто: модели берутся из общего кэша.
    """
    if not is_frozen():
        return []
    return [os.path.join(app_dir(), "models"), resource_path("models")]


def models_dir():
    """Куда скачивать другие модели. При запуске из Python — общий кэш (None)."""
    if is_frozen():
        return _own_or_user("models")
    return None
