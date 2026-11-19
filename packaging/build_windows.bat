@echo off
rem Builds dist\PlayTranslate\PlayTranslate.exe on Windows. Needs Python 3.12 from python.org.
setlocal
cd /d "%~dp0\.."
if not exist .venv (
    py -3.12 -m venv .venv || python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
python packaging\prepare_models.py || goto :error
if exist tv-app\app\build\outputs\apk\release\app-release.apk copy /y tv-app\app\build\outputs\apk\release\app-release.apk playtranslate\server\static\PlayTranslateTV.apk
pyinstaller packaging\playtranslate.spec --noconfirm || goto :error
echo.
echo Done: dist\PlayTranslate\PlayTranslate.exe
exit /b 0
:error
echo Build failed.
exit /b 1
