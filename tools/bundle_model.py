"""Кладёт модель распознавания в dist/models/<имя> рядом с exe: python tools/bundle_model.py base

Тогда exe работает без интернета на любом компьютере — достаточно скопировать
exe вместе с папкой models. Файлы копируются обычными файлами (без ярлыков
кэша Hugging Face), чтобы папку можно было спокойно переносить и архивировать.
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "base"
    models = os.path.join(ROOT, "dist", "models")
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
