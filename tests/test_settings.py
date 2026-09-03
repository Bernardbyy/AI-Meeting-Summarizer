import json

import pytest

from app import settings, storage


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(storage, "MEETINGS_DIR", tmp_path / "meetings")
    return tmp_path


def test_defaults_when_no_file():
    assert settings.load() == settings.DEFAULTS


def test_missing_keys_fall_back_to_defaults(isolated):
    settings.SETTINGS_FILE.write_text(json.dumps({"whisper_model": "base"}), encoding="utf-8")
    s = settings.load()
    assert s["whisper_model"] == "base"
    assert s["llm_model"] == settings.DEFAULTS["llm_model"]


def test_corrupt_file_falls_back_instead_of_crashing(isolated):
    settings.SETTINGS_FILE.write_text("{not json", encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_unknown_keys_in_file_are_ignored(isolated):
    settings.SETTINGS_FILE.write_text(json.dumps({"nonsense": 1}), encoding="utf-8")
    assert "nonsense" not in settings.load()


def test_save_round_trips(isolated):
    settings.save({"whisper_model": "medium", "llm_model": "llama3:8b"})
    s = settings.load()
    assert s["whisper_model"] == "medium" and s["llm_model"] == "llama3:8b"


def test_save_merges_rather_than_replaces(isolated):
    settings.save({"whisper_model": "base"})
    settings.save({"llm_model": "qwen3:0.6b"})
    s = settings.load()
    assert s["whisper_model"] == "base" and s["llm_model"] == "qwen3:0.6b"


@pytest.mark.parametrize("patch", [
    {"whisper_model": "enormous"},
    {"llm_model": "  "},
    {"mic_index": "not-a-number"},
    {"meetings_dir": ""},
    {"made_up_setting": 1},
])
def test_bad_values_are_rejected(patch):
    with pytest.raises(ValueError):
        settings.validate(patch)


def test_nothing_is_written_when_validation_fails(isolated):
    with pytest.raises(ValueError):
        settings.save({"whisper_model": "enormous"})
    assert not settings.SETTINGS_FILE.exists()


def test_null_device_index_means_system_default():
    assert settings.validate({"mic_index": None}) == {"mic_index": None}
    assert settings.validate({"mic_index": 15}) == {"mic_index": 15}


def test_meetings_dir_is_created_and_applied(isolated):
    target = isolated / "somewhere" / "else"
    settings.save({"meetings_dir": str(target)})
    assert target.is_dir()
    assert storage.MEETINGS_DIR == target


def test_meetings_land_in_the_configured_folder(isolated):
    target = isolated / "recordings"
    settings.save({"meetings_dir": str(target)})
    mid = storage.new_meeting("elsewhere")
    assert (target / mid / "meta.json").exists()
