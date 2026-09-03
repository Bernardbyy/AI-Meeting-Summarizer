# MeetingAI — Implementation Plan

From `SPEC.md`. Empty project — everything below is new code.

## Dependency graph

```
              run.bat + FastAPI shell
                        |
        +---------------+---------------+
        |                               |
   storage.py                      audio.py  (RISK)
   (folders, meta)                 WASAPI dual capture

        |                               |
        |                          chunk writer
        |                               |
        +-------------+-----------------+
                      |
                transcribe.py
              (chunk -> tagged text)
                      |
          +-----------+-----------+
          |                       |
   background worker         summarize.py
   + progress status         (Ollama -> minutes.md)
          |                       |
          +-----------+-----------+
                      |
              history UI + settings
```

`audio.py` is the only component that can fail for reasons outside the code — device
enumeration, WASAPI loopback availability, PyAudioWPatch wheels on Python 3.11. It is
therefore attacked in Phase 1, before anything is built on top of it.

## Slicing

Each phase ends with an app you can run and use. No phase is a horizontal layer
("build all the models", "build all the routes") — each cuts top to bottom through
UI, backend, and disk.

---

## Phase 0 — Walking skeleton

Prove the loop before adding anything hard.

**Task 0.1 — Project scaffold**
- `uv add fastapi uvicorn`, `app/main.py`, `app/static/index.html`, `run.bat`
- FastAPI serves the page; `run.bat` runs `uv run uvicorn` on port 8756 and opens the browser
- uv project already initialised: `pyproject.toml` + `.python-version` (3.11) exist
- Accept: double-click `run.bat`, browser opens to a page with Start/Stop buttons
- Verify: manual — the page loads and the buttons are visible

**Task 0.2 — Meeting folders**
- `app/storage.py`: `new_meeting()`, `list_meetings()`, `read_meeting(id)`, `delete_meeting(id)`
- Folder `meetings/YYYY-MM-DD_HHMM_<slug>/` with `meta.json`
- Accept: Start creates a folder, Stop writes duration into `meta.json`
- Verify: `pytest tests/test_storage.py` — naming, listing, delete, tolerate a junk folder

**CHECKPOINT 0** — Start/Stop produces real folders on disk. No audio yet.

---

## Phase 1 — Audio capture (highest risk, done early)

**Task 1.1 — Device enumeration spike**
- Standalone script: list WASAPI devices, find default mic + default output loopback
- Accept: prints both device names on this machine
- Verify: manual — run it, confirm the names match Windows sound settings
- If PyAudioWPatch has no wheel for 3.11, stop here and escalate; do not work around it
  (fallback under discussion would be dropping to 3.10, not building PortAudio from source)

**Task 1.2 — Dual-stream capture to disk**
- `app/audio.py`: open both streams, write continuously, mix to stereo (L=you, R=them)
- Wired to the existing Start/Stop buttons
- Accept: 10s recording produces `audio.wav` with signal in both channels
- Verify: manual — talk while playing a video, then check each channel independently
  (`ffmpeg -i audio.wav -map_channel 0.0.0 l.wav -map_channel 0.0.1 r.wav` and listen)

**Task 1.3 — 60s chunking**
- Close a chunk every ~60s into `chunks/NNN.wav`, keep the full `audio.wav` too
- Handle the final partial chunk on Stop
- Accept: a 150s recording yields 3 chunks, last one short, plus a complete `audio.wav`
- Verify: manual — record 150s, count files, check total duration matches

**CHECKPOINT 1** — The app records real meetings. Nothing transcribes them yet, but
no audio is being lost. This is already useful on its own.

---

## Phase 2 — Transcription (synchronous first)

Deliberately simple first pass: transcribe after Stop, in the request. Made concurrent
in Phase 3 once it is known to be correct.

**Task 2.1 — Single-chunk transcription**
- `app/transcribe.py`: `transcribe_chunk(path, channel) -> list[Segment]`
- `faster-whisper`, `compute_type="int8"`, model name as a parameter
- Accept: one 60s chunk returns segments with text and timestamps
- Verify: manual — transcribe a known chunk, read the output

**Task 2.2 — Stitching and tagging**
- Offset each chunk timestamps by its position; tag lines `You:` / `Them:` by channel;
  merge both channels into one time-ordered `transcript.txt`
- Accept: `[00:01:12] You: ...` / `[00:01:20] Them: ...`, timestamps monotonic across chunks
- Verify: `pytest tests/test_transcribe.py` — synthetic segments, no audio needed

**CHECKPOINT 2** — Stop produces a real `transcript.txt`. The UI blocks while it works;
that is expected and fixed next.

---

## Phase 3 — Background worker + progress

**Task 3.1 — Transcription queue**
- Background thread consumes chunks as they close, during recording
- Stop drains the queue instead of starting from zero
- Accept: a 5-min recording is transcribed within seconds of pressing Stop
- Verify: manual — time the gap between Stop and `transcript.txt` appearing

**Task 3.2 — Status endpoint and progress UI**
- `GET /api/status` returns stage + counts; page polls it every 1s
- Stages: `idle | recording MM:SS | transcribing N/M | summarizing | done`
- Accept: the UI shows chunk counts advancing during a recording
- Verify: manual — record 3 min, watch the counter move

**CHECKPOINT 3** — No more dead waiting. The app is honest about what it is doing.

---

## Phase 4 — Summarization

**Task 4.1 — Ollama call**
- `app/summarize.py`: `summarize(transcript: str, model: str) -> str`
- POST to `127.0.0.1:11434/api/generate`; prompt yields Summary / Decisions /
  Action Items / Open Questions
- `# ponytail:` comment naming the long-transcript ceiling and map-reduce upgrade path
- Accept: a 10-min transcript produces sensible minutes with `qwen3:4b`
- Verify: `pytest tests/test_summarize.py` — prompt assembly against a stub callable;
  plus one manual run against real Ollama

**Task 4.2 — Wire into Stop**
- After the queue drains, summarize and write `minutes.md`; show it in the UI
- Handle Ollama being down with a clear error, not a stack trace
- Accept: Stop yields `minutes.md` and the page displays it
- Verify: manual — full record to minutes run; then stop Ollama and confirm the error reads plainly

**CHECKPOINT 4** — Feature-complete against the core loop. Everything after this is
convenience.

---

## Phase 5 — History and settings

**Task 5.1 — History UI**
- List past meetings, open one to read transcript + minutes, delete with confirmation
- Accept: three recorded meetings appear, open correctly, delete removes the folder
- Verify: manual + `test_storage.py` already covers the backend

**Task 5.2 — Settings**
- Panel for Whisper model, Ollama model (live from `/api/tags`), input/output device,
  meetings folder; persisted to `settings.json`
- Accept: switching the Ollama model changes which model the next summary uses
- Verify: manual — switch to `qwen3:0.6b`, confirm `meta.json` records it

**CHECKPOINT 5** — Ship.

---

## Verification that runs the whole way through

`uv run pytest` covers storage, stitching, and prompt assembly — none of it needs audio devices
or Ollama, so it stays runnable in any state.

Audio capture is verified manually at each phase, per SPEC section 8.

## Known deferrals

Live transcript display, diarization, map-reduce summarization, packaging. All out of
scope by decision; the summarize interface is shaped so map-reduce can slot in later.
