@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Сборка программы и файлов для релиза.
rem Нужно: pip install --only-binary=av -r requirements.txt pyinstaller pillow
rem        и Inno Setup 6 (https://jrsoftware.org/isdl.php или choco install innosetup)
rem Результат — папка dist\release:
rem   audio-transcriber-<версия>-setup.exe     установщик
rem   audio-transcriber-<версия>-portable.zip  программа без установки
rem   audio-transcriber-<версия>.exe           программа одним файлом
python tools\make_icon.py

set OPTIONS=--noconfirm --clean --windowed --name "Расшифровщик аудио" ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --add-data "assets\icon.png;assets" ^
  --collect-data faster_whisper ^
  --collect-data sv_ttk ^
  --collect-binaries ctranslate2 ^
  --collect-all av ^
  --collect-all onnxruntime ^
  --exclude-module torch --exclude-module matplotlib

rem 1. Папка с программой (для установщика и zip). --onedir: открывается за пару секунд
python -m PyInstaller %OPTIONS% --onedir --workpath build\onedir --distpath dist main.py
if errorlevel 1 (echo Ошибка сборки & pause & exit /b 1)
python tools\bundle_model.py base
if errorlevel 1 (echo Не удалось положить модель & pause & exit /b 1)

rem 2. Программа одним файлом, модель base упакована внутрь
python -m PyInstaller %OPTIONS% --onefile ^
  --add-data "dist\Расшифровщик аудио\models\base;models\base" ^
  --workpath build\onefile-work --distpath build\onefile main.py
if errorlevel 1 (echo Ошибка сборки одного файла & pause & exit /b 1)

rem 3. Установщик
for /f %%v in ('python -c "from app import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 не найден: установщик не собран
  pause
  exit /b 1
)
"%ISCC%" /Q /DAppVersion=%VERSION% installer.iss
if errorlevel 1 (echo Ошибка сборки установщика & pause & exit /b 1)

rem 4. Файлы для релиза
python tools\make_release.py
if errorlevel 1 (echo Ошибка подготовки релиза & pause & exit /b 1)
echo Готово: dist\release
