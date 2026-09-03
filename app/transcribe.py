"""Chunk -> tagged, time-ordered transcript.

Each side is transcribed independently, then interleaved by timestamp:

    [00:01:12] You: are we shipping Friday
    [00:01:20] Them: Friday works

Timestamps are absolute within the meeting. Chunk offsets come from the actual
wav durations, not chunk_index * 60, because the last chunk is short and a
dropped buffer makes the rest drift.
"""

import os
import wave
from pathlib import Path

DEFAULT_MODEL = os.environ.get("MEETINGAI_WHISPER_MODEL", "small")

# Capture label -> how it reads in the transcript.
SPEAKER = {"mic": "You", "sys": "Them"}

_models = {}


def get_model(name: str = DEFAULT_MODEL):
    """Cached WhisperModel. Imported lazily so the rest of this module and its
    tests do not need faster-whisper installed."""
    if name not in _models:
        from faster_whisper import WhisperModel

        _models[name] = WhisperModel(name, device="cpu", compute_type="int8")
    return _models[name]


def wav_duration(path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def chunk_offsets(paths: list[Path]) -> list[float]:
    """Start time of each chunk, from real durations."""
    offsets, t = [], 0.0
    for p in paths:
        offsets.append(t)
        t += wav_duration(p)
    return offsets


def transcribe_chunk(path, channel: str, offset: float = 0.0,
                     model_name: str = DEFAULT_MODEL, language: str | None = None,
                     _model=None) -> list[dict]:
    """One chunk -> segments with meeting-absolute timestamps."""
    model = _model if _model is not None else get_model(model_name)
    # ponytail: greedy decode + VAD. beam_size=5 is roughly 3x slower on CPU for
    # a small accuracy gain, and VAD skips the silence that dominates the mic
    # channel. Raise beam_size if transcripts read badly.
    segments, _info = model.transcribe(
        str(path), beam_size=1, vad_filter=True, language=language
    )
    return [
        {
            "start": seg.start + offset,
            "end": seg.end + offset,
            "text": seg.text.strip(),
            "channel": channel,
        }
        for seg in segments
        if seg.text.strip()
    ]


def hhmmss(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def format_transcript(segments: list[dict]) -> str:
    """Interleave both channels by time. Stable: on a tie, you come first."""
    ordered = sorted(segments, key=lambda s: (s["start"], s["channel"] != "mic"))
    return "\n".join(
        f"[{hhmmss(s['start'])}] {SPEAKER.get(s['channel'], s['channel'])}: {s['text']}"
        for s in ordered
    )


def transcribe_meeting(meeting_dir, model_name: str = DEFAULT_MODEL,
                       progress=None, _model=None) -> str:
    """Transcribe every chunk in a meeting folder and write transcript.txt."""
    meeting_dir = Path(meeting_dir)
    chunks_dir = meeting_dir / "chunks"

    work = []
    for channel in ("mic", "sys"):
        paths = sorted(chunks_dir.glob(f"{channel}_*.wav"))
        work += list(zip(paths, chunk_offsets(paths), [channel] * len(paths)))

    segments = []
    for i, (path, offset, channel) in enumerate(work, 1):
        if progress:
            progress(i, len(work))
        segments += transcribe_chunk(path, channel, offset,
                                     model_name=model_name, _model=_model)

    text = format_transcript(segments)
    (meeting_dir / "transcript.txt").write_text(text, encoding="utf-8")
    return text
