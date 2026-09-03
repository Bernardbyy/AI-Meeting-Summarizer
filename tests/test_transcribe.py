"""Stitching and formatting, with a stub model. No audio, no faster-whisper."""

import wave

import pytest

from app import transcribe


class Seg:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class StubModel:
    """Returns one segment per chunk, echoing the file name."""

    def __init__(self, per_chunk=None):
        self.per_chunk = per_chunk or {}
        self.seen = []

    def transcribe(self, path, **kw):
        self.seen.append(path)
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        return list(self.per_chunk.get(name, [Seg(0.5, 1.5, f"text from {name}")])), None


def write_wav(path, seconds, rate=48000, channels=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds) * 2 * channels)
    return path


def test_hhmmss():
    assert transcribe.hhmmss(0) == "00:00:00"
    assert transcribe.hhmmss(61.9) == "00:01:01"
    assert transcribe.hhmmss(3725) == "01:02:05"
    assert transcribe.hhmmss(-3) == "00:00:00"


def test_chunk_offsets_use_real_durations(tmp_path):
    paths = [write_wav(tmp_path / "a.wav", 60),
             write_wav(tmp_path / "b.wav", 60),
             write_wav(tmp_path / "c.wav", 7.5)]
    assert transcribe.chunk_offsets(paths) == [0.0, 60.0, 120.0]


def test_offsets_survive_a_short_middle_chunk(tmp_path):
    """A dropped buffer must not desync everything after it."""
    paths = [write_wav(tmp_path / "a.wav", 60),
             write_wav(tmp_path / "b.wav", 42),
             write_wav(tmp_path / "c.wav", 60)]
    assert transcribe.chunk_offsets(paths) == [0.0, 60.0, 102.0]


def test_transcribe_chunk_applies_offset_and_channel(tmp_path):
    p = write_wav(tmp_path / "mic_001.wav", 1)
    out = transcribe.transcribe_chunk(p, "mic", offset=60.0, _model=StubModel())
    assert out == [{"start": 60.5, "end": 61.5,
                    "text": "text from mic_001.wav", "channel": "mic"}]


def test_blank_segments_are_dropped(tmp_path):
    p = write_wav(tmp_path / "mic_000.wav", 1)
    stub = StubModel({"mic_000.wav": [Seg(0, 1, "   "), Seg(1, 2, " hi ")]})
    out = transcribe.transcribe_chunk(p, "mic", _model=stub)
    assert [s["text"] for s in out] == ["hi"]


def test_format_interleaves_channels_by_time():
    segs = [
        {"start": 80, "end": 81, "text": "Friday works", "channel": "sys"},
        {"start": 72, "end": 73, "text": "are we shipping Friday", "channel": "mic"},
    ]
    assert transcribe.format_transcript(segs) == (
        "[00:01:12] You: are we shipping Friday\n"
        "[00:01:20] Them: Friday works"
    )


def test_format_breaks_ties_with_you_first():
    segs = [{"start": 5, "end": 6, "text": "b", "channel": "sys"},
            {"start": 5, "end": 6, "text": "a", "channel": "mic"}]
    assert transcribe.format_transcript(segs).splitlines()[0].endswith("You: a")


def test_format_of_nothing_is_empty():
    assert transcribe.format_transcript([]) == ""


def test_transcribe_meeting_stitches_both_channels(tmp_path):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    for label in ("mic", "sys"):
        write_wav(chunks / f"{label}_000.wav", 60)
        write_wav(chunks / f"{label}_001.wav", 30)

    stub = StubModel({
        "mic_000.wav": [Seg(10, 11, "first thing")],
        "sys_000.wav": [Seg(20, 21, "reply")],
        "mic_001.wav": [Seg(5, 6, "later")],      # -> 65s
        "sys_001.wav": [Seg(1, 2, "earlier")],    # -> 61s
    })
    seen = []
    text = transcribe.transcribe_meeting(tmp_path, progress=lambda i, n: seen.append((i, n)),
                                         _model=stub)

    assert text.splitlines() == [
        "[00:00:10] You: first thing",
        "[00:00:20] Them: reply",
        "[00:01:01] Them: earlier",
        "[00:01:05] You: later",
    ]
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == text
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_transcribe_meeting_with_no_chunks(tmp_path):
    (tmp_path / "chunks").mkdir()
    assert transcribe.transcribe_meeting(tmp_path, _model=StubModel()) == ""


def test_chunks_are_read_in_numeric_order(tmp_path):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    for i in range(11):
        write_wav(chunks / f"mic_{i:03d}.wav", 1)
    stub = StubModel()
    transcribe.transcribe_meeting(tmp_path, _model=stub)
    assert [p.rsplit("_", 1)[-1] for p in stub.seen][:3] == ["000.wav", "001.wav", "002.wav"]
    assert stub.seen[-1].endswith("010.wav")
