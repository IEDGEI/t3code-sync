@echo off
setlocal
set "INSTALL_SCRIPT=%~dp0install.ps1"
if not exist "%INSTALL_SCRIPT%" set "INSTALL_SCRIPT=%~dp0scripts\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%" %*
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="0" goto failed
echo.
echo Done. Use the T3 Code (Auto Sync) desktop shortcut.
goto finish
:failed
echo.
echo Installation failed. Read the message above.
:finish
pause
exit /b %INSTALL_EXIT%
