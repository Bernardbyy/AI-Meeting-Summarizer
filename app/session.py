"""One recording session: capture, transcribe-as-you-go, then summarize.

The transcription worker consumes chunks while the meeting is still running, so
pressing Stop usually leaves only the last chunk or two to process.

Chunk offsets accumulate per channel from real durations, in queue order. The
two channels are independent clocks and are only merged when the transcript is
formatted.
"""

import threading
import time
from pathlib import Path

from . import audio, storage, summarize, transcribe

# Whisper on an empty or near-empty wav is a waste; 44 bytes is a bare header.
MIN_CHUNK_BYTES = 1024


class Session:
    def __init__(self, meeting_id: str, model_name: str | None = None,
                 chunk_seconds: int = audio.CHUNK_SECONDS, recorder=None,
                 llm_model: str | None = None, mic_index: int | None = None,
                 loopback_index: int | None = None):
        self.meeting_id = meeting_id
        self.dir = storage.meeting_dir(meeting_id)
        self.model_name = model_name or transcribe.DEFAULT_MODEL
        self.llm_model = llm_model or summarize.DEFAULT_MODEL
        self.recorder = recorder or audio.Recorder(
            self.dir, chunk_seconds=chunk_seconds,
            mic_index=mic_index, loopback_index=loopback_index,
        )
        self.stage = "idle"
        self.stage_since = time.time()
        self.started_at = 0.0
        self.devices: dict = {}
        self.segments: list[dict] = []
        self.transcribed = 0
        self.errors: list[str] = []
        self._offsets = {"mic": 0.0, "sys": 0.0}
        self._worker: threading.Thread | None = None

    # --- lifecycle -----------------------------------------------------

    def _set_stage(self, stage: str):
        self.stage = stage
        self.stage_since = time.time()

    def start(self) -> dict:
        devices = self.recorder.start()
        self.started_at = time.time()
        self.devices = devices
        self._set_stage("recording")
        self._worker = threading.Thread(target=self._consume, name="transcriber",
                                        daemon=True)
        self._worker.start()
        return devices

    def stop(self) -> dict:
        """Stop capture, drain the queue, write transcript.txt and audio.wav."""
        duration = int(time.time() - self.started_at)
        self._set_stage("finishing")
        chunks = self.recorder.stop_capture()

        self._set_stage("transcribing")
        self.recorder.closed.put(None)  # sentinel: drain what is left
        if self._worker:
            self._worker.join()

        text = transcribe.format_transcript(self.segments)
        (self.dir / "transcript.txt").write_text(text, encoding="utf-8")

        # Everything from here down is best-effort: the transcript is already on
        # disk, so no later failure may take the meeting with it.
        self._set_stage("saving")
        audio_path = None
        try:
            audio_path = audio.build_audio(self.dir, chunks.get("mic", []),
                                           chunks.get("sys", []))
        except Exception as e:  # ffmpeg missing, killed, or fed a torn chunk
            self.errors.append(f"could not build audio.wav: {e}")

        self._set_stage("summarizing")
        minutes = ""
        try:
            minutes = summarize.summarize(text, model=self.llm_model)
            (self.dir / "minutes.md").write_text(minutes, encoding="utf-8")
        except summarize.SummarizeError as e:
            self.errors.append(str(e))

        self._set_stage("idle")
        self.errors += self.recorder.errors
        return {
            "meeting_id": self.meeting_id,
            "duration_sec": duration,
            "audio": audio_path.name if audio_path else None,
            "transcript": text,
            "minutes": minutes,
            "errors": self.errors,
        }

    # --- worker --------------------------------------------------------

    def _consume(self):
        q = self.recorder.closed
        while True:
            item = q.get()
            if item is None:
                return
            try:
                self._transcribe(Path(item["path"]), item["channel"])
            except Exception as e:  # one bad chunk must not lose the meeting
                self.errors.append(f"{Path(item['path']).name}: {e}")
            finally:
                self.transcribed += 1

    def _transcribe(self, path: Path, channel: str):
        if not path.exists() or path.stat().st_size < MIN_CHUNK_BYTES:
            return
        offset = self._offsets[channel]
        self._offsets[channel] = offset + transcribe.wav_duration(path)
        self.segments += transcribe.transcribe_chunk(
            path, channel, offset, model_name=self.model_name
        )

    # --- reporting -----------------------------------------------------

    def status(self) -> dict:
        elapsed = int(time.time() - self.started_at) if self.started_at else 0
        return {
            "stage": self.stage,
            "meeting_id": self.meeting_id,
            "elapsed_sec": elapsed if self.stage == "recording" else 0,
            "stage_sec": int(time.time() - self.stage_since),
            "closed": self.recorder.closed_count,
            "transcribed": self.transcribed,
            "devices": self.devices,
            "models": {"whisper": self.model_name, "llm": self.llm_model},
            "errors": self.errors + self.recorder.errors,
        }
