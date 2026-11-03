@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title PatchBridge

set "MKL_THREADING_LAYER=TBB"
set "PYTHONPATH=%~dp0src"
set "PY=C:\pixi_env\.pixi\envs\default\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m patchbridge --open

if errorlevel 1 (
  echo.
  echo PatchBridge 启动失败。请确认 Python 依赖已安装：
  echo   pip install -e ".[test]"
  echo.
  pause
)
