@echo off
rem Double-click launcher for the Allied Awaaz laptop demo (Windows).
rem First run creates .venv and installs dependencies; later runs start straight away.
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo Setting up Python environment, first run only...
  python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt -r tools\laptop_terminal\requirements.txt || goto :error
)
".venv\Scripts\python.exe" scripts\laptop_demo.py %*
goto :eof
:error
echo Setup failed. Install Python 3.11+ from python.org and try again.
pause
