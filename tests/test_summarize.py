"""Prompt assembly and response handling against a stub. No Ollama needed."""

import urllib.error

import pytest

from app import summarize


def stub(response="## Summary\n\nWe shipped.\n", capture=None):
    def _post(path, payload, timeout=None):
        if capture is not None:
            capture.append((path, payload))
        return {"response": response}
    return _post


def test_prompt_carries_the_transcript_and_the_sections():
    seen = []
    summarize.summarize("[00:00:01] You: hello", post=stub(capture=seen))
    path, payload = seen[0]

    assert path == "/api/generate"
    assert payload["stream"] is False
    assert "[00:00:01] You: hello" in payload["prompt"]
    for section in ("## Summary", "## Decisions", "## Action Items", "## Open Questions"):
        assert section in payload["prompt"]


def test_model_defaults_and_overrides():
    seen = []
    summarize.summarize("x", post=stub(capture=seen))
    assert seen[0][1]["model"] == summarize.DEFAULT_MODEL

    seen.clear()
    summarize.summarize("x", model="llama3:8b", post=stub(capture=seen))
    assert seen[0][1]["model"] == "llama3:8b"


def test_thinking_blocks_are_stripped():
    out = summarize.summarize(
        "x", post=stub("<think>hmm, let me plan\nmore planning</think>\n## Summary\n\nDone.")
    )
    assert out.startswith("## Summary")
    assert "think" not in out and "planning" not in out


def test_strip_thinking_leaves_normal_text_alone():
    assert summarize.strip_thinking("## Summary\n\nfine") == "## Summary\n\nfine"


def test_empty_think_block_from_no_think_mode_is_stripped():
    assert summarize.strip_thinking("<think>\n\n</think>\n\n## Summary") == "## Summary"


def test_no_think_is_sent_only_to_qwen3():
    seen = []
    summarize.summarize("x", model="qwen3:4b", post=stub(capture=seen))
    assert seen[0][1]["prompt"].startswith("/no_think\n")

    seen.clear()
    summarize.summarize("x", model="llama3:8b", post=stub(capture=seen))
    assert "/no_think" not in seen[0][1]["prompt"]


def test_empty_transcript_never_calls_the_model():
    called = []
    out = summarize.summarize("   ", post=stub(capture=called))
    assert called == []
    assert "No speech" in out


def test_short_transcript_has_no_note():
    out = summarize.summarize("[00:00:01] You: quick chat", post=stub())
    assert not out.startswith("> **Note:**")


def test_a_long_transcript_is_batched_rather_than_trimmed():
    """Superseded test_long_transcript_is_trimmed_from_the_head_with_a_note:
    long meetings are now split and digested, so nothing is left out."""
    seen = []
    line = "[00:00:01] Them: line {} " + "filler " * 15
    transcript = "\n".join(line.format(i) for i in range(4000))
    out = summarize.summarize(transcript, post=stub(capture=seen))

    assert len(seen) > 2, "must be batched, not sent as one prompt"
    sent = "\n".join(payload["prompt"] for _path, payload in seen)
    assert "line 0 " in sent and "line 3999 " in sent
    assert not out.startswith("> **Note:**")


def test_ollama_down_explains_itself():
    def refuse(path, payload, timeout=None):
        raise urllib.error.URLError("connection refused")

    with pytest.raises(summarize.SummarizeError) as e:
        summarize.summarize("x", post=refuse)
    assert "Is it running?" in str(e.value)


def test_missing_model_names_the_pull_command():
    def http_error(path, payload, timeout=None):
        raise urllib.error.HTTPError("u", 404, "not found", {}, None)

    with pytest.raises(summarize.SummarizeError) as e:
        summarize.summarize("x", model="nope:7b", post=http_error)
    assert "ollama pull nope:7b" in str(e.value)


def test_empty_response_is_an_error():
    with pytest.raises(summarize.SummarizeError):
        summarize.summarize("x", post=stub(response="   "))
