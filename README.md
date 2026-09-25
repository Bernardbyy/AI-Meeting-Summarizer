# MeetingAI

Records a meeting on Windows — your microphone *and* everything you hear — then
transcribes it and writes the minutes. Everything stays on your machine: the
only network address it contacts is the local Ollama server. Built for CPU-only
inference on 16GB of RAM.

Each meeting is a plain folder under `meetings/` with `audio.wav`,
`transcript.txt` and `minutes.md`. Delete the folder and the meeting is gone.

## Setup

Windows only. Paste this into PowerShell:

```powershell
irm https://raw.githubusercontent.com/Bernardbyy/AI-Meeting-Summarizer/main/Batch/install.bat -OutFile $env:TEMP\meetingai-install.bat; & $env:TEMP\meetingai-install.bat
```

It installs everything MeetingAI needs, downloads the models (~3GB, so allow
some time), puts the app in `%USERPROFILE%\MeetingAI` and opens it. If a step
fails, fix it and run the line again; finished steps are skipped.

After that, find **MeetingAI** in the Start menu.

## Updates

Run `Batch\update.bat`. It lists what changed and asks before installing anything.
Starting the app never updates on its own, and updates never touch your
meetings or settings.

## Settings

Choose the transcription model, summarization model and audio devices in the
app's Settings panel. Changes apply from the next recording.

| Whisper model | Speed on CPU | 2h meeting |
|---|---|---|
| `tiny` | ~15-20× realtime | ~7 min |
| `base` | ~10× | ~12 min |
| `small` (default) | ~4-5× | ~25-30 min |
| `medium` | ~1.5× | ~80 min |
| `large-v3` | slower than realtime | 2h+ |

Any model pulled into Ollama shows up as a summarization choice. Expect several
minutes of summarizing after Stop; a smaller model is faster but writes weaker
minutes.

## Project Structure

```
Batch/
  install.bat    one-shot setup: tools, code, models
  run.bat        start the app
  update.bat     update to the latest version
app/
  main.py        FastAPI routes
  session.py     one recording: capture, transcribe-as-you-go, summarize
  audio.py       WASAPI dual capture, chunk writer, ffmpeg mixdown
  transcribe.py  faster-whisper, chunk stitching, You/Them tagging
  summarize.py   Ollama prompt and minutes
  storage.py     meeting folders
  settings.py    settings.json
  static/        the UI
tests/           uv run pytest — no audio devices or Ollama needed
design/          .dc.html source for the design canvas
docs/, tasks/    intent, spec and build plan
```
