@echo off
rem Scripts live in Batch\; everything else runs from the project root.
cd /d "%~dp0.."

rem No git pull here on purpose: launching must never run code the user has not
rem chosen to install. Updates are update.bat, run by hand.
echo Syncing dependencies...
uv sync || goto :error

rem Start menu shortcut, so "MeetingAI" is findable from Windows search.
rem Rewritten every launch so it follows the folder if it is moved.
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\MeetingAI.lnk\"); $s.TargetPath='%~f0'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\app\static\favicon.ico'; $s.Save()" >nul 2>&1

rem Open the browser a few seconds after uvicorn starts.
start "" /b cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8756"

uv run uvicorn app.main:app --port 8756
goto :eof

:error
echo.
echo Setup failed. Is uv installed?  https://docs.astral.sh/uv/
pause
