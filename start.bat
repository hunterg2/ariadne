@echo off
title Ariadne
cd /d "%~dp0"

rem Ariadne launcher for Windows. It lives beside app.py and runs whatever
rem app.py currently says, so you can keep editing the code without touching
rem the desktop shortcut that make_shortcut.py points at this file.

set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo   Python was not found.
  echo.
  echo   Install it from python.org and tick "Add Python to PATH"
  echo   on the first screen of the installer.
  echo.
  pause
  exit /b 1
)

%PY% -c "import flask, PIL, cryptography" >nul 2>&1
if errorlevel 1 (
  echo Installing what it needs (Flask, Pillow and cryptography), just this once...
  %PY% -m pip install --quiet --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   Could not install the requirements. Try running this by hand:
    echo     %PY% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
)

%PY% app.py %*

rem A clean shutdown with Ctrl+C leaves errorlevel at 0, so the window only
rem stays open when something actually went wrong and you need to read it.
if errorlevel 1 (
  echo.
  echo   It stopped with an error. The lines above say why.
  echo.
  pause
)
