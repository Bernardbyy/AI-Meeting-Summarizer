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

## Requirements

- Windows (capture uses WASAPI loopback)
- [uv](https://docs.astral.sh/uv/) — provisions Python 3.11 itself
- [Ollama](https://ollama.com/) with a model pulled: `ollama pull qwen3:4b`
- `ffmpeg` on PATH

## Run it

```
run.bat
```

That syncs dependencies, starts the server on port 8756 and opens your browser.
The Whisper model downloads on first use (~460MB for `small`), then never again.

```bash
uv sync                                  # setup only
uv run uvicorn app.main:app --port 8756  # run without the .bat
uv run pytest                            # 86 tests, no devices or Ollama needed
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
- **Summarization is a single prompt** over the whole transcript, which holds to
  roughly 30-40 minutes of meeting. Past that the earliest part is dropped and
  the minutes say so. Chunked map-reduce is the planned fix.

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
