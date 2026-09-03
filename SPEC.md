# MeetingAI — Specification

Derived from `docs/intent/meeting-ai.md` (confirmed 2026-09-02).

## 1. Objective

A fully offline Windows desktop app that records a meeting (your mic + everything you hear),
transcribes it, and produces meeting minutes. **No audio, transcript, or summary ever leaves
the machine** — there are no outbound network calls in the pipeline.

Single user, own machine: Python 3.11 (managed by `uv`), CPU-only inference, 16GB RAM.

Success: press Start, have a meeting, press Stop, and get usable minutes without waiting
on a spinner that tells you nothing.

## 2. Stack

Verified present on this machine — nothing new to install outside the Python deps:

| Piece | Choice | Why |
|---|---|---|
| Python | 3.11, pinned in `.python-version` | modern, and `PyAudioWPatch` still ships a prebuilt wheel for it; 3.12+ would need a C toolchain to build PortAudio |
| Deps | `uv` (`pyproject.toml` + `uv.lock`) | user preference; uv also provisions the interpreter, so no conda env is involved |
| Backend | FastAPI + uvicorn | user preference |
| UI | Static HTML/JS served by FastAPI, opened in the default browser | user preference |
| Launch | `run.bat` — starts uvicorn, opens browser | user preference |
| Audio capture | `PyAudioWPatch` | the WASAPI-loopback fork of PyAudio; only reliable way to capture system output on Windows |
| Transcription | `faster-whisper` (CTranslate2, int8) | 4-5x realtime on CPU at `small` |
| Summarization | Ollama HTTP API at `127.0.0.1:11434` | already installed; `qwen3:4b` present; gives the model dropdown for free via `/api/tags` |
| Audio file ops | `ffmpeg` (already on PATH) | wav concat / conversion only if needed |

Both model choices are user-selectable at runtime (see §5).

## 3. Commands

```bat
run.bat                     :: start the app and open the browser
```

```bash
uv sync                                  # first-time setup: interpreter + deps
uv run uvicorn app.main:app --port 8756  # run without the .bat
uv run pytest                            # run tests
uv add <package>                         # add a dependency (see boundaries)
```

`run.bat` calls `uv run uvicorn ...`, so it works on a clean machine with only uv installed.

## 4. Project structure

```
MeetingAI/
  run.bat                  launch: uv run uvicorn + open browser
  pyproject.toml
  uv.lock
  .python-version          3.11
  SPEC.md
  docs/intent/meeting-ai.md
  app/
    main.py                FastAPI app, routes, static mount
    audio.py               WASAPI dual-stream capture, 60s chunk writer
    transcribe.py          background worker: chunk -> text
    summarize.py           transcript -> minutes via Ollama
    storage.py             meeting folder layout, history listing
    static/
      index.html
      app.js
      style.css
  meetings/                created at runtime, one folder per meeting
  tests/
    test_storage.py
    test_summarize.py
```

## 5. Behaviour

### Recording
- On Start: open two WASAPI streams — default mic (input) and default output device (loopback).
- Write both to disk continuously. Every ~60s, close a chunk and hand it to the transcription queue.
- The UI shows elapsed time and stage only. **No live transcript text.**
- On Stop: stop capture, wait for the queue to drain, then summarize.

### Channels
Mic and system audio are kept separate through transcription, so each transcript line is
tagged `You:` or `Them:`. This is channel-based, not diarization — individual remote
speakers are not distinguished.

Final `audio.wav` is the two sources mixed to a single stereo file (L = you, R = them),
so it stays one playable file while remaining separable.

### Transcription
- `faster-whisper`, `compute_type="int8"`, model chosen in settings.
- Runs in a background thread during recording, one chunk at a time.
- Chunks are transcribed with timestamp offsets so the stitched transcript stays in order.

### Summarization
- Single prompt: full transcript in, minutes out (Markdown: Summary / Decisions / Action Items / Open Questions).
- **Known ceiling:** works to roughly 30-40 min of meeting. A 2h transcript (~25-30k tokens)
  will overflow context or ingest very slowly on CPU. Chunked map-reduce is the deferred
  upgrade path and must slot in behind the same `summarize(transcript) -> str` interface.

### Settings
A settings panel listing:
- Whisper model: `tiny | base | small | medium | large-v3` (dropdown, default `small`)
- Ollama model: populated live from `GET /api/tags` (default `qwen3:4b`)
- Input device / output device: populated from the WASAPI device list
- Meetings folder path

Persisted to `settings.json` in the project root.

### Progress
The UI polls `GET /api/status` and shows real stages with counts:
`Recording 12:04` -> `Transcribing chunk 7/24` -> `Summarizing…` -> `Done`.
Never a bare spinner.

### Storage
One folder per meeting, named `meetings/YYYY-MM-DD_HHMM_<slug>/`:

```
audio.wav        stereo: L = you, R = them
transcript.txt   "[00:12:31] You: ..." / "[00:12:44] Them: ..."
minutes.md       the generated minutes
meta.json        duration, models used, timestamps
```

History = listing that directory. No database. Deleting a folder deletes the meeting entirely.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/start` | begin recording |
| POST | `/api/stop` | stop, drain queue, summarize |
| GET | `/api/status` | current stage + progress counts |
| GET | `/api/meetings` | list past meetings |
| GET | `/api/meetings/{id}` | transcript + minutes for one meeting |
| DELETE | `/api/meetings/{id}` | delete the folder |
| GET/POST | `/api/settings` | read/write settings, list available models + devices |

## 7. Code style

- Plain functions and modules. No classes unless something genuinely holds state
  (the recorder does; nothing else should).
- No abstraction layers with one implementation — no `TranscriberBase`, no plugin registry.
  Model choice is a string parameter, not a class hierarchy.
- Type hints on module-boundary functions; skip them on local helpers.
- Standard library first; a new dependency needs a reason the table in §2 doesn't already cover.
  Dependencies are added with `uv add`, never hand-edited into `pyproject.toml`, and `uv.lock` is committed.
- Deliberate shortcuts are marked with a `# ponytail:` comment naming the ceiling and upgrade path.

## 8. Testing

Small and real — no fixtures framework, no mocks of things that don't need mocking.

- `test_storage.py` — folder naming, meeting listing, delete, malformed-folder tolerance.
- `test_summarize.py` — prompt assembly and minutes parsing against a stub LLM callable
  (no Ollama needed to run the suite).
- Transcript stitching (chunk offsets producing monotonic timestamps) is tested with
  synthetic segment data, no audio.
- Audio capture is **not** unit-tested — it needs real devices. It gets one manual check:
  record 10s while playing a YouTube video and talking, confirm both channels have signal.

## 9. Boundaries

**Always**
- Keep every byte on-device. Only permitted network target is `127.0.0.1:11434` (Ollama).
- Write audio to disk continuously during recording — a crash must not lose the meeting.
- Show a real stage and count in the UI whenever work is running.

**Ask first**
- Adding any dependency not in §2.
- Anything that would send data off the machine, including telemetry, crash reporting, or model downloads at runtime beyond the Whisper weights the user explicitly selects.
- Changing the on-disk folder format.

**Never**
- Cloud transcription or cloud LLM calls, under any flag or fallback.
- A database for meeting storage.
- Live transcript display, diarization, or map-reduce summarization in the MVP — all deferred by decision.
- Deleting or overwriting a meeting folder without an explicit user action.

## 10. Out of scope (MVP)

Live transcript display · speaker diarization · chunked map-reduce summarization ·
calendar/Teams integration · installer or packaging · multiple users · any cloud call.
