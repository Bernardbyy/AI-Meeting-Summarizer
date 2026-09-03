"""HTTP behaviour, with fake devices and a stubbed model. No audio, no Ollama."""

import json
import queue
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import audio, main, session, settings, storage, summarize, transcribe

DEVICES = {
    "mics": [{"index": 15, "name": "Fake Mic", "channels": 2, "rate": 48000}],
    "loopbacks": [{"index": 16, "name": "Fake Speakers [Loopback]", "channels": 2, "rate": 48000}],
    "default_mic": 15,
    "default_loopback": 16,
}


class FakeRecorder:
    def __init__(self, meeting_dir, **kw):
        self.dir = Path(meeting_dir)
        (self.dir / "chunks").mkdir(parents=True, exist_ok=True)
        self.closed = queue.Queue()
        self.closed_count = 0
        self.errors = []
        self.fail_on_start = False

    def start(self):
        if self.fail_on_start:
            raise RuntimeError("no loopback device for output 'Speakers'")
        return {"mic": "Fake Mic", "loopback": "Fake Speakers [Loopback]"}

    def emit(self, channel="mic", seconds=1):
        path = self.dir / "chunks" / f"{channel}_{self.closed_count:03d}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00" * int(16000 * seconds) * 2)
        self.closed_count += 1
        self.closed.put({"path": str(path), "channel": channel, "index": 0})

    def stop_capture(self):
        return {"mic": [], "sys": []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(storage, "MEETINGS_DIR", tmp_path / "meetings")
    monkeypatch.setattr(audio, "list_devices", lambda: dict(DEVICES))
    monkeypatch.setattr(audio, "build_audio", lambda d, m, s: Path(d) / "audio.wav")
    monkeypatch.setattr(audio, "Recorder", FakeRecorder)
    monkeypatch.setattr(summarize, "summarize",
                        lambda text, model=None: "## Summary\n\nstub minutes\n")
    monkeypatch.setattr(summarize, "list_models", lambda: ["qwen3:4b", "qwen3:0.6b"])
    monkeypatch.setattr(transcribe, "transcribe_chunk",
                        lambda p, ch, off=0.0, **kw: [
                            {"start": off, "end": off + 1, "text": "hello", "channel": ch}])
    monkeypatch.setattr(main, "CURRENT", None)
    with TestClient(main.app) as c:
        yield c
    main.CURRENT = None


# --- status ---------------------------------------------------------------

def test_idle_status_still_names_devices_and_models(client):
    """The app must be able to say what it would record with, before recording."""
    s = client.get("/api/status").json()
    assert s["stage"] == "idle" and s["meeting_id"] is None
    assert s["devices"]["mic"] == "Fake Mic"
    assert s["devices"]["loopback"] == "Fake Speakers [Loopback]"
    assert s["models"]["whisper"] and s["models"]["llm"]


def test_idle_status_survives_a_machine_with_no_audio(client, monkeypatch):
    def no_audio():
        raise RuntimeError("no loopback device for output 'Speakers'")

    monkeypatch.setattr(audio, "list_devices", no_audio)
    s = client.get("/api/status").json()
    assert s["stage"] == "idle"
    assert "no loopback" in s["errors"][0]


def test_status_reflects_the_chosen_devices_not_the_defaults(client):
    client.post("/api/settings", json={"mic_index": 16})
    assert client.get("/api/status").json()["devices"]["mic"] == "Fake Speakers [Loopback]"


# --- start / stop ---------------------------------------------------------

def test_start_creates_a_meeting_and_reports_recording(client):
    s = client.post("/api/start").json()
    assert s["stage"] == "recording" and s["meeting_id"]
    assert (storage.MEETINGS_DIR / s["meeting_id"] / "meta.json").exists()


def test_start_records_the_devices_and_models_in_meta(client):
    mid = client.post("/api/start").json()["meeting_id"]
    meta = json.loads((storage.MEETINGS_DIR / mid / "meta.json").read_text(encoding="utf-8"))
    assert meta["devices"]["mic"] == "Fake Mic"
    assert meta["whisper_model"] and meta["llm_model"]


def test_starting_twice_is_refused(client):
    client.post("/api/start")
    r = client.post("/api/start")
    assert r.status_code == 409 and "already recording" in r.json()["detail"]


def test_stopping_when_idle_is_refused(client):
    r = client.post("/api/stop")
    assert r.status_code == 409 and r.json()["detail"] == "not recording"


def test_a_capture_failure_leaves_no_empty_meeting_behind(client, monkeypatch):
    """A meeting you could never record must not clutter the history."""
    class Broken(FakeRecorder):
        def start(self):
            raise RuntimeError("no loopback device for output 'Speakers'")

    monkeypatch.setattr(audio, "Recorder", Broken)
    r = client.post("/api/start")

    assert r.status_code == 500 and "could not start capture" in r.json()["detail"]
    assert client.get("/api/meetings").json() == []
    assert client.get("/api/status").json()["stage"] == "idle"


def test_stop_writes_duration_and_artifacts(client):
    mid = client.post("/api/start").json()["meeting_id"]
    main.CURRENT.recorder.emit()
    body = client.post("/api/stop").json()

    assert body["meeting_id"] == mid and body["errors"] == []
    meta = json.loads((storage.MEETINGS_DIR / mid / "meta.json").read_text(encoding="utf-8"))
    assert "ended_at" in meta and meta["duration_sec"] >= 0
    assert (storage.MEETINGS_DIR / mid / "minutes.md").exists()


def test_the_app_is_usable_again_after_a_stop(client):
    client.post("/api/start")
    client.post("/api/stop")
    assert client.post("/api/start").status_code == 200


# --- meetings -------------------------------------------------------------

def test_meetings_are_listed_newest_first_with_sizes(client):
    for _ in range(2):
        client.post("/api/start")
        client.post("/api/stop")
    items = client.get("/api/meetings").json()

    assert len(items) == 2
    assert items[0]["id"] > items[1]["id"]
    assert all(m["size_bytes"] > 0 and m["has_minutes"] for m in items)


def test_reading_a_meeting_returns_its_text(client):
    client.post("/api/start")
    main.CURRENT.recorder.emit()
    mid = client.post("/api/stop").json()["meeting_id"]

    m = client.get(f"/api/meetings/{mid}").json()
    assert m["id"] == mid and "stub minutes" in m["minutes"] and "hello" in m["transcript"]


def test_missing_meeting_is_404(client):
    assert client.get("/api/meetings/2026-01-01_0900_nope").status_code == 404


def test_a_malformed_id_is_rejected_before_it_reaches_the_disk(client):
    """Ids reach shutil.rmtree, so the route must refuse anything we did not name."""
    for bad in ("not-an-id", "....", "2026-13-45_9999_x!"):
        assert client.get(f"/api/meetings/{bad}").status_code == 400
        assert client.delete(f"/api/meetings/{bad}").status_code == 400


def test_delete_removes_the_folder(client):
    mid = client.post("/api/start").json()["meeting_id"]
    client.post("/api/stop")

    assert client.delete(f"/api/meetings/{mid}").json() == {"deleted": mid}
    assert not (storage.MEETINGS_DIR / mid).exists()
    assert client.get("/api/meetings").json() == []


def test_you_cannot_delete_the_meeting_you_are_recording(client):
    mid = client.post("/api/start").json()["meeting_id"]
    r = client.delete(f"/api/meetings/{mid}")

    assert r.status_code == 409 and "still recording" in r.json()["detail"]
    assert (storage.MEETINGS_DIR / mid).exists()


# --- settings -------------------------------------------------------------

def test_settings_offers_the_installed_models_and_devices(client):
    d = client.get("/api/settings").json()
    assert d["llm_models"] == ["qwen3:4b", "qwen3:0.6b"]
    assert "small" in d["whisper_models"]
    assert d["devices"]["mics"][0]["name"] == "Fake Mic"


def test_saving_settings_changes_what_the_next_meeting_uses(client):
    client.post("/api/settings", json={"whisper_model": "base", "llm_model": "qwen3:0.6b"})
    mid = client.post("/api/start").json()["meeting_id"]
    client.post("/api/stop")

    meta = json.loads((storage.MEETINGS_DIR / mid / "meta.json").read_text(encoding="utf-8"))
    assert meta["whisper_model"] == "base" and meta["llm_model"] == "qwen3:0.6b"


def test_a_bad_setting_is_rejected_with_a_readable_reason(client):
    r = client.post("/api/settings", json={"whisper_model": "enormous"})
    assert r.status_code == 400 and "unknown whisper model" in r.json()["detail"]


def test_settings_cannot_change_mid_recording(client):
    client.post("/api/start")
    r = client.post("/api/settings", json={"whisper_model": "base"})
    assert r.status_code == 409 and "stop the recording" in r.json()["detail"]


# --- the page -------------------------------------------------------------

def test_the_page_and_its_assets_are_served(client):
    assert client.get("/").status_code == 200
    for asset in ("/static/app.js", "/static/style.css"):
        assert client.get(asset).status_code == 200
