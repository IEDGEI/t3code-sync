@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
  echo.
  echo Installation failed. Read the message above.
) else (
  echo.
  echo Done. Use the T3 Code (Auto Sync) desktop shortcut.
)
pause
