"""Графический интерфейс расшифровщика (Tkinter + тема Sun Valley в стиле Windows 11)."""

import ctypes
import json
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
from app.transcriber import LANGUAGES, MODELS, ModelLoadError, Transcriber, TranscriptionCancelled, language_name

try:
    import sv_ttk  # тема оформления в стиле Windows 11
except ImportError:  # без неё программа работает со стандартным видом
    sv_ttk = None

DATA_DIR = data_dir()  # в exe — папка data рядом с exe, иначе история терялась бы

AUDIO_FILETYPES = [
    ("Аудиофайлы", " ".join("*" + e for e in SUPPORTED_EXTENSIONS)),
    ("Все файлы", "*.*"),
]
PROJECT_FILETYPES = [("Проект расшифровки", "*.json"), ("Все файлы", "*.*")]

# Цвета, которые тема не задаёт сама (подсветка поиска, полосы таблицы, текст)
PALETTE = {
    "light": {"muted": "#5f6368", "found": "#fff1b8", "odd": "#ffffff", "even": "#f5f6f8",
              "text_bg": "#ffffff", "text_fg": "#1b1b1b", "accent": "#005fb8"},
    "dark": {"muted": "#a3a3a3", "found": "#5a4a14", "odd": "#1f1f1f", "even": "#262626",
             "text_bg": "#232323", "text_fg": "#ececec", "accent": "#60cdff"},
}
FONT = "Segoe UI"


