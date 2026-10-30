@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Сборка exe. Нужно: pip install -r requirements.txt pyinstaller pillow
python tools\make_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "Расшифровщик аудио" ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --collect-data faster_whisper ^
  --collect-data sv_ttk ^
  --add-data "assets\icon.png;assets" ^
  --collect-binaries ctranslate2 ^
  --collect-all av ^
  --collect-all onnxruntime ^
  --exclude-module torch --exclude-module matplotlib ^
  --workpath build --distpath dist ^
  main.py
if errorlevel 1 (echo Ошибка сборки & pause & exit /b 1)
python tools\bundle_model.py base
echo Готово: папка dist
