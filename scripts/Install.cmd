@echo off
setlocal
set "INSTALL_SCRIPT=%~dp0install.ps1"
if not exist "%INSTALL_SCRIPT%" set "INSTALL_SCRIPT=%~dp0scripts\install.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%" %*
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="0" goto failed
echo.
echo Created: T3 Code (Auto Sync) shortcut (desktop by default).
echo Fully exit T3, then use that shortcut to refresh imported chats.
echo If T3 is already running, it opens without syncing.
goto finish
:failed
echo.
echo Installation failed. Read the message above.
:finish
pause
exit /b %INSTALL_EXIT%
