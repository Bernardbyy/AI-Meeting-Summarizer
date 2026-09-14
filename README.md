# AI Meeting Summarizer

Records a meeting on Windows — your microphone *and* everything you hear — then
transcribes it and writes the minutes. Entirely on your machine: the only network
address it ever contacts is `127.0.0.1:11434`, the local Ollama server.

Built for CPU-only inference on 16GB of RAM.

## What you get

Every meeting is a plain folder. No database.

```
meetings/2026-09-02_1806/
    audio.wav        stereo — left channel is you, right channel is everyone else
    transcript.txt   [00:01:12] You: are we shipping Friday
    minutes.md       Summary / Decisions / Action Items / Open Questions
    meta.json        duration, devices and models used
```

Delete the folder and the meeting is gone, audio included.

## Setup

Windows only — audio capture uses WASAPI loopback. Run these in PowerShell.

**1. Install the tools**

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
winget install --id Gyan.FFmpeg -e
winget install --id Ollama.Ollama -e
winget install --id GitHub.cli -e
```

**2. Close and reopen PowerShell** so the new tools are on PATH.

**3. Sign in to GitHub** (the repository is private)

```powershell
gh auth login
```

**4. Get the code**

```powershell
gh repo clone Bernardbyy/AI-Meeting-Summarizer
cd AI-Meeting-Summarizer
```

**5. Download the summarization model** (2.6GB, one time)

```powershell
ollama pull qwen3:4b
```

**6. Run it**

```powershell
.\run.bat
```

`run.bat` installs Python 3.11 and the dependencies, starts the server on port
8756 and opens your browser. After the first time, just double-click it.

### What to expect the first time

- **Starting takes a minute.** The first `run.bat` downloads Python and the
  packages before the browser opens.
- **Your first recording looks frozen for a few minutes.** Pressing Record
  downloads the transcription model (~460MB for `small`) and nothing on screen
  shows it. Do one short test recording before relying on it in a real meeting.
- **Use headphones** (see below).

### Moving from another machine

A fresh clone has all the code, but not:

- **Past meetings** — `meetings/` is never committed, because recordings are
  private. Copy the folder across by hand if you want them.
- **Your settings** — `settings.json` is not committed either. The app starts
  with the defaults (`small` and `qwen3:4b`); reselect your models in Settings.

### For development

```powershell
uv sync                                  # dependencies only
uv run uvicorn app.main:app --port 8756  # run without run.bat
uv run pytest                            # 106 tests, no devices or Ollama needed
```

## How it works

Transcription runs *while* you record, so pressing Stop leaves only the tail to
process rather than the whole meeting.

```
mic  ──┐                          ┌─ transcript.txt
       ├─ 60s chunks ─→ Whisper ──┤
system ┘        │                 └─ Ollama ──→ minutes.md
                └─ ffmpeg ──────────────────→ audio.wav
```

Chunks are written to disk continuously, so a crash costs one chunk, not the
meeting. The transcript is saved before summarization starts, so a failed or
unreachable model costs you the minutes and nothing else.

## Settings

Transcription model, summarization model, input devices and the meetings folder
are all selectable in-app and stored in `settings.json`.

| Whisper model | Speed on CPU | 2h meeting |
|---|---|---|
| `tiny` | ~15-20× realtime | ~7 min |
| `base` | ~10× | ~12 min |
| `small` (default) | ~4-5× | ~25-30 min |
| `medium` | ~1.5× | ~80 min |
| `large-v3` | slower than realtime | 2h+ |

Two things worth knowing:

- **Use headphones.** On speakers the microphone re-hears the system audio, so
  both channels transcribe the same words and the minutes see everything twice.
- **Long meetings are summarized in batches.** Past roughly 40 minutes the
  transcript is split on line boundaries, each part is digested separately, and
  the digests are combined into the minutes. Every line reaches the model —
  nothing is dropped. Batches run one at a time, because on CPU a single request
  already uses every core.
- **It is slow, and that is the model, not the pipeline.** Generation runs about
  7 tokens/sec and prompt reading about 24-40 tokens/sec on a 16GB CPU machine,
  so expect several minutes after Stop. A smaller model trades quality for speed.

## Layout

```
app/
  main.py        FastAPI routes
  session.py     one recording: capture, transcribe-as-you-go, summarize
  audio.py       WASAPI dual capture, chunk writer, ffmpeg mixdown
  transcribe.py  faster-whisper, chunk stitching, You/Them tagging
  summarize.py   Ollama prompt and minutes
  storage.py     meeting folders
  settings.py    settings.json
  static/        the UI
design/          .dc.html source for the design canvas
docs/, tasks/    intent, spec and build plan
```
