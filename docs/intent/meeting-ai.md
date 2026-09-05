# MeetingAI — Confirmed Intent

Confirmed 2026-09-02.

## MVP

- **Outcome:** Windows desktop app — FastAPI backend + browser UI, launched by a `.bat` — that records mic + system audio, then on Stop transcribes and summarizes it into meeting minutes, entirely offline.
- **User:** Single user, own 16GB CPU-only Windows machine.
- **Why now:** Existing meeting tools ship audio to third parties; not acceptable.
- **Success:** Start → meeting → Stop; minutes appear a few minutes later, and no audio or transcript ever left the machine.
- **Constraint:** CPU-only inference, 16GB RAM. Transcription model and summarization LLM both selectable from a settings dropdown listing locally installed models.
- **Storage:** One folder per meeting: `audio.wav` + `transcript.txt` + `minutes.md`. History = list of folders. No database.

## Decisions

- Python backend (only sane path to WASAPI loopback capture + faster-whisper).
- FastAPI + browser UI, started by a click-to-run `.bat`.
- Mic and system audio recorded as separate channels, so minutes can distinguish "you" vs "them".
- `audio.wav` kept after processing; deleting the folder deletes everything.
- Summarization by a local LLM. No network calls anywhere in the pipeline.
- Transcription runs in the background *during* recording (~60s chunks, no live text shown), so only summarization is left when Stop is pressed.
- Progress UI shows real stages (recording / transcribing N of M chunks / summarizing), not a spinner.
- Summarization batches long meetings (split, digest, combine) so nothing is dropped, whatever the meeting's length. Delivered 2026-09-05, replacing the original single-prompt shortcut.

## Out of scope (MVP)

- Live / real-time transcription
- Speaker diarization
- Any cloud call
- Calendar or Teams integration
- Installer / packaging
- Multiple users

## Future enhancements (to be discussed)

- Speaker diarization
- Live transcription (showing text on screen during the meeting)
