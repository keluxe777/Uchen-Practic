"""Точка входа: запуск расшифровщика аудио."""

import sys
import tkinter as tk
from tkinter import messagebox


def main():
    try:
        import faster_whisper  # noqa: F401  проверяем, что библиотеки установлены
        import docx  # noqa: F401
    except ImportError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Не хватает библиотек",
                             f"Не установлена библиотека: {exc.name}\n\n"
                             "Запустите install.bat (или: pip install -r requirements.txt).")
        sys.exit(1)

    from app.gui import run
    run()


if __name__ == "__main__":
    main()
