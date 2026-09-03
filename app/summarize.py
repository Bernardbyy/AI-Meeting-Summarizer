"""Transcript -> meeting minutes, via a local Ollama model.

127.0.0.1:11434 is the only network address this app ever talks to. Nothing
leaves the machine.
"""

import json
import os
import re
import urllib.error
import urllib.request

OLLAMA = os.environ.get("MEETINGAI_OLLAMA", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("MEETINGAI_LLM", "qwen3:4b")

# CPU generation is slow; a long transcript can legitimately take many minutes.
TIMEOUT = int(os.environ.get("MEETINGAI_LLM_TIMEOUT", 1800))

# ponytail: one prompt over the whole transcript. Ceiling: roughly 30-40 minutes
# of meeting at NUM_CTX 8192. Beyond that the head is dropped and the minutes say
# so. Upgrade path is chunked map-reduce behind this same summarize() signature.
NUM_CTX = int(os.environ.get("MEETINGAI_NUM_CTX", 8192))
RESERVED_TOKENS = 1200  # prompt scaffolding + room to write the minutes

PROMPT = """You are writing the minutes of a meeting from its transcript.

"You" is the person whose microphone recorded this. "Them" is everyone else,
heard through the computer speakers. Individual remote speakers are not
distinguished, so never invent names.

Write Markdown with exactly these sections, in this order:

## Summary
Three to six sentences on what the meeting was about and what came of it.

## Decisions
What was actually decided. One bullet each. If nothing was decided, write "None".

## Action Items
One bullet each, as "- Owner — task (deadline if stated)". Use "You" or
"Unassigned" when the owner is unclear. If there are none, write "None".

## Open Questions
Anything raised and left unresolved. If there are none, write "None".

Rules: use only what the transcript says, never guess at anything that was not
said, do not add sections beyond the four above, and write entirely in English.

TRANSCRIPT
----------
{transcript}
"""

TRUNCATION_NOTE = (
    "> **Note:** the transcript was too long for the model context, so the "
    "earliest {dropped} characters were left out of these minutes. The full "
    "transcript is in `transcript.txt`.\n\n"
)


class SummarizeError(RuntimeError):
    pass


def no_think(model: str, prompt: str) -> str:
    """Qwen3 reasons before answering unless told not to, and on CPU that costs
    far more than the answer: 3m42s vs 15s on the same transcript, measured.
    The `think` API field is ignored by this Ollama build; the prompt directive
    is what actually works. Other model families ignore the line, so only send
    it where it means something."""
    return f"/no_think\n{prompt}" if model.startswith("qwen3") else prompt


def _post(path: str, payload: dict, timeout: int = TIMEOUT) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_models() -> list[str]:
    """Installed Ollama models, for the settings dropdown."""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return sorted(m["name"] for m in data.get("models", []))


def strip_thinking(text: str) -> str:
    """Reasoning models (qwen3, deepseek-r1) emit <think> blocks. Drop them."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _fit(transcript: str) -> tuple[str, int]:
    """Trim the head to fit the context window. Returns (text, chars dropped).

    Roughly 4 characters per token; the tail is kept because decisions and
    action items land at the end of a meeting.
    """
    budget = max(1000, (NUM_CTX - RESERVED_TOKENS) * 4)
    if len(transcript) <= budget:
        return transcript, 0
    return transcript[-budget:], len(transcript) - budget


def summarize(transcript: str, model: str | None = None, post=None) -> str:
    """Minutes as Markdown. Raises SummarizeError if Ollama cannot be reached."""
    transcript = (transcript or "").strip()
    if not transcript:
        # Nothing was said; do not spend minutes of CPU discovering that.
        return "## Summary\n\nNo speech was detected in this recording.\n"

    model = model or DEFAULT_MODEL
    text, dropped = _fit(transcript)
    send = post or _post

    try:
        data = send("/api/generate", {
            "model": model,
            "prompt": no_think(model, PROMPT.format(transcript=text)),
            "stream": False,
            "options": {"num_ctx": NUM_CTX, "temperature": 0.2},
        })
    except urllib.error.HTTPError as e:
        raise SummarizeError(
            f"Ollama rejected the request ({e.code}). Is the model {model!r} installed? "
            f"Run: ollama pull {model}"
        ) from e
    except (urllib.error.URLError, OSError) as e:
        raise SummarizeError(
            f"Could not reach Ollama at {OLLAMA} ({e}). Is it running?"
        ) from e

    minutes = strip_thinking(data.get("response", ""))
    if not minutes:
        raise SummarizeError(f"{model} returned nothing")
    if dropped:
        minutes = TRUNCATION_NOTE.format(dropped=dropped) + minutes
    return minutes
