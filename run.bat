@echo off
cd /d "%~dp0"

echo Syncing dependencies...
uv sync || goto :error

rem Open the browser a few seconds after uvicorn starts.
start "" /b cmd /c "timeout /t 3 >nul & start "" http://127.0.0.1:8756"

uv run uvicorn app.main:app --port 8756
goto :eof

:error
echo.
echo Setup failed. Is uv installed?  https://docs.astral.sh/uv/
pause
