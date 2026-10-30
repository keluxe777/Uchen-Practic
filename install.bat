@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Установка библиотек...
python -m pip install --only-binary=av -r requirements.txt
if errorlevel 1 (
  echo Ошибка установки. Проверьте, что установлен Python 3.10+ и есть интернет.
  pause
  exit /b 1
)
echo Готово. Запускайте run.bat
pause
