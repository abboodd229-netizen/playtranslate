@echo off
rem Run PlayTranslate without building an exe. First run installs everything (a few minutes).
rem Needs Python 3.12 from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
setlocal
cd /d "%~dp0"
if not exist .venv (
    echo Creating environment...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv || goto :nopython
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt || goto :error
) else (
    call .venv\Scripts\activate.bat
)
start "" pythonw -m playtranslate
exit /b 0
:nopython
echo Python 3.12 is not installed. Get it from https://www.python.org/downloads/
pause
exit /b 1
:error
echo Installing requirements failed. See the messages above.
pause
exit /b 1
