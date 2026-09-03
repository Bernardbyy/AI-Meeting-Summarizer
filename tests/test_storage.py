import json

import pytest

from app import storage


@pytest.fixture(autouse=True)
def meetings_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MEETINGS_DIR", tmp_path / "meetings")
    return tmp_path / "meetings"


def test_new_meeting_creates_folder_and_meta(meetings_dir):
    mid = storage.new_meeting("Weekly Standup")
    d = meetings_dir / mid
    assert (d / "chunks").is_dir()
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["id"] == mid and meta["title"] == "Weekly Standup"
    assert mid.endswith("_weekly-standup")


def test_untitled_meeting_has_no_slug_tail(meetings_dir):
    mid = storage.new_meeting()
    assert storage._ID_RE.match(mid) and not mid.endswith("_")


def test_same_minute_meetings_do_not_collide(meetings_dir):
    a, b = storage.new_meeting("dup"), storage.new_meeting("dup")
    assert a != b and (meetings_dir / b).is_dir()


def test_list_is_newest_first_and_flags_artifacts(meetings_dir):
    old = storage.new_meeting("old")
    new = storage.new_meeting("new")
    # Force a later id so ordering is deterministic regardless of clock.
    (meetings_dir / new).rename(meetings_dir / "2099-01-01_0900_new")
    (meetings_dir / "2099-01-01_0900_new" / "minutes.md").write_text("x", encoding="utf-8")

    ids = [m["id"] for m in storage.list_meetings()]
    assert ids[0] == "2099-01-01_0900_new" and old in ids
    assert storage.list_meetings()[0]["has_minutes"] is True
    assert storage.list_meetings()[1]["has_transcript"] is False


def test_list_tolerates_junk_folders(meetings_dir):
    good = storage.new_meeting("good")
    (meetings_dir / "not-a-meeting").mkdir()
    (meetings_dir / "2026-01-01_0900_broken").mkdir()
    (meetings_dir / "2026-01-01_0900_broken" / "meta.json").write_text("{oops", encoding="utf-8")

    assert [m["id"] for m in storage.list_meetings()] == [good]


def test_list_on_missing_dir_is_empty():
    assert storage.list_meetings() == []


def test_read_meeting_includes_text_artifacts(meetings_dir):
    mid = storage.new_meeting("readme")
    (meetings_dir / mid / "transcript.txt").write_text("hello", encoding="utf-8")
    m = storage.read_meeting(mid)
    assert m["transcript"] == "hello" and m["minutes"] == ""


def test_update_meta_merges(meetings_dir):
    mid = storage.new_meeting()
    storage.update_meta(mid, duration_sec=42)
    meta = storage.read_meta(mid)
    assert meta["duration_sec"] == 42 and "started_at" in meta


def test_delete_removes_folder(meetings_dir):
    mid = storage.new_meeting()
    storage.delete_meeting(mid)
    assert not (meetings_dir / mid).exists()


def test_missing_meeting_raises(meetings_dir):
    meetings_dir.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        storage.delete_meeting("2026-01-01_0900_nope")


@pytest.mark.parametrize(
    "bad",
    ["../../etc", "..", "meetings/../..", "C:/Windows", "2026-01-01_0900_../x", ""],
)
def test_path_traversal_is_rejected(bad, meetings_dir):
    """Ids reach shutil.rmtree, so this is the boundary that matters."""
    with pytest.raises(ValueError):
        storage.delete_meeting(bad)
    with pytest.raises(ValueError):
        storage.read_meeting(bad)
