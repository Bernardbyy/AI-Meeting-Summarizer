# MeetingAI — Task List

## Phase 0 — Walking skeleton
- [x] 0.1 Scaffold: uv add fastapi uvicorn, app/main.py, static/index.html, run.bat
- [x] 0.2 storage.py: meeting folders + meta.json, wired to Start/Stop
- [x] **CHECKPOINT 0** — Start/Stop creates real folders (16 tests pass; routes smoke-tested)

## Phase 1 — Audio capture (risk first)
- [x] 1.1 WASAPI device enumeration spike — wheel installs on 3.11, loopback found
- [x] 1.2 Dual-stream capture -> stereo audio.wav (L=you, R=them)
- [x] 1.3 60s chunking + final partial chunk
- [x] **CHECKPOINT 1** — App records meetings without losing audio
      (verified: 13s recording -> 3 chunks/side; L RMS -49dB, R RMS -25dB)

## Phase 2 — Transcription (synchronous)
- [x] 2.1 transcribe_chunk() via faster-whisper int8
- [x] 2.2 Stitch chunks, tag You/Them, write transcript.txt
- [x] **CHECKPOINT 2** — Stop produces transcript.txt
      (verified: 13s of SAPI speech -> 8 correctly tagged, time-ordered lines)
      OPEN: speaker bleed — on laptop speakers the mic re-hears system audio,
      so both channels transcribe the same words. Headphones avoid it; a
      near-duplicate filter is the fix if needed.

## Phase 3 — Background worker + progress
- [x] 3.1 Transcription queue running during recording
- [x] 3.2 /api/status + progress UI with real stages
- [x] **CHECKPOINT 3** — No dead waiting
      (verified: 31s meeting, worker kept pace with capture the whole way;
       Stop returned in 2.1s including ffmpeg mixdown)

## Phase 4 — Summarization
- [x] 4.1 summarize() via Ollama, with ponytail ceiling comment
- [x] 4.2 Wire into Stop, write minutes.md, handle Ollama down
- [x] **CHECKPOINT 4** — Core loop complete
      (verified end to end: record -> transcript.txt -> minutes.md, 27s total)
      NOTE: qwen3 needs the `/no_think` prompt directive — without it the same
      summary took 3m42s instead of 15s. The API `think: false` field is ignored.

## Phase 5 — History and settings
- [x] 5.1 History UI: list, open, delete
- [x] 5.2 Settings panel + settings.json
- [x] **CHECKPOINT 5** — Ship
      (verified: settings persist and reach the run — meta.json recorded the
       chosen whisper/llm models; bad values 400; changes blocked while recording)

## Design pass — glass / Apple
- [x] Canvas of 6 screens published for review
- [x] Rebuilt static/ against it: style.css, restructured index.html, rewritten app.js
- [x] Live level meters (real RMS per channel, exposed in /api/status)
- [x] Staged post-stop progress, folder sizes, human dates, parsed minutes + transcript
- [x] Reduced-motion and reduced-transparency fallbacks
