"""Meeting storage: one folder per meeting, no database.

Layout, per SPEC section 5:

    meetings/2026-09-02_1430_standup/
        audio.wav        stereo: L = you, R = them
        transcript.txt
        minutes.md
        meta.json
"""

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

# Tests and settings override this; everything below reads it lazily.
MEETINGS_DIR = Path("meetings")

# Folder names we generate: 2026-09-02_1430 with an optional _slug tail.
_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(_[a-z0-9-]+)?$")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40]


def _safe_dir(meeting_id: str) -> Path:
    """Resolve a meeting id to its folder, rejecting anything we did not name.

    This is the trust boundary: ids arrive from HTTP and reach shutil.rmtree.
    """
    if not _ID_RE.match(meeting_id):
        raise ValueError(f"bad meeting id: {meeting_id!r}")
    return MEETINGS_DIR / meeting_id


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_meeting(title: str = "") -> str:
    """Create the folder and meta.json, return the meeting id."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    slug = _slug(title)
    meeting_id = f"{stamp}_{slug}" if slug else stamp

    # Two meetings in the same minute would collide.
    base, n = meeting_id, 2
    while (MEETINGS_DIR / meeting_id).exists():
        meeting_id = f"{base}-{n}"
        n += 1

    d = MEETINGS_DIR / meeting_id
    (d / "chunks").mkdir(parents=True)
    write_meta(meeting_id, {"id": meeting_id, "title": title, "started_at": _now()})
    return meeting_id


def meeting_dir(meeting_id: str) -> Path:
    return _safe_dir(meeting_id)


def read_meta(meeting_id: str) -> dict:
    p = _safe_dir(meeting_id) / "meta.json"
    return json.loads(p.read_text(encoding="utf-8"))


def write_meta(meeting_id: str, meta: dict) -> None:
    p = _safe_dir(meeting_id) / "meta.json"
    p.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def update_meta(meeting_id: str, **fields) -> dict:
    meta = read_meta(meeting_id)
    meta.update(fields)
    write_meta(meeting_id, meta)
    return meta


def folder_size(d: Path) -> int:
    """Bytes on disk, chunks included — what deleting this folder frees."""
    total = 0
    for root, _dirs, files in os.walk(d):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def list_meetings() -> list[dict]:
    """Newest first. Folders without readable meta.json are skipped, not fatal."""
    if not MEETINGS_DIR.exists():
        return []
    out = []
    for d in MEETINGS_DIR.iterdir():
        if not d.is_dir() or not _ID_RE.match(d.name):
            continue
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # The folder name is the record; meta.json can go stale if it is renamed.
        meta["id"] = d.name
        meta["size_bytes"] = folder_size(d)
        meta["has_transcript"] = (d / "transcript.txt").exists()
        meta["has_minutes"] = (d / "minutes.md").exists()
        out.append(meta)
    out.sort(key=lambda m: m.get("id", ""), reverse=True)
    return out


def read_meeting(meeting_id: str) -> dict:
    d = _safe_dir(meeting_id)
    if not d.is_dir():
        raise FileNotFoundError(meeting_id)
    meta = read_meta(meeting_id)
    meta["id"] = meeting_id
    for name, key in (("transcript.txt", "transcript"), ("minutes.md", "minutes")):
        p = d / name
        meta[key] = p.read_text(encoding="utf-8") if p.exists() else ""
    return meta


def delete_meeting(meeting_id: str) -> None:
    d = _safe_dir(meeting_id)
    if not d.is_dir():
        raise FileNotFoundError(meeting_id)
    shutil.rmtree(d)
