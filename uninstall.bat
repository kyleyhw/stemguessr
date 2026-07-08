@echo off
rem ============================================================
rem StemGuessr uninstaller for Windows.
rem
rem Removes what StemGuessr put on this machine. Two tiers:
rem   1. App-local: the .venv and the ingested cache in this folder
rem      (always removed).
rem   2. Shared downloads outside this folder: uv's package cache and
rem      the Demucs model weights, ~2-3 GB (removed only if you agree).
rem
rem After running, delete this folder to finish. uv itself is left
rem installed unless you remove it manually (see the note at the end).
rem ============================================================
setlocal
cd /d "%~dp0"

echo StemGuessr uninstaller
echo.

echo Removing local environment (.venv) and ingested cache (cache\)...
if exist ".venv" rmdir /s /q ".venv"
if exist "cache" rmdir /s /q "cache"

echo.
echo StemGuessr also downloaded ~2-3 GB of shared files OUTSIDE this folder:
echo   - Python dependencies in uv's cache
echo   - Demucs AI model weights (%USERPROFILE%\.cache\torch)
echo Remove these too? Choose yes only if you do not use uv or PyTorch
echo for anything else on this machine.
set "ANS=N"
set /p "ANS=Remove shared downloads? [y/N] "
if /i "%ANS%"=="y" (
    where uv >nul 2>nul && uv cache clean
    if exist "%USERPROFILE%\.cache\torch" rmdir /s /q "%USERPROFILE%\.cache\torch"
    echo Shared downloads removed.
) else (
    echo Left shared downloads in place.
)

echo.
echo Done. To finish, delete this StemGuessr folder.
echo To remove uv itself as well, run:  uv self uninstall
pause
endlocal
