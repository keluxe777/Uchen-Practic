"""Кладёт модель распознавания в папку программы рядом с exe:
python tools/bundle_model.py base   →   dist/Расшифровщик аудио/models/base

Установщик забирает её вместе с exe, и программа работает без интернета на любом
компьютере. Файлы копируются обычными файлами (без ярлыков кэша Hugging Face),
чтобы папку можно было спокойно переносить и архивировать.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import APP_NAME  # noqa: E402  имя папки программы, как у exe


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "base"
    models = os.path.join(ROOT, "dist", APP_NAME, "models")
    target = os.path.join(models, name)
    from faster_whisper.utils import download_model
    snapshot = download_model(name)  # скачивает в общий кэш или берёт оттуда
    if os.path.isdir(models):
        shutil.rmtree(models)
    os.makedirs(target)
    for file in os.listdir(snapshot):
        shutil.copy2(os.path.join(snapshot, file), os.path.join(target, file))  # copy2 идёт по ярлыкам
    size = sum(os.path.getsize(os.path.join(target, f)) for f in os.listdir(target)) / 1024 / 1024
    print(f"модель {name} -> {target} ({size:.0f} МБ)")


if __name__ == "__main__":
    main()
