"""Делает скриншоты программы для документации: python tools/screenshots.py [папка]"""

import ctypes
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import gui  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots")

for name in ("showinfo", "showwarning", "showerror"):
    setattr(gui.messagebox, name, lambda *a, **k: "ok")
gui.messagebox.askyesno = lambda *a, **k: False


def pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def window_image(root):
    """Снимок окна через PrintWindow — работает, даже если окно перекрыто."""
    from ctypes import wintypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = int(root.wm_frame(), 16)  # внешняя рамка окна вместе с меню
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)  # 2 = PW_RENDERFULLCONTENT

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    info = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)


def grab(root, name):
    if root.state() != "normal":  # окно могло свернуться — разворачиваем
        root.state("normal")
    pump(root, 0.6)
    print("  состояние окна:", root.state(), root.winfo_width(), "x", root.winfo_height())
    window_image(root).save(os.path.join(OUT, name))
    print("сохранён", name)


def main():
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp()
    gui.enable_dpi_awareness()
    root = tk.Tk()
    app = gui.App(root, history_path=os.path.join(tmp, "history.json"))
    root.geometry(f"{app.px(1120)}x{app.px(740)}+40+40")
    pump(root)
    grab(root, "01_start.png")

    sample = os.path.join(tmp, "Лекция_пример.wav")
    shutil.copy(os.path.join(ROOT, "samples", "sample_en.wav"), sample)
    app.open_audio(sample)
    pump(root)
    grab(root, "02_file_opened.png")

    app.start_transcription()
    while app.is_busy() or not app.messages.empty():
        pump(root, 0.1)
    pump(root)
    grab(root, "03_transcribed.png")

    app.find_var.set("program")
    app.find()
    grab(root, "04_search.png")

    app.tabs.select(1)
    grab(root, "05_text_tab.png")

    app.tabs.select(2)
    grab(root, "06_history.png")

    app.tabs.select(0)
    app.theme_var.set(True)
    app.toggle_theme()
    grab(root, "08_dark.png")
    app.theme_var.set(False)
    app.toggle_theme()

    app.tabs.select(0)
    root.geometry(f"{app.px(900)}x{app.px(600)}+40+40")
    pump(root)
    grab(root, "07_min_size.png")

    root.destroy()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