def enable_dpi_awareness():
    """Чёткий текст на экранах с масштабом 125–150% (без этого Windows размывает окно)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class App:
    def __init__(self, root, history_path=None):
        self.root = root
        self.transcriber = Transcriber()
        history_path = history_path or os.path.join(DATA_DIR, "history.json")
        self.history = History(history_path)
        self.settings_path = os.path.join(os.path.dirname(history_path), "settings.json")
        self.project = Project()
        self.audio_info = None
        self.project_path = ""
        self.dirty = False             # есть несохранённые изменения
        self.worker = None             # поток расшифровки
        self.cancel_event = threading.Event()
        self.messages = queue.Queue()  # сообщения из потока в окно
        self.found = set()             # фрагменты, найденные поиском

        # Масштаб экрана: размеры окна задаём в «обычных» пикселях и умножаем
        self.scale = max(root.winfo_fpixels("1i") / 96, 1.0)
        root.title(f"{APP_NAME} {APP_VERSION}")
        root.geometry(f"{self.px(1120)}x{self.px(740)}")
        root.minsize(self.px(900), self.px(600))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        try:
            root.iconbitmap(default=resource_path("assets", "icon.ico"))
        except tk.TclError:
            pass  # без иконки программа тоже работает

        self.theme = self.load_settings().get("theme", "light")
        self.style = ttk.Style()
        self.apply_theme(self.theme, first=True)

        self._build_sidebar()
        ttk.Separator(root, orient="vertical").pack(side="left", fill="y")
        self._build_main()
        self._bind_keys()
        self.apply_theme(self.theme)
        self.refresh_all()

    def px(self, value):
        return int(value * self.scale)

    # ------------------------------------------------------------------ тема

    def colors(self):
        return PALETTE[self.theme]

    def apply_theme(self, theme, first=False):
        self.theme = theme if theme in PALETTE else "light"
        if sv_ttk is not None:
            sv_ttk.set_theme(self.theme)
        elif first and "vista" in self.style.theme_names():
            self.style.theme_use("vista")
        c = self.colors()
        st = self.style
        st.configure("Treeview", rowheight=self.px(30), font=(FONT, 10))
        st.configure("Treeview.Heading", font=(FONT, 10, "bold"))
        st.configure("AppTitle.TLabel", font=(FONT, 13, "bold"))
        st.configure("AppSub.TLabel", font=(FONT, 9), foreground=c["muted"])
        st.configure("Caption.TLabel", font=(FONT, 8, "bold"), foreground=c["muted"])
        st.configure("FileName.TLabel", font=(FONT, 14, "bold"))
        st.configure("Muted.TLabel", font=(FONT, 9), foreground=c["muted"])
        st.configure("Status.TLabel", font=(FONT, 9), foreground=c["muted"])
        st.configure("Side.TButton", anchor="w", padding=(self.px(12), self.px(7)))
        st.configure("Run.Accent.TButton", font=(FONT, 10, "bold"), padding=(self.px(18), self.px(6)))
        if first:
            return
        for widget in (self.text,):
            widget.configure(background=c["text_bg"], foreground=c["text_fg"],
                             insertbackground=c["text_fg"], selectbackground=c["accent"])
        self.tree.tag_configure("found", background=c["found"])
        self.tree.tag_configure("odd", background=c["odd"])
        self.tree.tag_configure("even", background=c["even"])
        self.hist_tree.tag_configure("odd", background=c["odd"])
        self.hist_tree.tag_configure("even", background=c["even"])
        tree_bg = self.style.lookup("Treeview", "background") or c["odd"]
        for ph in (self.placeholder, self.hist_placeholder):
            ph.configure(background=tree_bg, foreground=c["muted"])
        self.theme_var.set(self.theme == "dark")

    def toggle_theme(self):
        self.apply_theme("dark" if self.theme_var.get() else "light")
        self.save_settings({"theme": self.theme})

    def load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self, data):
        try:
            os.makedirs(os.path.dirname(self.settings_path) or ".", exist_ok=True)
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    # ------------------------------------------------------------------ боковая панель

    def _build_sidebar(self):
        side = ttk.Frame(self.root, padding=(self.px(16), self.px(18), self.px(16), self.px(16)),
                         width=self.px(230))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        logo = ttk.Frame(side)
        logo.pack(fill="x", pady=(0, self.px(22)))
        try:
            img = tk.PhotoImage(file=resource_path("assets", "icon.png"))
            factor = max(1, round(img.width() / self.px(40)))
            self.logo_img = img.subsample(factor, factor)
            ttk.Label(logo, image=self.logo_img).pack(side="left", padx=(0, self.px(10)))
        except tk.TclError:
            pass
        names = ttk.Frame(logo)
        names.pack(side="left", fill="x")
        ttk.Label(names, text="Расшифровщик", style="AppTitle.TLabel").pack(anchor="w")
        ttk.Label(names, text="аудио → текст", style="AppSub.TLabel").pack(anchor="w")

        def section(title):
            ttk.Label(side, text=title, style="Caption.TLabel").pack(anchor="w", pady=(self.px(14), self.px(6)))

        def button(text, command):
            b = ttk.Button(side, text=text, style="Side.TButton", command=command)
            b.pack(fill="x", pady=self.px(3))
            return b

        section("ФАЙЛ")
        button("Открыть аудио…", self.open_audio)
        button("Открыть проект…", self.open_project)
        self.btn_save = button("Сохранить проект", self.save_project)

        section("ЭКСПОРТ")
        self.export_buttons = [
            button("Текст  (TXT)", lambda: self.export("txt")),
            button("Субтитры  (SRT)", lambda: self.export("srt")),
            button("Документ Word  (DOCX)", lambda: self.export("docx")),
        ]

        bottom = ttk.Frame(side)
        bottom.pack(side="bottom", fill="x")
        self.theme_var = tk.BooleanVar(value=self.theme == "dark")
        ttk.Checkbutton(bottom, text="Тёмная тема", variable=self.theme_var, command=self.toggle_theme,
                        style="Switch.TCheckbutton" if sv_ttk else "TCheckbutton").pack(anchor="w",
                                                                                         pady=(0, self.px(10)))
        links = ttk.Frame(bottom)
        links.pack(fill="x")
        ttk.Button(links, text="Справка  F1", command=self.show_help).pack(side="left", fill="x", expand=True)
        ttk.Button(links, text="О программе", command=self.show_about).pack(side="left", fill="x", expand=True,
                                                                          padx=(self.px(6), 0))

    # ------------------------------------------------------------------ основная область

    def _build_main(self):
        main = ttk.Frame(self.root, padding=(self.px(20), self.px(18), self.px(20), self.px(10)))
        main.pack(side="left", fill="both", expand=True)

        # --- карточка файла: имя, сведения, настройки и запуск
        card = ttk.Frame(main, style="Card.TFrame" if sv_ttk else "TFrame",
                         padding=(self.px(18), self.px(14), self.px(18), self.px(14)))
        card.pack(fill="x")
        # Верх карточки: слева имя файла, справа кнопки запуска (кнопки пакуем первыми,
        # чтобы длинное имя файла не вытесняло их из окна)
        header = ttk.Frame(card)
        header.pack(fill="x", pady=(0, self.px(12)))
        self.btn_cancel = ttk.Button(header, text="Отмена", command=self.cancel_transcription)
        self.btn_cancel.pack(side="right", anchor="n")
        self.btn_run = ttk.Button(header, text="▶  Расшифровать", command=self.start_transcription,
                                  style="Run.Accent.TButton" if sv_ttk else "TButton")
        self.btn_run.pack(side="right", anchor="n", padx=(self.px(16), self.px(8)))
        names = ttk.Frame(header)
        names.pack(side="left", fill="x", expand=True)
        self.file_label = ttk.Label(names, text="", style="FileName.TLabel")
        self.file_label.pack(anchor="w")
        self.info_label = ttk.Label(names, text="", style="Muted.TLabel")
        self.info_label.pack(anchor="w", pady=(self.px(2), 0))

        run_bar = ttk.Frame(card)
        run_bar.pack(fill="x")
        ttk.Label(run_bar, text="Модель").pack(side="left")
        self.model_var = tk.StringVar(value=MODELS["base"])
        self.model_box = ttk.Combobox(run_bar, textvariable=self.model_var, values=list(MODELS.values()),
                                      state="readonly", width=34)
        self.model_box.pack(side="left", padx=(self.px(8), self.px(16)))
        ttk.Label(run_bar, text="Язык").pack(side="left")
        self.lang_var = tk.StringVar(value=LANGUAGES["auto"])
        self.lang_box = ttk.Combobox(run_bar, textvariable=self.lang_var, values=list(LANGUAGES.values()),
                                     state="readonly", width=26)
        self.lang_box.pack(side="left", padx=(self.px(8), 0))

        self.progress = ttk.Progressbar(card, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(self.px(14), self.px(4)))
        self.status_label = ttk.Label(card, text="", style="Status.TLabel")
        self.status_label.pack(anchor="w")

        # --- строка состояния снизу (пакуем до вкладок, чтобы её не вытеснило)
        status_bar = ttk.Frame(main)
        status_bar.pack(side="bottom", fill="x", pady=(self.px(8), 0))
        self.stats_label = ttk.Label(status_bar, text="", style="Status.TLabel")
        self.stats_label.pack(side="left")

        # --- вкладки
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True, pady=(self.px(14), 0))
        self._build_segments_tab()
        self._build_text_tab()
        self._build_history_tab()

    def _make_tree(self, parent, columns):
        """Таблица с прокруткой и надписью-заглушкой, когда она пуста."""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings")
        for col, title, width, stretch, anchor in columns:
            tree.heading(col, text=title, anchor=anchor)
            tree.column(col, width=self.px(width), stretch=stretch, anchor=anchor)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        placeholder = tk.Label(frame, justify="center", font=(FONT, 11))
        return tree, placeholder

    def _build_segments_tab(self):
        tab = ttk.Frame(self.tabs, padding=self.px(12))
        self.tabs.add(tab, text="Фрагменты")

        search = ttk.Frame(tab)
        search.pack(fill="x", pady=(0, self.px(10)))
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(search, textvariable=self.find_var, width=22)
        self.find_entry.pack(side="left")
        ttk.Button(search, text="Найти", command=self.find).pack(side="left", padx=(self.px(6), self.px(18)))
        ttk.Label(search, text="Заменить на").pack(side="left")
        self.replace_var = tk.StringVar()
        ttk.Entry(search, textvariable=self.replace_var, width=22).pack(side="left", padx=(self.px(8), 0))
        ttk.Button(search, text="Заменить всё", command=self.replace_all).pack(side="left",
                                                                              padx=(self.px(6), self.px(18)))
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(search, text="Учитывать регистр", variable=self.case_var).pack(side="left")
        self._entry_hint(self.find_entry, "Поиск по тексту")

        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        ttk.Button(buttons, text="Изменить фрагмент", command=self.edit_segment).pack(side="left")
        ttk.Button(buttons, text="Удалить", command=self.delete_segments).pack(side="left", padx=self.px(6))

        self.tree, self.placeholder = self._make_tree(tab, [
            ("num", "№", 50, False, "center"), ("start", "Начало", 80, False, "center"),
            ("end", "Конец", 80, False, "center"), ("text", "Текст", 600, True, "w")])
        self.tree.configure(selectmode="extended")
        self.tree.bind("<Double-1>", lambda e: self.edit_segment())

    def _build_text_tab(self):
        tab = ttk.Frame(self.tabs, padding=self.px(12))
        self.tabs.add(tab, text="Текст")
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(0, self.px(10)))
        self.timecodes_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Показывать таймкоды", variable=self.timecodes_var,
                        command=self.refresh_text).pack(side="left")
        ttk.Button(top, text="Копировать весь текст", command=self.copy_text).pack(side="right")
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", font=(FONT, 11), padx=self.px(14), pady=self.px(12),
                            relief="flat", borderwidth=0, spacing1=self.px(2), spacing3=self.px(6))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_history_tab(self):
        tab = ttk.Frame(self.tabs, padding=self.px(12))
        self.tabs.add(tab, text="История")
        buttons = ttk.Frame(tab)
        buttons.pack(side="bottom", fill="x", pady=(self.px(10), 0))
        ttk.Button(buttons, text="Открыть", command=self.open_from_history).pack(side="left")
        ttk.Button(buttons, text="Удалить из истории", command=self.remove_from_history).pack(side="left",
                                                                                             padx=self.px(6))
        ttk.Button(buttons, text="Очистить историю", command=self.clear_history).pack(side="right")
        self.hist_tree, self.hist_placeholder = self._make_tree(tab, [
            ("date", "Дата", 130, False, "center"), ("file", "Файл", 300, True, "w"),
            ("duration", "Длительность", 110, False, "center"), ("words", "Слов", 70, False, "center"),
            ("model", "Модель", 80, False, "center"), ("project", "Проект", 220, True, "w")])
        self.hist_tree.configure(selectmode="browse")
        self.hist_tree.bind("<Double-1>", lambda e: self.open_from_history())

    def _entry_hint(self, entry, hint):
        """Серая подсказка в пустом поле ввода."""
        var = self.find_var

        def show(_e=None):
            if not var.get():
                entry.configure(foreground=self.colors()["muted"])
                entry.insert(0, hint)
                entry.hint_on = True

        def hide(_e=None):
            if getattr(entry, "hint_on", False):
                entry.delete(0, "end")
                entry.configure(foreground="")
                entry.hint_on = False

        entry.bind("<FocusIn>", hide)
        entry.bind("<FocusOut>", show)
        self.find_hint = (hint, hide)
        show()

    def search_query(self):
        hint, _hide = self.find_hint
        value = self.find_var.get()
        return "" if getattr(self.find_entry, "hint_on", False) and value == hint else value

    def _bind_keys(self):
        # Привязка по коду клавиши, а не по букве: так Ctrl+O/P/S работают
        # и при русской раскладке (дефект D-01)
        self.root.bind("<Control-KeyPress>", self._on_ctrl_key)
        self.root.bind("<F5>", lambda e: self.start_transcription())
        self.root.bind("<F1>", lambda e: self.show_help())
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
            self.file_label.config(text="Откройте аудиозапись")
            self.info_label.config(text="WAV, MP3, M4A, OGG, FLAC и др.  •  Ctrl+O  •  работает без интернета")
            return
        name = os.path.basename(p.audio_path)
        self.file_label.config(text=name + ("  •" if self.dirty else ""))
        project = f"   •   проект: {os.path.basename(self.project_path)}" if self.project_path else ""
        unsaved = "   •   не сохранено" if self.dirty else ""
        if self.audio_info:
            i = self.audio_info
            self.info_label.config(text=f"{i['format']}   •   {format_time(i['duration'])}   •   "
                                        f"{i['size_mb']:.1f} МБ   •   {i['sample_rate']} Гц, "
                                        f"каналов: {i['channels']}{project}{unsaved}")
        elif not os.path.isfile(p.audio_path):
            self.info_label.config(text="Исходный аудиофайл не найден — текст можно править и экспортировать, "
                                        f"но расшифровать заново нельзя{project}{unsaved}")
        else:
            self.info_label.config(text=f"Длительность: {format_time(p.duration)}{project}{unsaved}")

    def refresh_table(self, found=None):
        if found is not None:
            self.found = set(found)
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.project.segments):
            self._insert_row(i, s)
        count = len(self.project.segments)
        self.tabs.tab(0, text=f"Фрагменты ({count})" if count else "Фрагменты")
        self._toggle_placeholder(self.placeholder, not count,
                                 "Здесь появится текст с таймкодами\n\n"
                                 "Откройте аудиозапись и нажмите «Расшифровать»")

    def _insert_row(self, i, seg):
        tag = "found" if i in self.found else ("even" if i % 2 else "odd")
        self.tree.insert("", "end", iid=str(i), tags=(tag,),
                         values=(i + 1, format_time(seg.start), format_time(seg.end), seg.text))

    def _toggle_placeholder(self, label, show, text):
        if show:
            label.configure(text=text)
            label.place(relx=0.5, rely=0.5, anchor="center")
        else:
            label.place_forget()

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
            self.hist_tree.insert("", "end", iid=str(i), tags=("even" if i % 2 else "odd",), values=(
                h.get("date", ""), os.path.basename(h.get("audio_path", "")),
                format_time(h.get("duration", 0)), h.get("words", 0), h.get("model", ""), project))
        self._toggle_placeholder(self.hist_placeholder, not self.history.items,
                                 "История пуста\n\nЗдесь будут прошлые расшифровки")

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
        self.stats_label.config(text=f"Слов: {st['words']}   •   Символов: {st['chars']}   •   "
                                     f"Темп речи: {st['words_per_minute']} сл/мин")

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
        self.found = set()
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
        self.found = set()
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
            if i == 0:
                self._toggle_placeholder(self.placeholder, False, "")
            self._insert_row(i, seg)
            self.tree.see(str(i))
            self.tabs.tab(0, text=f"Фрагменты ({i + 1})")
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
            lang_name = language_name(lang)
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
        c = self.colors()

        win = tk.Toplevel(self.root)
        win.title(f"Фрагмент №{i + 1}")
        win.transient(self.root)
        win.grab_set()
        win.geometry(f"{self.px(600)}x{self.px(280)}")
        body = ttk.Frame(win, padding=self.px(16))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Фрагмент №{i + 1}", style="FileName.TLabel").pack(anchor="w")
        ttk.Label(body, text=f"{format_time(seg.start)} – {format_time(seg.end)}",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, self.px(8)))
        box = tk.Text(body, wrap="word", font=(FONT, 11), height=5, padx=self.px(10), pady=self.px(8),
                      relief="flat", background=c["text_bg"], foreground=c["text_fg"],
                      insertbackground=c["text_fg"], highlightthickness=1, highlightcolor=c["accent"])
        box.insert("1.0", seg.text)
        box.pack(fill="both", expand=True)
        box.focus_set()

        def ok(_event=None):
            new_text = " ".join(box.get("1.0", "end").split())
            if not new_text:
                messagebox.showwarning("Пустой текст", "Текст фрагмента не может быть пустым. "
                                                       "Чтобы убрать фрагмент, используйте «Удалить».",
                                       parent=win)
                return "break"
            if new_text != seg.text:
                seg.text = new_text
                self.after_edit(select=i)
            win.destroy()
            return "break"

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(self.px(12), 0))
        ttk.Label(buttons, text="Ctrl+Enter — сохранить, Esc — отмена", style="Muted.TLabel").pack(side="left")
        ttk.Button(buttons, text="Отмена", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Сохранить", command=ok,
                   style="Accent.TButton" if sv_ttk else "TButton").pack(side="right", padx=self.px(6))
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
        self.found = set()
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
        query = self.search_query()
        if not query.strip():
            messagebox.showinfo("Поиск", "Введите текст для поиска.")
            return
        found = find_segments(self.project.segments, query, self.case_var.get())
        self.refresh_table(found=found)
        if found:
            self.tree.see(str(found[0]))
            self.set_status(f"Найдено во фрагментах: {len(found)} (подсвечены).")
        else:
            self.set_status(f"«{query}» не найдено.")

    def replace_all(self):
        if self.is_busy():
            return
        query = self.search_query()
        if not query.strip():
            messagebox.showinfo("Замена", "Введите, что нужно заменить, в поле поиска.")
            return
        count = replace_in_segments(self.project.segments, query, self.replace_var.get(), self.case_var.get())
        if count:
            self.found = set()
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
        self.found = set()
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
    enable_dpi_awareness()
    root = tk.Tk()
    App(root)
    root.mainloop()
