@echo off
rem ============================================================
rem StemGuessr one-click launcher for Windows.
rem
rem 1. Installs uv (the Python package manager) if it is missing.
rem 2. Starts the StemGuessr server; the game opens in the default
rem    browser automatically once the server is ready.
rem
rem The first run downloads the Python toolchain and dependencies
rem (~2-3 GB, mostly PyTorch) plus ~250 MB of Demucs model weights.
rem Subsequent runs start in seconds. Everything runs and stays on
rem this machine; nothing is uploaded anywhere.
rem ============================================================
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo uv not found - installing it now ^(one-time, a few MB^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo Failed to install uv. See https://docs.astral.sh/uv/ for manual installation.
        pause
        exit /b 1
    )
    rem The installer places uv in %USERPROFILE%\.local\bin but only new
    rem shells pick that up; extend PATH for this session.
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

echo Starting StemGuessr... the browser opens when the server is ready.
echo (The first run may take several minutes while dependencies download.)
uv run --no-dev stemguessr serve

rem Keep the window open if the server exited with an error, so the
rem message is readable rather than the window vanishing.
pause
endlocal
