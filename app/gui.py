"""Графический интерфейс расшифровщика (Tkinter)."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app import APP_NAME, APP_VERSION
from app.audio_utils import LONG_AUDIO_SECONDS, SUPPORTED_EXTENSIONS, AudioFileError, get_audio_info
from app.exporter import ExportError, export_docx, export_srt, export_txt, load_project, save_project, segments_to_text
from app.history import History
from app.models import Project, format_time
from app.paths import data_dir, resource_path
from app.text_tools import find_segments, get_stats, replace_in_segments
from app.transcriber import LANGUAGES, MODELS, ModelLoadError, Transcriber, TranscriptionCancelled

DATA_DIR = data_dir()  # в exe — папка data рядом с exe, иначе история терялась бы

AUDIO_FILETYPES = [
    ("Аудиофайлы", " ".join("*" + e for e in SUPPORTED_EXTENSIONS)),
    ("Все файлы", "*.*"),
]
PROJECT_FILETYPES = [("Проект расшифровки", "*.json"), ("Все файлы", "*.*")]


class App:
    def __init__(self, root, history_path=None):
        self.root = root
        self.transcriber = Transcriber()
        self.history = History(history_path or os.path.join(DATA_DIR, "history.json"))
        self.project = Project()
        self.audio_info = None
        self.project_path = ""
        self.dirty = False            # есть несохранённые изменения
        self.worker = None            # поток расшифровки
        self.cancel_event = threading.Event()
        self.messages = queue.Queue()  # сообщения из потока в окно

        root.title(f"{APP_NAME} {APP_VERSION}")
        root.geometry("1040x700")
        root.minsize(820, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            root.iconbitmap(default=resource_path("assets", "icon.ico"))
        except tk.TclError:
            pass  # без иконки программа тоже работает

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=26)
        style.configure("Title.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        self._build_menu()
        self._build_toolbar()
        self._build_bottom()  # нижнюю панель — до вкладок, иначе вкладки её вытесняют (дефект D-03)
        self._build_body()
        self._bind_keys()
        self.refresh_all()

    # ------------------------------------------------------------------ интерфейс

    def _build_menu(self):
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Открыть аудио…", accelerator="Ctrl+O", command=self.open_audio)
        file_menu.add_command(label="Открыть проект…", accelerator="Ctrl+P", command=self.open_project)
        file_menu.add_command(label="Сохранить проект", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Сохранить проект как…", command=lambda: self.save_project(ask=True))
        file_menu.add_separator()
        export_menu = tk.Menu(file_menu, tearoff=False)
        export_menu.add_command(label="Текст (TXT)…", command=lambda: self.export("txt"))
        export_menu.add_command(label="Субтитры (SRT)…", command=lambda: self.export("srt"))
        export_menu.add_command(label="Документ Word (DOCX)…", command=lambda: self.export("docx"))
        file_menu.add_cascade(label="Экспорт", menu=export_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.on_close)
        menu.add_cascade(label="Файл", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Как пользоваться", command=self.show_help)
        help_menu.add_command(label="О программе", command=self.show_about)
        menu.add_cascade(label="Справка", menu=help_menu)
        self.root.config(menu=menu)

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill="x")
        ttk.Button(bar, text="Открыть аудио", command=self.open_audio).pack(side="left")
        ttk.Button(bar, text="Открыть проект", command=self.open_project).pack(side="left", padx=(6, 0))
        self.btn_save = ttk.Button(bar, text="Сохранить проект", command=self.save_project)
        self.btn_save.pack(side="left", padx=(6, 0))

        # Вторая строка: настройки и запуск (в одну строку не помещалось — дефект D-02)
        run_bar = ttk.Frame(self.root, padding=(10, 2, 10, 4))
        run_bar.pack(fill="x")
        ttk.Label(run_bar, text="Модель:").pack(side="left")
        self.model_var = tk.StringVar(value=MODELS["base"])
        self.model_box = ttk.Combobox(run_bar, textvariable=self.model_var, values=list(MODELS.values()),
                                      state="readonly", width=34)
        self.model_box.pack(side="left", padx=(4, 10))
        ttk.Label(run_bar, text="Язык:").pack(side="left")
        self.lang_var = tk.StringVar(value=LANGUAGES["auto"])
        self.lang_box = ttk.Combobox(run_bar, textvariable=self.lang_var, values=list(LANGUAGES.values()),
                                     state="readonly", width=27)
        self.lang_box.pack(side="left", padx=(4, 10))
        self.btn_run = ttk.Button(run_bar, text="▶  Расшифровать", style="Accent.TButton",
                                  command=self.start_transcription)
        self.btn_run.pack(side="left", padx=(4, 0))
        self.btn_cancel = ttk.Button(run_bar, text="Отмена", command=self.cancel_transcription)
        self.btn_cancel.pack(side="left", padx=(6, 0))

        info = ttk.Frame(self.root, padding=(10, 2, 10, 2))
        info.pack(fill="x")
        self.file_label = ttk.Label(info, text="", style="Title.TLabel")
        self.file_label.pack(anchor="w")
        self.info_label = ttk.Label(info, text="", foreground="#555")
        self.info_label.pack(anchor="w")

        prog = ttk.Frame(self.root, padding=(10, 4, 10, 4))
        prog.pack(fill="x")
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.status_label = ttk.Label(prog, text="", foreground="#555")
        self.status_label.pack(anchor="w", pady=(2, 0))

    def _build_body(self):
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=4)

        # --- вкладка «Фрагменты»: таблица с таймкодами, поиск и замена
        seg_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(seg_tab, text="Фрагменты с таймкодами")

        search = ttk.Frame(seg_tab)
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="Найти:").pack(side="left")
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(search, textvariable=self.find_var, width=18)
        self.find_entry.pack(side="left", padx=(4, 4))
        ttk.Button(search, text="Найти", command=self.find).pack(side="left", padx=(0, 12))
        ttk.Label(search, text="Заменить на:").pack(side="left")
        self.replace_var = tk.StringVar()
        ttk.Entry(search, textvariable=self.replace_var, width=18).pack(side="left", padx=(4, 4))
        ttk.Button(search, text="Заменить всё", command=self.replace_all).pack(side="left", padx=(0, 12))
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search, text="Учитывать регистр", variable=self.case_var).pack(side="left")

        # Кнопки под таблицей пакуем раньше таблицы, чтобы они не обрезались (дефект D-04)
        seg_buttons = ttk.Frame(seg_tab)
        seg_buttons.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(seg_buttons, text="Изменить фрагмент", command=self.edit_segment).pack(side="left")
        ttk.Button(seg_buttons, text="Удалить фрагмент", command=self.delete_segments).pack(side="left", padx=6)
        ttk.Label(seg_buttons, text="Двойной щелчок по строке — редактировать текст",
                  foreground="#777").pack(side="left", padx=10)

        table = ttk.Frame(seg_tab)
        table.pack(fill="both", expand=True)
        cols = ("num", "start", "end", "text")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", selectmode="extended")
        for col, title, width, stretch in (("num", "№", 44, False), ("start", "Начало", 74, False),
                                           ("end", "Конец", 74, False), ("text", "Текст", 600, True)):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=stretch, anchor="w" if col == "text" else "center")
        self.tree.tag_configure("found", background="#fff3b0")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.edit_segment())

        # --- вкладка «Текст»: сплошной текст для чтения и копирования
        text_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(text_tab, text="Текст")
        top = ttk.Frame(text_tab)
        top.pack(fill="x", pady=(0, 6))
        self.timecodes_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Показывать таймкоды", variable=self.timecodes_var,
                        command=self.refresh_text).pack(side="left")
        ttk.Button(top, text="Копировать весь текст", command=self.copy_text).pack(side="right")
        text_frame = ttk.Frame(text_tab)
        text_frame.pack(fill="both", expand=True)
        self.text = tk.Text(text_frame, wrap="word", font=("Segoe UI", 11), padx=10, pady=8,
                            relief="flat", background="#fbfbfb")
        tscroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=tscroll.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        tscroll.pack(side="right", fill="y")

        # --- вкладка «История»
        hist_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(hist_tab, text="История")
        hcols = ("date", "file", "duration", "words", "model", "project")
        self.hist_tree = ttk.Treeview(hist_tab, columns=hcols, show="headings", selectmode="browse")
        for col, title, width in (("date", "Дата", 120), ("file", "Файл", 300), ("duration", "Длительность", 100),
                                  ("words", "Слов", 60), ("model", "Модель", 70), ("project", "Проект", 220)):
            self.hist_tree.heading(col, text=title)
            self.hist_tree.column(col, width=width, anchor="w" if col in ("file", "project") else "center")
        self.hist_tree.pack(fill="both", expand=True)
        self.hist_tree.bind("<Double-1>", lambda e: self.open_from_history())
        hb = ttk.Frame(hist_tab)
        hb.pack(fill="x", pady=(6, 0))
        ttk.Button(hb, text="Открыть", command=self.open_from_history).pack(side="left")
        ttk.Button(hb, text="Удалить из истории", command=self.remove_from_history).pack(side="left", padx=6)
        ttk.Button(hb, text="Очистить историю", command=self.clear_history).pack(side="left")

    def _build_bottom(self):
        bottom = ttk.Frame(self.root, padding=(10, 4, 10, 10))
        bottom.pack(side="bottom", fill="x")
        ttk.Label(bottom, text="Экспорт:").pack(side="left")
        self.export_buttons = []
        for label, kind in (("TXT", "txt"), ("SRT (субтитры)", "srt"), ("Word (DOCX)", "docx")):
            b = ttk.Button(bottom, text=label, command=lambda k=kind: self.export(k))
            b.pack(side="left", padx=(6, 0))
            self.export_buttons.append(b)
        self.stats_label = ttk.Label(bottom, text="", foreground="#555")
        self.stats_label.pack(side="right")

    def _bind_keys(self):
        # Привязка по коду клавиши, а не по букве: так Ctrl+O/P/S работают
        # и при русской раскладке (дефект D-01)
        self.root.bind("<Control-KeyPress>", self._on_ctrl_key)
        self.root.bind("<F5>", lambda e: self.start_transcription())
        self.find_entry.bind("<Return>", lambda e: self.find())
        self.tree.bind("<Delete>", lambda e: self.delete_segments())

    def _on_ctrl_key(self, event):
        actions = {79: self.open_audio, 80: self.open_project, 83: self.save_project}  # O, P, S
        action = actions.get(event.keycode)
        if action:
            action()
            return "break"
        return None

    # ------------------------------------------------------------------ обновление экрана

    def refresh_all(self):
        self.refresh_file_info()
        self.refresh_table()
        self.refresh_text()
        self.refresh_history()
        self.refresh_buttons()
        self.refresh_stats()

    def refresh_file_info(self):
        p = self.project
        if not p.audio_path:
            self.file_label.config(text="Файл не выбран")
            self.info_label.config(text="Нажмите «Открыть аудио» (Ctrl+O) и выберите запись: "
                                        "WAV, MP3, M4A, OGG, FLAC и др.")
            return
        name = os.path.basename(p.audio_path)
        title = name + ("  •  проект: " + os.path.basename(self.project_path) if self.project_path else "")
        self.file_label.config(text=title + ("  (изменён)" if self.dirty else ""))
        if self.audio_info:
            i = self.audio_info
            self.info_label.config(text=f"Формат: {i['format']}   •   Длительность: {format_time(i['duration'])}   •   "
                                        f"Размер: {i['size_mb']:.1f} МБ   •   {i['sample_rate']} Гц, "
                                        f"каналов: {i['channels']}")
        elif not os.path.isfile(p.audio_path):
            self.info_label.config(text="Исходный аудиофайл не найден — текст доступен для правки и экспорта, "
                                        "но повторная расшифровка невозможна.")
        else:
            self.info_label.config(text=f"Длительность: {format_time(p.duration)}")

    def refresh_table(self, found=()):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.project.segments):
            tags = ("found",) if i in found else ()
            self.tree.insert("", "end", iid=str(i), values=(i + 1, format_time(s.start), format_time(s.end), s.text),
                             tags=tags)

    def refresh_text(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if self.project.segments:
            self.text.insert("1.0", segments_to_text(self.project.segments, self.timecodes_var.get()))
        self.text.configure(state="disabled")

    def refresh_history(self):
        self.hist_tree.delete(*self.hist_tree.get_children())
        for i, h in enumerate(self.history.items):
            project = os.path.basename(h.get("project_path", "")) or "—"
            self.hist_tree.insert("", "end", iid=str(i), values=(
                h.get("date", ""), os.path.basename(h.get("audio_path", "")),
                format_time(h.get("duration", 0)), h.get("words", 0), h.get("model", ""), project))

    def refresh_buttons(self):
        busy = self.is_busy()
        has_audio = bool(self.project.audio_path) and os.path.isfile(self.project.audio_path)
        has_text = bool(self.project.segments)
        self.btn_run.config(state="normal" if has_audio and not busy else "disabled")
        self.btn_cancel.config(state="normal" if busy else "disabled")
        self.btn_save.config(state="normal" if has_text and not busy else "disabled")
        for b in self.export_buttons:
            b.config(state="normal" if has_text and not busy else "disabled")
        self.model_box.config(state="disabled" if busy else "readonly")
        self.lang_box.config(state="disabled" if busy else "readonly")

    def refresh_stats(self):
        if not self.project.segments:
            self.stats_label.config(text="")
            return
        st = get_stats(self.project.segments, self.project.duration)
        self.stats_label.config(text=f"Фрагментов: {st['segments']}   •   Слов: {st['words']}   •   "
                                     f"Символов: {st['chars']}   •   Темп речи: {st['words_per_minute']} сл/мин")

    def set_status(self, text):
        self.status_label.config(text=text)

    def mark_dirty(self):
        self.dirty = True
        self.refresh_file_info()

    # ------------------------------------------------------------------ функция 1: открыть аудио

    def open_audio(self, path=None):
        if self.is_busy() or not self.confirm_discard():
            return
        if path is None:
            path = filedialog.askopenfilename(title="Выберите аудиозапись", filetypes=AUDIO_FILETYPES)
            if not path:
                return  # пользователь закрыл окно выбора
        try:
            info = get_audio_info(path)
        except AudioFileError as exc:
            messagebox.showerror("Файл не подходит", str(exc))
            return
        self.project = Project(audio_path=os.path.abspath(path), duration=info["duration"])
        self.audio_info = info
        self.project_path = ""
        self.dirty = False
        self.progress.config(value=0)
        self.set_status("Файл загружен. Выберите модель и язык, затем нажмите «Расшифровать» (F5).")
        self.refresh_all()
        self.tabs.select(0)
        if info["duration"] > LONG_AUDIO_SECONDS:
            messagebox.showwarning("Длинная запись",
                                   f"Запись длится {format_time(info['duration'])}. На этом компьютере "
                                   "расшифровка может занять много времени. Для начала выберите модель tiny.")

    # ------------------------------------------------------------------ функция 2: расшифровка

    def selected_model(self):
        for key, title in MODELS.items():
            if title == self.model_var.get():
                return key
        return "base"

    def selected_language(self):
        for key, title in LANGUAGES.items():
            if title == self.lang_var.get():
                return key
        return "auto"

    def is_busy(self):
        return self.worker is not None and self.worker.is_alive()

    def start_transcription(self):
        if self.is_busy():
            return
        path = self.project.audio_path
        if not path:
            messagebox.showinfo("Нет файла", "Сначала откройте аудиофайл.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Нет файла", f"Аудиофайл не найден:\n{path}")
            return
        if self.project.segments and not messagebox.askyesno(
                "Повторная расшифровка", "Текущий текст и все правки будут заменены новой расшифровкой. Продолжить?"):
            return
        model, language = self.selected_model(), self.selected_language()
        self.project.segments = []
        self.refresh_table()
        self.refresh_text()
        self.refresh_stats()
        self.cancel_event.clear()
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self.set_status(f"Загрузка модели «{model}»… При первом запуске она скачивается из интернета.")
        self.worker = threading.Thread(target=self._worker, args=(path, model, language), daemon=True)
        self.worker.start()
        self.refresh_buttons()
        self.root.after(100, self._poll_worker)

    def _worker(self, path, model, language):
        """Работает в отдельном потоке, чтобы окно не зависало."""
        try:
            self.transcriber.load_model(model)
            self.messages.put(("started", None))
            segments, lang, duration = self.transcriber.transcribe(
                path, model, language,
                on_progress=lambda frac, seg: self.messages.put(("progress", (frac, seg))),
                cancel_event=self.cancel_event)
            self.messages.put(("done", (segments, lang, duration, model)))
        except TranscriptionCancelled:
            self.messages.put(("cancelled", None))
        except ModelLoadError as exc:
            self.messages.put(("error", str(exc)))
        except Exception as exc:
            self.messages.put(("error", f"Ошибка при расшифровке:\n{exc}"))

    def _poll_worker(self):
        try:
            while True:
                kind, data = self.messages.get_nowait()
                self._handle_message(kind, data)
        except queue.Empty:
            pass
        if self.is_busy() or not self.messages.empty():
            self.root.after(100, self._poll_worker)
        else:
            self.refresh_buttons()

    def _handle_message(self, kind, data):
        if kind == "started":
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self.set_status("Идёт расшифровка… Можно нажать «Отмена».")
        elif kind == "progress":
            frac, seg = data
            self.progress.config(value=frac * 100)
            self.project.segments.append(seg)
            i = len(self.project.segments) - 1
            self.tree.insert("", "end", iid=str(i), values=(i + 1, format_time(seg.start), format_time(seg.end),
                                                             seg.text))
            self.tree.see(str(i))
            self.set_status(f"Идёт расшифровка… {int(frac * 100)}%")
        elif kind == "done":
            segments, lang, duration, model = data
            self.progress.stop()
            self.progress.config(mode="determinate", value=100)
            self.project.segments = segments
            self.project.language = lang or ""
            self.project.model = model
            if duration:
                self.project.duration = duration
            self.project_path = ""
            self.refresh_all()
            if not segments:
                self.set_status("Готово, но речь не найдена.")
                messagebox.showinfo("Речь не найдена", "В записи не удалось распознать речь. "
                                                       "Проверьте, что в файле есть голос, или выберите другой язык.")
                return
            self.mark_dirty()
            words = get_stats(segments, duration)["words"]
            self.history.add(self.project.audio_path, self.project.duration, words, model)
            self.refresh_history()
            lang_name = LANGUAGES.get(lang, lang)
            self.set_status(f"Готово: {len(segments)} фрагментов, язык — {lang_name}. "
                            "Проверьте текст и сохраните проект или экспортируйте результат.")
        elif kind == "cancelled":
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self.project.segments = []
            self.refresh_all()
            self.set_status("Расшифровка отменена.")
        elif kind == "error":
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
            self.project.segments = []
            self.refresh_all()
            self.set_status("Ошибка — см. сообщение.")
            messagebox.showerror("Ошибка", data)

    def cancel_transcription(self):
        if self.is_busy():
            self.cancel_event.set()
            self.set_status("Отмена… дождитесь окончания текущего фрагмента.")

    # ------------------------------------------------------------------ функции 3–4: таймкоды и редактирование

    def selected_indexes(self):
        return sorted(int(iid) for iid in self.tree.selection())

    def edit_segment(self):
        if self.is_busy():
            return
        idx = self.selected_indexes()
        if not idx:
            messagebox.showinfo("Редактирование", "Выберите фрагмент в таблице.")
            return
        i = idx[0]
        seg = self.project.segments[i]

        win = tk.Toplevel(self.root)
        win.title(f"Фрагмент №{i + 1}  [{format_time(seg.start)} – {format_time(seg.end)}]")
        win.transient(self.root)
        win.grab_set()
        win.geometry("560x240")
        box = tk.Text(win, wrap="word", font=("Segoe UI", 11), height=6, padx=8, pady=6)
        box.insert("1.0", seg.text)
        box.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        box.focus_set()

        def ok(_event=None):
            new_text = " ".join(box.get("1.0", "end").split())
            if not new_text:
                messagebox.showwarning("Пустой текст", "Текст фрагмента не может быть пустым. "
                                                       "Чтобы убрать фрагмент, используйте «Удалить фрагмент».",
                                       parent=win)
                return
            if new_text != seg.text:
                seg.text = new_text
                self.after_edit(select=i)
            win.destroy()

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(buttons, text="Отмена", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить", command=ok).pack(side="right", padx=6)
        win.bind("<Control-Return>", ok)
        win.bind("<Escape>", lambda e: win.destroy())

    def delete_segments(self):
        if self.is_busy():
            return
        idx = self.selected_indexes()
        if not idx:
            messagebox.showinfo("Удаление", "Выберите фрагменты в таблице.")
            return
        if not messagebox.askyesno("Удаление", f"Удалить выбранные фрагменты ({len(idx)} шт.)?"):
            return
        for i in reversed(idx):
            del self.project.segments[i]
        self.after_edit()

    def after_edit(self, select=None):
        self.mark_dirty()
        self.refresh_table()
        self.refresh_text()
        self.refresh_stats()
        self.refresh_buttons()
        if select is not None and str(select) in self.tree.get_children():
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    # ------------------------------------------------------------------ функция 5: поиск и замена

    def find(self):
        query = self.find_var.get()
        if not query.strip():
            messagebox.showinfo("Поиск", "Введите текст для поиска.")
            return
        found = find_segments(self.project.segments, query, self.case_var.get())
        self.refresh_table(found=set(found))
        if found:
            self.tree.see(str(found[0]))
            self.tree.selection_set(str(found[0]))
            self.set_status(f"Найдено во фрагментах: {len(found)} (подсвечены жёлтым).")
        else:
            self.set_status(f"«{query}» не найдено.")

    def replace_all(self):
        if self.is_busy():
            return
        query = self.find_var.get()
        if not query.strip():
            messagebox.showinfo("Замена", "Введите, что нужно заменить, в поле «Найти».")
            return
        count = replace_in_segments(self.project.segments, query, self.replace_var.get(), self.case_var.get())
        if count:
            self.after_edit()
        self.set_status(f"Замен выполнено: {count}.")
        if not count:
            messagebox.showinfo("Замена", f"«{query}» не найдено.")

    # ------------------------------------------------------------------ функция 6: экспорт

    def default_name(self):
        if self.project.audio_path:
            return os.path.splitext(os.path.basename(self.project.audio_path))[0]
        return "расшифровка"

    def export(self, kind):
        if self.is_busy():
            return
        if not self.project.segments:
            messagebox.showinfo("Экспорт", "Нечего сохранять: сначала расшифруйте запись.")
            return
        types = {"txt": ("Текст", "*.txt"), "srt": ("Субтитры", "*.srt"), "docx": ("Документ Word", "*.docx")}
        path = filedialog.asksaveasfilename(title="Сохранить как", defaultextension="." + kind,
                                            initialfile=self.default_name() + "." + kind,
                                            filetypes=[types[kind]])
        if not path:
            return
        try:
            if kind == "txt":
                export_txt(self.project.segments, path, self.timecodes_var.get())
            elif kind == "srt":
                export_srt(self.project.segments, path)
            else:
                export_docx(self.project.segments, path, source_name=os.path.basename(self.project.audio_path),
                            with_timecodes=self.timecodes_var.get())
        except ExportError as exc:
            messagebox.showerror("Не удалось сохранить", str(exc))
            return
        self.set_status(f"Сохранено: {path}")
        if messagebox.askyesno("Готово", f"Файл сохранён:\n{path}\n\nОткрыть папку с файлом?"):
            os.startfile(os.path.dirname(path))

    def copy_text(self):
        if not self.project.segments:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(segments_to_text(self.project.segments, self.timecodes_var.get()))
        self.set_status("Текст скопирован в буфер обмена.")

    # ------------------------------------------------------------------ функция 7: проекты и история

    def save_project(self, ask=False):
        if self.is_busy():
            return False
        if not self.project.segments:
            messagebox.showinfo("Сохранение", "Нечего сохранять: сначала расшифруйте запись.")
            return False
        path = self.project_path
        if ask or not path:
            path = filedialog.asksaveasfilename(title="Сохранить проект", defaultextension=".json",
                                                initialfile=self.default_name() + ".json",
                                                filetypes=PROJECT_FILETYPES)
            if not path:
                return False
        try:
            save_project(self.project, path)
        except ExportError as exc:
            messagebox.showerror("Не удалось сохранить", str(exc))
            return False
        self.project_path = os.path.abspath(path)
        self.dirty = False
        self.history.set_project_path(self.project.audio_path, self.project_path)
        self.refresh_history()
        self.refresh_file_info()
        self.set_status(f"Проект сохранён: {path}")
        return True

    def open_project(self, path=None):
        if self.is_busy() or not self.confirm_discard():
            return
        if path is None:
            path = filedialog.askopenfilename(title="Открыть проект", filetypes=PROJECT_FILETYPES)
            if not path:
                return
        try:
            project = load_project(path)
        except ExportError as exc:
            messagebox.showerror("Не удалось открыть проект", str(exc))
            return
        self.project = project
        self.project_path = os.path.abspath(path)
        self.dirty = False
        try:
            self.audio_info = get_audio_info(project.audio_path) if project.audio_path else None
        except AudioFileError:
            self.audio_info = None
        self.progress.config(value=0)
        self.refresh_all()
        self.tabs.select(0)
        self.set_status(f"Проект открыт: {len(project.segments)} фрагментов.")

    def selected_history_index(self):
        sel = self.hist_tree.selection()
        return int(sel[0]) if sel else None

    def open_from_history(self):
        i = self.selected_history_index()
        if i is None:
            messagebox.showinfo("История", "Выберите запись в истории.")
            return
        item = self.history.items[i]
        project_path = item.get("project_path", "")
        if project_path and os.path.isfile(project_path):
            self.open_project(project_path)
        elif os.path.isfile(item.get("audio_path", "")):
            self.open_audio(item["audio_path"])
        else:
            if messagebox.askyesno("Файл не найден", "Ни проект, ни аудиофайл больше не существуют.\n"
                                                     "Удалить запись из истории?"):
                self.history.remove(i)
                self.refresh_history()

    def remove_from_history(self):
        i = self.selected_history_index()
        if i is None:
            messagebox.showinfo("История", "Выберите запись в истории.")
            return
        self.history.remove(i)
        self.refresh_history()

    def clear_history(self):
        if self.history.items and messagebox.askyesno("История", "Очистить всю историю расшифровок?"):
            self.history.clear()
            self.refresh_history()

    # ------------------------------------------------------------------ прочее

    def confirm_discard(self):
        """Спрашивает о несохранённых изменениях. True — можно продолжать."""
        if not self.dirty or not self.project.segments:
            return True
        answer = messagebox.askyesnocancel("Несохранённые изменения",
                                           "Расшифровка не сохранена. Сохранить проект?")
        if answer is None:
            return False
        if answer:
            return self.save_project()
        return True

    def on_close(self):
        if self.is_busy():
            if not messagebox.askyesno("Идёт расшифровка", "Расшифровка ещё не закончена. Прервать и выйти?"):
                return
            self.cancel_event.set()
        elif not self.confirm_discard():
            return
        self.root.destroy()

    def show_help(self):
        messagebox.showinfo("Как пользоваться", (
            "1. «Открыть аудио» (Ctrl+O) — выберите запись.\n"
            "2. Выберите модель и язык, нажмите «Расшифровать» (F5).\n"
            "3. Проверьте текст: двойной щелчок по фрагменту — правка, Delete — удаление.\n"
            "4. «Найти» и «Заменить всё» — исправление повторяющихся ошибок.\n"
            "5. Сохраните проект (Ctrl+S), чтобы продолжить позже.\n"
            "6. Экспортируйте результат в TXT, SRT или Word.\n"
            "7. Вкладка «История» — быстрый доступ к прошлым расшифровкам."))

    def show_about(self):
        messagebox.showinfo("О программе", (
            f"{APP_NAME}, версия {APP_VERSION}\n\n"
            "Учебный проект компании «Пиксель и Код».\n"
            "Распознавание речи: модель Whisper (библиотека faster-whisper), "
            "работает на компьютере без отправки записей в интернет."))


def run():
    root = tk.Tk()
    App(root)
    root.mainloop()
