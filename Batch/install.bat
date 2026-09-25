@echo off
setlocal
rem One-shot setup: tools, code, models, then launch. Safe to run again:
rem every step skips itself when already done.

set "DIR=%USERPROFILE%\MeetingAI"
rem Run from inside a clone: use that clone instead of making a second one.
if exist "%~dp0..\.git" set "DIR=%~dp0.."
set "REPO=https://github.com/Bernardbyy/AI-Meeting-Summarizer"
set WG=winget install -e --silent --accept-package-agreements --accept-source-agreements --id

where winget >nul 2>&1 || (echo winget not found. Update "App Installer" from the Microsoft Store. & goto :error)

echo [1/5] Installing tools, skipping any already installed...
where git    >nul 2>&1 || %WG% Git.Git
where uv     >nul 2>&1 || %WG% astral-sh.uv
where ffmpeg >nul 2>&1 || %WG% Gyan.FFmpeg
where ollama >nul 2>&1 || %WG% Ollama.Ollama
rem New installs are not on this window's PATH yet; reread it from the registry.
call :refresh_path
for %%t in (git uv ffmpeg ollama) do where %%t >nul 2>&1 || (echo %%t did not install. & goto :error)

echo [2/5] Getting the code...
if exist "%DIR%\.git" (echo Already at %DIR%) else (git clone --quiet %REPO% "%DIR%" || goto :error)
cd /d "%DIR%"

echo [3/5] Downloading the summarization model, 2.6GB the first time...
ollama list >nul 2>&1 || (start "" /min ollama serve & timeout /t 5 >nul)
ollama pull qwen3:4b || goto :error

echo [4/5] Installing Python and packages...
uv sync || goto :error

echo [5/5] Downloading the transcription model, ~460MB the first time...
rem Done here so the first recording does not stall on it. Hugging Face's
rem token and symlink warnings are harmless and only alarm people.
set HF_HUB_VERBOSITY=error
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
uv run python -c "from app import transcribe; transcribe.get_model()" || goto :error

echo.
echo Setup complete. Starting MeetingAI...
call Batch\run.bat
exit /b

:refresh_path
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')"`) do set "PATH=%%p"
exit /b

:error
echo.
echo Setup stopped at the step above. Fix it and run this again; finished steps are skipped.
pause
exit /b 1
