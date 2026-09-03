"""WASAPI dual capture: your mic and everything you hear, to disk, in chunks.

Two independent streams. Each owns its writer and its own chunk clock, because
devices do not have to agree on sample rate (a USB headset at 44.1kHz next to
speakers at 48kHz is normal). The two sides are reconciled only at Stop, by ffmpeg.

Files under a meeting folder:

    chunks/mic_000.wav   native rate, as captured
    chunks/sys_000.wav
    audio.wav            built at Stop: stereo, L = you, R = them

Chunks are written continuously, so a crash costs at most one chunk.
"""

import os
import queue
import subprocess
import threading
import wave
from pathlib import Path

import pyaudiowpatch as pyaudio

CHUNK_SECONDS = int(os.environ.get("MEETINGAI_CHUNK_SECONDS", 60))
FRAMES_PER_BUFFER = 1024
SAMPLE_FORMAT = pyaudio.paInt16
SAMPLE_WIDTH = 2


def _wasapi(p):
    return p.get_host_api_info_by_type(pyaudio.paWASAPI)


def list_devices() -> dict:
    """Selectable capture devices, for the settings panel."""
    p = pyaudio.PyAudio()
    try:
        w = _wasapi(p)
        mics = [
            {"index": i["index"], "name": i["name"], "channels": i["maxInputChannels"],
             "rate": int(i["defaultSampleRate"])}
            for i in (p.get_device_info_by_host_api_device_index(w["index"], n)
                      for n in range(w["deviceCount"]))
            if i["maxInputChannels"] > 0 and "[Loopback]" not in i["name"]
        ]
        loopbacks = [
            {"index": i["index"], "name": i["name"], "channels": i["maxInputChannels"],
             "rate": int(i["defaultSampleRate"])}
            for i in p.get_loopback_device_info_generator()
        ]
        d = default_devices(p)
        return {"mics": mics, "loopbacks": loopbacks,
                "default_mic": d[0]["index"], "default_loopback": d[1]["index"]}
    finally:
        p.terminate()


def default_devices(p) -> tuple[dict, dict]:
    """(mic, loopback-of-default-output). Raises if no loopback exists."""
    w = _wasapi(p)
    mic = p.get_device_info_by_index(w["defaultInputDevice"])
    speakers = p.get_device_info_by_index(w["defaultOutputDevice"])

    for lb in p.get_loopback_device_info_generator():
        if speakers["name"] in lb["name"]:
            return mic, lb
    raise RuntimeError(f"no loopback device for output {speakers['name']!r}")


class _StreamWriter(threading.Thread):
    """Reads one device forever, rotating a wav file every CHUNK_SECONDS."""

    def __init__(self, p, device: dict, label: str, chunks_dir: Path,
                 chunk_seconds: int, on_chunk, on_error):
        super().__init__(name=f"capture-{label}", daemon=True)
        self._p = p
        self._device = device
        self.label = label
        self._dir = chunks_dir
        self._chunk_frames = int(device["defaultSampleRate"]) * chunk_seconds
        self._on_chunk = on_chunk
        self._on_error = on_error
        self._stopping = threading.Event()
        self.rate = int(device["defaultSampleRate"])
        self.channels = device["maxInputChannels"]
        self.chunks: list[Path] = []

    def _open_chunk(self) -> wave.Wave_write:
        path = self._dir / f"{self.label}_{len(self.chunks):03d}.wav"
        self.chunks.append(path)
        w = wave.open(str(path), "wb")
        w.setnchannels(self.channels)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(self.rate)
        return w

    def run(self):
        stream = writer = None
        try:
            stream = self._p.open(
                format=SAMPLE_FORMAT,
                channels=self.channels,
                rate=self.rate,
                input=True,
                input_device_index=self._device["index"],
                frames_per_buffer=FRAMES_PER_BUFFER,
            )
            writer = self._open_chunk()
            written = 0
            while not self._stopping.is_set():
                data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
                writer.writeframes(data)
                written += FRAMES_PER_BUFFER
                if written >= self._chunk_frames:
                    writer.close()
                    self._on_chunk(self.chunks[-1], self.label, len(self.chunks) - 1)
                    writer, written = self._open_chunk(), 0
        except Exception as e:  # device vanished, format rejected, etc.
            self._on_error(self.label, e)
        finally:
            if writer is not None:
                try:
                    writer.close()
                    # Final partial chunk still counts.
                    self._on_chunk(self.chunks[-1], self.label, len(self.chunks) - 1)
                except Exception:
                    pass
            if stream is not None:
                stream.stop_stream()
                stream.close()

    def stop(self):
        self._stopping.set()


