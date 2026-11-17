@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (set PY=python) else (
  where py >nul 2>nul
  if %errorlevel%==0 (set PY=py) else (
    echo Python is not installed!
    echo Install it from: https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during install, then run this file again.
    pause
    exit /b 1
  )
)
echo ==============================
echo   1 = Website mode (chat page in your browser)
echo   2 = Text mode (type tasks here)
echo   3 = Voice mode (speak, fully automatic)
echo ==============================
set /p choice=Choose 1, 2 or 3 and press Enter:
if "%choice%"=="2" (
  %PY% agent.py
) else if "%choice%"=="3" (
  %PY% agent.py --voice -y
) else (
  %PY% agent.py --web
)
pause
