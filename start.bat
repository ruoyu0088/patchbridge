@echo off
setlocal
cd /d "%~dp0"
title PatchBridge

set "PYEXE="
where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
  where py >nul 2>nul
  if not errorlevel 1 (
    py -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYEXE=py"
  )
)
if not defined PYEXE (
  echo Python 3.11 or newer was not found on PATH.
  echo Install Python from https://www.python.org/downloads/ and enable "Add python.exe to PATH".
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
%PYEXE% start.py --open
if errorlevel 1 pause
