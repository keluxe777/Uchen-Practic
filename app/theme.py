"""Тема оформления: светлая, тёмная или как в системе."""

import sys

THEME_MODES = ("auto", "light", "dark")  # auto — как в Windows

_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def system_theme():
    """Тема приложений в настройках Windows: "dark" или "light".

    Windows хранит её в реестре: AppsUseLightTheme = 0 — тёмная, 1 — светлая.
    Если прочитать не удалось (старая Windows, другая ОС), считаем тему светлой.
    """
    if sys.platform != "win32":
        return "light"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
            value, _type = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"
    except OSError:
        return "light"


def normalize_mode(mode):
    """Режим из файла настроек; неизвестное значение — «как в системе»."""
    return mode if mode in THEME_MODES else "auto"


def resolve_theme(mode, system="light"):
    """Какую тему показать: в режиме auto — системную, иначе выбранную."""
    mode = normalize_mode(mode)
    if mode == "auto":
        return system if system in ("light", "dark") else "light"
    return mode
