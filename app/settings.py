"""User settings, persisted next to the code in settings.json.

Small and flat on purpose: five values, no schema library, no migrations.
Unknown keys are rejected rather than stored, so a hand-edited file cannot
quietly grow fields nothing reads.
"""

import json
from pathlib import Path

from . import storage, summarize, transcribe

SETTINGS_FILE = Path("settings.json")

# faster-whisper accepts these names and downloads on first use.
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

DEFAULTS = {
    "whisper_model": transcribe.DEFAULT_MODEL,
    "llm_model": summarize.DEFAULT_MODEL,
    "mic_index": None,
    "loopback_index": None,
    "meetings_dir": "meetings",
}


def load() -> dict:
    s = dict(DEFAULTS)
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return s
    if isinstance(stored, dict):
        s.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return s


def validate(patch: dict) -> dict:
    """Reject bad values loudly instead of writing them and failing at Start."""
    clean = {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting: {key}")

        if key == "whisper_model":
            if value not in WHISPER_MODELS:
                raise ValueError(f"unknown whisper model: {value}")
        elif key == "llm_model":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("llm_model must be a model name")
            value = value.strip()
        elif key in ("mic_index", "loopback_index"):
            if value is not None and not isinstance(value, int):
                raise ValueError(f"{key} must be a device index or null")
        elif key == "meetings_dir":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("meetings_dir must be a path")
            value = value.strip()
            try:
                Path(value).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValueError(f"cannot use that folder: {e}") from e

        clean[key] = value
    return clean


def save(patch: dict) -> dict:
    s = load()
    s.update(validate(patch))
    SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    apply(s)
    return s


def apply(s: dict | None = None) -> dict:
    """Push settings into the modules that read them at call time."""
    s = s or load()
    storage.MEETINGS_DIR = Path(s["meetings_dir"])
    storage.MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
    return s
