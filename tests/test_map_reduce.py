"""Batched summarization: every line of the meeting must be read.

The old behaviour trimmed the front of a long transcript and said so. The
promise now is stronger: nothing is dropped, whatever the meeting's length.
"""

import pytest

from app import summarize


def transcript(minutes, per_minute=6):
    """A transcript that looks like the real one, with unique, findable lines."""
    out = []
    for m in range(minutes):
        for i in range(per_minute):
            who = "You" if i % 2 else "Them"
            out.append(f"[{m // 60:02d}:{m % 60:02d}:{i * 10:02d}] {who}: "
                       f"line {m}-{i} " + ("filler words here " * 4).strip())
    return "\n".join(out)


class Recorder:
    """Stands in for Ollama, remembering every prompt it was sent."""

    def __init__(self, reply="## Summary\n\nminutes\n"):
        self.prompts = []
        self.payloads = []
        self.reply = reply

    def __call__(self, path, payload, timeout=None):
        self.prompts.append(payload["prompt"])
        self.payloads.append(payload)
        return {"response": self.reply}


# --- splitting ------------------------------------------------------------

def test_every_line_survives_the_split():
    """The whole point: no line may be lost between the transcript and the model."""
    text = transcript(90)
    segments = summarize.split_transcript(text, budget=8000)

    rejoined = "\n".join(segments).splitlines()
    assert rejoined == text.splitlines()


def test_segments_respect_the_budget():
    segments = summarize.split_transcript(transcript(90), budget=8000)
    assert len(segments) > 1
    assert all(len(s) <= 8000 for s in segments)


def test_a_line_is_never_cut_in_half():
    text = transcript(30)
    segments = summarize.split_transcript(text, budget=3000)
    originals = set(text.splitlines())
    for seg in segments:
        for line in seg.splitlines():
            assert line in originals


def test_an_oversized_single_line_gets_its_own_segment_rather_than_being_dropped():
    long_line = "[00:00:01] Them: " + "word " * 5000
    text = f"[00:00:00] You: short\n{long_line}\n[00:00:02] You: also short"
    segments = summarize.split_transcript(text, budget=500)

    assert long_line in "\n".join(segments).splitlines()
    assert len(segments) == 3


def test_splitting_nothing_yields_nothing():
    assert summarize.split_transcript("", budget=1000) == []
    assert summarize.split_transcript("   \n  \n", budget=1000) == []


# --- the fast path --------------------------------------------------------

def test_a_short_meeting_still_takes_exactly_one_call():
    rec = Recorder()
    summarize.summarize("[00:00:01] You: quick chat", post=rec)
    assert len(rec.prompts) == 1


def test_a_short_meeting_is_never_annotated():
    rec = Recorder()
    out = summarize.summarize("[00:00:01] You: quick chat", post=rec)
    assert not out.startswith("> **Note:**")


# --- batching -------------------------------------------------------------

def test_a_long_meeting_is_summarized_in_batches():
    rec = Recorder()
    summarize.summarize(transcript(120), post=rec)
    assert len(rec.prompts) > 2, "a two-hour meeting must be split, not sent whole"


def test_no_content_is_dropped_from_a_long_meeting():
    """Every line must appear in some prompt we actually sent."""
    text = transcript(120)
    rec = Recorder()
    summarize.summarize(text, post=rec)

    sent = "\n".join(rec.prompts)
    for line in text.splitlines():
        assert line in sent, f"this line never reached the model: {line[:60]}"


def test_a_long_meeting_is_never_annotated_as_truncated():
    rec = Recorder()
    out = summarize.summarize(transcript(120), post=rec)
    assert "left out of these minutes" not in out


def test_the_final_minutes_come_from_the_last_call():
    """The last call is the one that combines the digests into the minutes."""
    rec = Recorder(reply="## Summary\n\nthe combined minutes\n")
    out = summarize.summarize(transcript(120), post=rec)
    assert "the combined minutes" in out


def test_progress_is_reported_for_every_batch():
    seen = []
    summarize.summarize(transcript(120), post=Recorder(),
                        progress=lambda done, total: seen.append((done, total)))

    assert seen, "a multi-minute wait must report progress"
    assert seen[-1][0] == seen[-1][1], "progress must finish at 100%"
    assert all(d <= t for d, t in seen)


def test_a_very_long_meeting_still_terminates():
    """Digests of a six-hour meeting may themselves overflow; reduce again."""
    rec = Recorder(reply="digest " * 400)
    out = summarize.summarize(transcript(360), post=rec)
    assert out
    assert len(rec.prompts) < 200, "recursion must converge, not explode"


# --- the truncation guard -------------------------------------------------

def test_instructions_come_after_the_transcript():
    """Ollama drops the OLDEST tokens when a prompt overflows. Instructions
    last means an overflow costs transcript, not the output format."""
    rec = Recorder()
    summarize.summarize("[00:00:01] You: hello", post=rec)
    prompt = rec.prompts[0]

    assert prompt.index("hello") < prompt.index("## Summary")


def test_the_sections_are_still_requested():
    rec = Recorder()
    summarize.summarize("[00:00:01] You: hello", post=rec)
    for section in ("## Summary", "## Decisions", "## Action Items", "## Open Questions"):
        assert section in rec.prompts[0]


# --- failure --------------------------------------------------------------

def test_a_failure_mid_batch_is_reported_not_swallowed():
    calls = {"n": 0}

    def fail_on_third(path, payload, timeout=None):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("connection reset")
        return {"response": "digest"}

    with pytest.raises(summarize.SummarizeError):
        summarize.summarize(transcript(120), post=fail_on_third)


def test_empty_transcript_never_calls_the_model():
    rec = Recorder()
    out = summarize.summarize("   ", post=rec)
    assert rec.prompts == [] and "No speech" in out


# --- runtime guards -------------------------------------------------------
# Generation on CPU is ~7 tok/s, so output length is the runtime. An unbounded
# digest of one segment measured at ~15 minutes; these caps are what make
# batching faster than not batching.

def test_every_call_caps_its_output_length():
    rec = Recorder()
    summarize.summarize(transcript(120), post=rec)
    for payload in rec.payloads:
        assert payload["options"]["num_predict"] > 0


def test_digests_are_capped_harder_than_the_final_minutes():
    rec = Recorder()
    summarize.summarize(transcript(120), post=rec)
    caps = [p["options"]["num_predict"] for p in rec.payloads]
    assert caps[-1] > caps[0], "the minutes may be longer than any single digest"
    assert max(caps[:-1]) <= summarize.DIGEST_MAX_TOKENS


def test_the_digest_prompt_states_a_bullet_limit():
    """Without an explicit ceiling the model rewrites the segment line by line."""
    rec = Recorder()
    summarize.summarize(transcript(120), post=rec)
    assert f"At most {summarize.DIGEST_BULLETS} bullets" in rec.prompts[0]
