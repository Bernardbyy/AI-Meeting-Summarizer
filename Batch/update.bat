@echo off
cd /d "%~dp0.."

rem Show what is new, then install it only if the user says yes.
set GIT_TERMINAL_PROMPT=0
set GCM_INTERACTIVE=never

echo Checking for updates...
git fetch --quiet || goto :error

for /f %%n in ('git rev-list --count HEAD..@{u}') do set NEW=%%n
if "%NEW%"=="0" (
    echo Already up to date.
    pause
    goto :eof
)

echo.
echo %NEW% new change(s):
git log --oneline --no-decorate HEAD..@{u}
echo.
echo Full details: git diff HEAD..@{u}
echo.
choice /c YN /m "Install these updates"
if errorlevel 2 goto :eof

git pull --ff-only --quiet || goto :error
uv sync || goto :error
echo.
echo Updated. Start MeetingAI as usual.
pause
goto :eof

:error
echo.
echo Update failed. Offline, or you have local edits? Nothing was changed.
pause
