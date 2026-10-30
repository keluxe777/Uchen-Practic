"""Сценарная проверка окна программы: нажимает кнопки вместо человека.

Окна сообщений и выбора файлов подменяются, их вызовы записываются в журнал.
Запуск из корня проекта: python tools/gui_check.py
"""

import os
import shutil
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gui  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "sample_en.wav")

log = []           # что программа показала пользователю
answers = []       # что «пользователь» ответит на следующие вопросы
next_files = []    # что «пользователь» выберет в окне выбора файла


def fake_box(kind):
    def box(title, message="", **kw):
        log.append((kind, title, message))
        if kind in ("askyesno", "askyesnocancel"):
            return answers.pop(0) if answers else False
        return "ok"
    return box


for name in ("showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel"):
    setattr(gui.messagebox, name, fake_box(name))
gui.filedialog.askopenfilename = lambda **kw: next_files.pop(0) if next_files else ""
gui.filedialog.asksaveasfilename = lambda **kw: next_files.pop(0) if next_files else ""


def pump(root, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def wait_worker(app, root, timeout=180):
    end = time.time() + timeout
    while (app.is_busy() or not app.messages.empty()) and time.time() < end:
        pump(root, 0.1)
    pump(root, 0.3)


results = []


def check(name, condition, details=""):
    results.append((name, bool(condition)))
    print(("OK   " if condition else "FAIL ") + name + (f"  — {details}" if details and not condition else ""))


def last_msg():
    return log[-1] if log else ("", "", "")


def main():
    tmp = tempfile.mkdtemp()
    root = tk.Tk()
    app = gui.App(root, history_path=os.path.join(tmp, "history.json"))
    pump(root)

    # 0. Все кнопки помещаются в окно (дефекты D-02, D-03, D-04)
    def visible(widget):
        x = widget.winfo_rootx() - root.winfo_rootx() + widget.winfo_width()
        y = widget.winfo_rooty() - root.winfo_rooty() + widget.winfo_height()
        return widget.winfo_ismapped() and x <= root.winfo_width() and y <= root.winfo_height()

    for size in ("1040x700", "820x560"):
        root.geometry(size)
        pump(root, 0.5)
        hidden = [w["text"] for w in (app.btn_run, app.btn_cancel, *app.export_buttons) if not visible(w)]
        check(f"Кнопки видны при размере {size}", not hidden, hidden)
    root.geometry("1040x700")

    # 1. Начальное состояние
    check("Кнопки неактивны без файла", str(app.btn_run["state"]) == "disabled"
          and str(app.export_buttons[0]["state"]) == "disabled")

    # 2. Неверные файлы
    txt = os.path.join(tmp, "notes.txt")
    with open(txt, "w") as f:
        f.write("hi")
    next_files.append(txt)
    app.open_audio()
    check("TXT отклонён", last_msg()[0] == "showerror" and "не поддерживается" in last_msg()[2], last_msg())

    broken = os.path.join(tmp, "broken.mp3")
    with open(broken, "wb") as f:
        f.write(b"garbage" * 500)
    next_files.append(broken)
    app.open_audio()
    check("Битый MP3 отклонён", last_msg()[0] == "showerror", last_msg())

    log.clear()
    next_files.append("")  # пользователь закрыл окно выбора
    app.open_audio()
    check("Отмена выбора файла без сообщений", not log)

    # 3. Нормальный файл
    sample = os.path.join(tmp, "sample_en.wav")
    shutil.copy(SAMPLE, sample)
    next_files.append(sample)
    app.open_audio()
    pump(root)
    check("Файл открыт, сведения показаны", "16" in app.info_label["text"] and "WAV" in app.info_label["text"],
          app.info_label["text"])
    check("Кнопка «Расшифровать» активна", str(app.btn_run["state"]) == "normal")

    # 4. Отмена расшифровки
    app.model_var.set(gui.MODELS["base"])
    app.start_transcription()
    pump(root, 0.2)
    app.cancel_transcription()
    wait_worker(app, root)
    check("Отмена расшифровки", "отменена" in app.status_label["text"] and not app.project.segments,
          app.status_label["text"])

    # 5. Расшифровка
    app.start_transcription()
    pump(root, 0.3)
    check("Во время работы кнопки заблокированы", str(app.btn_run["state"]) == "disabled"
          and str(app.btn_cancel["state"]) == "normal")
    wait_worker(app, root)
    segs = app.project.segments
    check("Расшифровка выполнена", len(segs) >= 2 and "test recording" in segs[0].text.lower(),
          [s.text for s in segs])
    check("Таблица заполнена", len(app.tree.get_children()) == len(segs))
    check("Есть статистика", "Слов" in app.stats_label["text"])
    check("Запись в истории", len(app.history.items) == 1)
    check("Прогресс 100%", app.progress["value"] == 100, app.progress["value"])

    # 6. Текст с таймкодами и без
    with_tc = app.text.get("1.0", "end")
    app.timecodes_var.set(False)
    app.refresh_text()
    without_tc = app.text.get("1.0", "end")
    check("Переключение таймкодов", "[00:00" in with_tc and "[" not in without_tc)
    app.timecodes_var.set(True)

    # 7. Поиск и замена
    app.find_var.set("pixel")
    app.find()
    check("Поиск находит фрагмент", "Найдено" in app.status_label["text"], app.status_label["text"])
    app.replace_var.set("Пиксель")
    app.replace_all()
    check("Замена", any("Пиксель" in s.text for s in app.project.segments), app.status_label["text"])
    app.find_var.set("   ")
    log.clear()
    app.find()
    check("Пустой поиск — подсказка", log and log[-1][0] == "showinfo")

    # 8. Удаление фрагмента
    before = len(app.project.segments)
    app.tree.selection_set(str(before - 1))
    answers.append(True)
    app.delete_segments()
    check("Удаление фрагмента", len(app.project.segments) == before - 1)

    # 9. Экспорт
    for kind in ("txt", "srt", "docx"):
        out = os.path.join(tmp, "out." + kind)
        next_files.append(out)
        answers.append(False)  # не открывать папку
        app.export(kind)
        check(f"Экспорт {kind.upper()}", os.path.isfile(out) and os.path.getsize(out) > 0)

    # 10. Сохранение и открытие проекта
    proj = os.path.join(tmp, "project.json")
    next_files.append(proj)
    app.save_project()
    check("Проект сохранён", os.path.isfile(proj) and not app.dirty)
    texts = [s.text for s in app.project.segments]
    check("Путь проекта в истории", app.history.items[0]["project_path"] == os.path.abspath(proj))

    # 11. Несохранённые изменения при открытии другого файла
    app.project.segments[0].text = "Изменено"
    app.mark_dirty()
    log.clear()
    answers.append(None)  # «Отмена» в вопросе о сохранении
    next_files.append(sample)
    app.open_audio()
    check("Вопрос о несохранённых изменениях", log and log[0][0] == "askyesnocancel"
          and app.project.segments[0].text == "Изменено")
    next_files.clear()  # окно выбора файла не открывалось — убираем неиспользованный ответ

    # 12. Открытие проекта из истории
    answers.append(False)  # не сохранять изменения
    app.hist_tree.selection_set("0")
    app.open_from_history()
    check("Открытие проекта из истории", [s.text for s in app.project.segments] == texts)

    # 12a. Горячие клавиши по коду клавиши (дефект D-01): Ctrl+O при любой раскладке
    class FakeEvent:
        keycode = 79
        keysym = "Cyrillic_shcha"  # так Tk называет клавишу O в русской раскладке
    log.clear()
    next_files.append("")
    before_files = len(next_files)
    app._on_ctrl_key(FakeEvent())
    check("Ctrl+O при русской раскладке открывает выбор файла", len(next_files) == before_files - 1)

    # 13. Повреждённый проект
    bad = os.path.join(tmp, "bad.json")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("{oops")
    next_files.append(bad)
    app.open_project()
    check("Повреждённый проект — ошибка", last_msg()[0] == "showerror" and app.project.segments,
          last_msg())

    # 14. Проект без аудиофайла
    os.remove(sample)
    next_files.append(proj)
    app.open_project()
    check("Проект без аудио открывается, расшифровка выключена",
          app.project.segments and str(app.btn_run["state"]) == "disabled"
          and "не найден" in app.info_label["text"], app.info_label["text"])

    root.destroy()
    shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    print(f"\nИтого: {len(results) - len(failed)} из {len(results)} проверок пройдено")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
