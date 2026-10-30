"""Точка входа: запуск расшифровщика аудио.

python main.py                               — обычный запуск окна
python main.py --selftest запись.wav out.txt — расшифровать без окна (проверка сборки exe)
"""

import sys
import tkinter as tk
from tkinter import messagebox


def selftest(audio_path, out_path):
    """Расшифровывает файл без окна и пишет результат в out_path (у exe нет консоли)."""
    with open(out_path, "w", encoding="utf-8") as out:
        try:
            from app.paths import models_dir
            from app.transcriber import Transcriber
            segments, lang, duration = Transcriber().transcribe(audio_path, "base", "auto")
            out.write(f"OK lang={lang} duration={duration:.1f} models_dir={models_dir()}\n")
            for s in segments:
                out.write(f"{s.start:.1f}-{s.end:.1f} {s.text}\n")
            return 0
        except Exception as exc:
            import traceback
            out.write("ERROR " + repr(exc) + "\n" + traceback.format_exc())
            return 1


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        sys.exit(selftest(sys.argv[2], sys.argv[3]))

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
