"""Worker behaviour with a fake recorder and a stubbed Whisper. No devices."""

import queue
import wave
from pathlib import Path

import pytest

from app import audio, session, storage, summarize, transcribe


class FakeRecorder:
    """Emits chunks on demand, exactly like the real one closes them."""

    def __init__(self, meeting_dir, **kw):
        self.dir = Path(meeting_dir)
        self.chunks_dir = self.dir / "chunks"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.closed = queue.Queue()
        self.closed_count = 0
        self.errors = []
        self.written = {"mic": [], "sys": []}
        self.stopped = False

    def start(self):
        return {"mic": "fake mic", "loopback": "fake loopback"}

    def emit(self, channel, seconds, name=None):
        path = self.chunks_dir / (name or f"{channel}_{len(self.written[channel]):03d}.wav")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00" * int(16000 * seconds) * 2)
        self.written[channel].append(path)
        self.closed_count += 1
        self.closed.put({"path": str(path), "channel": channel, "index": 0})
        return path

    def stop_capture(self):
        self.stopped = True
        return self.written


@pytest.fixture
def meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEETINGS_DIR", tmp_path / "meetings")
    monkeypatch.setattr(audio, "build_audio", lambda d, m, s: Path(d) / "audio.wav")
    # Never reach a real LLM from the test suite.
    monkeypatch.setattr(summarize, "summarize",
                        lambda text, model=None: "## Summary\n\nstub minutes\n")
    return storage.new_meeting("worker test")


def stub_transcribe(calls):
    def _t(path, channel, offset=0.0, **kw):
        calls.append((Path(path).name, channel, offset))
        return [{"start": offset + 1, "end": offset + 2,
                 "text": f"{channel} {Path(path).stem}", "channel": channel}]
    return _t


def test_offsets_accumulate_per_channel(meeting, monkeypatch):
    calls = []
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe(calls))

    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 60)
    s.recorder.emit("sys", 60)
    s.recorder.emit("mic", 30)
    s.recorder.emit("sys", 15)
    result = s.stop()

    by_name = {name: offset for name, _ch, offset in calls}
    # Each channel keeps its own clock; sys chunk 1 starts at 60 regardless of mic.
    assert by_name == {"mic_000.wav": 0.0, "sys_000.wav": 0.0,
                       "mic_001.wav": 60.0, "sys_001.wav": 60.0}
    assert result["errors"] == []


def test_transcript_is_written_and_time_ordered(meeting, monkeypatch):
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("sys", 60)
    s.recorder.emit("mic", 60)
    s.stop()

    written = (storage.meeting_dir(meeting) / "transcript.txt").read_text(encoding="utf-8")
    assert written.splitlines() == [
        "[00:00:01] You: mic mic_000",
        "[00:00:01] Them: sys sys_000",
    ]


def test_chunks_emitted_after_stop_are_still_drained(meeting, monkeypatch):
    """The final partial chunk is queued during stop_capture, not before it."""
    calls = []
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe(calls))
    rec = FakeRecorder(storage.meeting_dir(meeting))

    original = rec.stop_capture

    def late(*a, **kw):
        rec.emit("mic", 12, name="mic_999.wav")  # closed on the way out
        return original()

    rec.stop_capture = late

    s = session.Session(meeting, recorder=rec)
    s.start()
    s.recorder.emit("mic", 60)
    s.stop()

    assert [c[0] for c in calls] == ["mic_000.wav", "mic_999.wav"]


def test_one_bad_chunk_does_not_lose_the_meeting(meeting, monkeypatch):
    def explode(path, channel, offset=0.0, **kw):
        if "001" in Path(path).name:
            raise RuntimeError("corrupt chunk")
        return [{"start": offset, "end": offset + 1, "text": "ok", "channel": channel}]

    monkeypatch.setattr(transcribe, "transcribe_chunk", explode)
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 60)
    s.recorder.emit("mic", 60)
    s.recorder.emit("mic", 60)
    result = s.stop()

    assert len(result["errors"]) == 1 and "corrupt chunk" in result["errors"][0]
    assert result["transcript"].count("You: ok") == 2


def test_empty_chunk_is_skipped(meeting, monkeypatch):
    calls = []
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe(calls))
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 0)      # header only
    s.recorder.emit("mic", 60)
    s.stop()

    assert [c[0] for c in calls] == ["mic_001.wav"]
    # The skipped chunk must not shift the clock of the one that follows.
    assert calls[0][2] == 0.0


def test_minutes_are_written(meeting, monkeypatch):
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 60)
    result = s.stop()

    written = (storage.meeting_dir(meeting) / "minutes.md").read_text(encoding="utf-8")
    assert written == result["minutes"] == "## Summary\n\nstub minutes\n"


def test_a_dead_llm_costs_the_minutes_not_the_meeting(meeting, monkeypatch):
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))

    def down(text, model=None):
        raise summarize.SummarizeError("Could not reach Ollama. Is it running?")

    monkeypatch.setattr(summarize, "summarize", down)
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 60)
    result = s.stop()

    assert "Is it running?" in result["errors"][0]
    assert result["transcript"]                              # transcript survived
    assert (storage.meeting_dir(meeting) / "transcript.txt").exists()
    assert not (storage.meeting_dir(meeting) / "minutes.md").exists()


def test_status_reports_progress(meeting, monkeypatch):
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    assert s.status()["stage"] == "recording"

    s.recorder.emit("mic", 60)
    s.stop()
    st = s.status()
    assert st["closed"] == 1 and st["transcribed"] == 1 and st["stage"] == "idle"
    assert st["models"]["whisper"] and st["models"]["llm"]


def test_stage_clock_restarts_on_each_stage(meeting, monkeypatch):
    """The UI shows time-in-stage, so it must not report time since Start."""
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))
    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.started_at -= 600          # pretend the meeting ran ten minutes
    s.stage_since -= 600
    s.recorder.emit("mic", 60)
    s.stop()
    assert s.status()["stage_sec"] < 5


def test_a_failed_mixdown_still_leaves_minutes(meeting, monkeypatch):
    """ffmpeg dying must cost the audio file, not the minutes.

    The transcript is on disk before the mixdown runs, so there is no reason a
    broken ffmpeg should also deny you the summary.
    """
    monkeypatch.setattr(transcribe, "transcribe_chunk", stub_transcribe([]))

    def ffmpeg_died(meeting_dir, mic, sys_):
        raise RuntimeError("ffmpeg failed: Invalid data found when processing input")

    monkeypatch.setattr(audio, "build_audio", ffmpeg_died)

    s = session.Session(meeting, recorder=FakeRecorder(storage.meeting_dir(meeting)))
    s.start()
    s.recorder.emit("mic", 60)
    result = s.stop()

    assert result["audio"] is None
    assert any("ffmpeg" in e for e in result["errors"])
    assert result["minutes"], "minutes must still be written when only the mixdown failed"
    assert (storage.meeting_dir(meeting) / "minutes.md").exists()
    assert (storage.meeting_dir(meeting) / "transcript.txt").exists()
