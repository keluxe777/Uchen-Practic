"""Собирает файлы для релиза на GitHub в папку dist/release (запускается из build.bat):

- audio-transcriber-<версия>-setup.exe     — установщик
- audio-transcriber-<версия>-portable.zip  — программа без установки (папка с exe и моделью)
- audio-transcriber-<версия>.exe           — вся программа в одном файле

Имена латиницей: GitHub заменяет русские буквы в именах файлов релиза.
Архив с исходным кодом GitHub добавляет к релизу сам.
"""

import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import APP_NAME, APP_VERSION  # noqa: E402

DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(DIST, "release")
PREFIX = f"audio-transcriber-{APP_VERSION}"


def zip_folder(folder, target):
    """Архив с папкой «Расшифровщик аудио» внутри (имена файлов в UTF-8 — Windows их понимает)."""
    parent = os.path.dirname(folder)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for here, _dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(here, name)
                z.write(path, os.path.relpath(path, parent))


def main():
    sources = {
        f"{PREFIX}-setup.exe": os.path.join(DIST, f"{APP_NAME} {APP_VERSION} - установка.exe"),
        f"{PREFIX}.exe": os.path.join(ROOT, "build", "onefile", f"{APP_NAME}.exe"),
    }
    folder = os.path.join(DIST, APP_NAME)
    for path in (*sources.values(), os.path.join(folder, f"{APP_NAME}.exe")):
        if not os.path.isfile(path):
            print("Нет файла:", path)
            return 1
    if os.path.isdir(RELEASE):
        shutil.rmtree(RELEASE)
    os.makedirs(RELEASE)
    for name, path in sources.items():
        shutil.copy2(path, os.path.join(RELEASE, name))
    zip_folder(folder, os.path.join(RELEASE, f"{PREFIX}-portable.zip"))
    for name in sorted(os.listdir(RELEASE)):
        size = os.path.getsize(os.path.join(RELEASE, name)) / 1024 / 1024
        print(f"  {name}  ({size:.0f} МБ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
