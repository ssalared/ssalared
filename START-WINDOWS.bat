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
echo   1 = Text mode (type tasks)
echo   2 = Voice mode (speak, fully automatic)
echo ==============================
set /p choice=Choose 1 or 2 and press Enter:
if "%choice%"=="2" (
  %PY% agent.py --voice -y
) else (
  %PY% agent.py
)
pause