class Recorder:
    """Start/stop dual capture into one meeting folder."""

    def __init__(self, meeting_dir: Path, chunk_seconds: int = CHUNK_SECONDS,
                 mic_index: int | None = None, loopback_index: int | None = None):
        self.dir = Path(meeting_dir)
        self.chunks_dir = self.dir / "chunks"
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self._chunk_seconds = chunk_seconds
        self._mic_index = mic_index
        self._loopback_index = loopback_index
        self._p = None
        self._writers: list[_StreamWriter] = []
        self.errors: list[str] = []
        # Closed chunks, consumed by the transcription worker.
        self.closed: queue.Queue = queue.Queue()
        self.closed_count = 0

    def _resolve(self):
        mic, loop = default_devices(self._p)
        if self._mic_index is not None:
            mic = self._p.get_device_info_by_index(self._mic_index)
        if self._loopback_index is not None:
            loop = self._p.get_device_info_by_index(self._loopback_index)
        return mic, loop

    def start(self):
        self._p = pyaudio.PyAudio()
        mic, loop = self._resolve()
        for device, label in ((mic, "mic"), (loop, "sys")):
            w = _StreamWriter(self._p, device, label, self.chunks_dir,
                              self._chunk_seconds, self._on_chunk, self._on_error)
            self._writers.append(w)
            w.start()
        return {"mic": mic["name"], "loopback": loop["name"]}

    def _on_chunk(self, path, label, index):
        self.closed_count += 1
        self.closed.put({"path": str(path), "channel": label, "index": index})

    def _on_error(self, label, exc):
        self.errors.append(f"{label}: {exc}")

    @property
    def chunk_count(self) -> int:
        """Chunks started, including the one still being written."""
        return sum(len(w.chunks) for w in self._writers)

    def stop_capture(self) -> dict[str, list[Path]]:
        """Stop both streams and return the chunks each wrote.

        Every remaining chunk is on the queue by the time this returns, so a
        consumer that then reads until its sentinel sees all of them.
        """
        for w in self._writers:
            w.stop()
        for w in self._writers:
            w.join(timeout=5)
        if self._p is not None:
            self._p.terminate()
            self._p = None
        by_label = {w.label: [p for p in w.chunks if p.exists() and p.stat().st_size > 44]
                    for w in self._writers}
        self._writers = []
        return by_label


def _concat_list(paths: list[Path], listfile: Path) -> Path:
    listfile.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in paths), encoding="utf-8"
    )
    return listfile


def build_audio(meeting_dir: Path, mic_chunks: list[Path], sys_chunks: list[Path],
                rate: int = 48000) -> Path | None:
    """Concatenate each side and interleave: L = you, R = them.

    Each side is downmixed to mono first, so the two channels stay independently
    listenable and the file is half the size of true 4-channel audio.
    """
    meeting_dir = Path(meeting_dir)
    out = meeting_dir / "audio.wav"
    if not mic_chunks and not sys_chunks:
        return None

    cmd = ["ffmpeg", "-nostdin", "-y", "-loglevel", "error"]
    parts, filters = [], []
    for i, (chunks, name) in enumerate(((mic_chunks, "l"), (sys_chunks, "r"))):
        if not chunks:
            continue
        lst = _concat_list(chunks, meeting_dir / f"chunks/_{name}.txt")
        cmd += ["-f", "concat", "-safe", "0", "-i", str(lst)]
        filters.append(
            f"[{len(parts)}:a]aformat=sample_fmts=s16:sample_rates={rate},"
            f"pan=mono|c0=0.5*c0+0.5*c1[{name}]"
        )
        parts.append(name)

    if len(parts) == 2:
        filters.append("[l][r]amerge=inputs=2[a]")
        mapped, channels = "[a]", "2"
    else:
        # ponytail: one side missing (device failed) -> mono file rather than no file.
        mapped, channels = f"[{parts[0]}]", "1"

    cmd += ["-filter_complex", ";".join(filters), "-map", mapped, "-ac", channels, str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        for name in ("l", "r"):
            (meeting_dir / f"chunks/_{name}.txt").unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[:400]}")
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(list_devices(), indent=2))
