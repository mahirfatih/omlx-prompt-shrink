"""Unit tests for the oMLX Prompt Shrink MCP server.

These cover the pure helpers (token estimation, trimming, compaction splitting,
chunking) and the optional-tokenizer resolution logic. No network access and no
MCP transport are involved.
"""

from __future__ import annotations

import json
from types import ModuleType

import pytest

# --- _content_text ---------------------------------------------------------


def test_content_text_handles_string_none_and_parts(shrink: ModuleType) -> None:
    assert shrink._content_text(None) == ""
    assert shrink._content_text("hello") == "hello"
    assert shrink._content_text([{"text": "a"}, "b", {"no": "text"}]) == "a\nb"


# --- token estimation ------------------------------------------------------


def test_estimate_tokens_heuristic_uses_chars_over_four(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": "x" * 40}]
    assert shrink._estimate_tokens(messages) == 10


def test_estimate_tokens_never_returns_zero(shrink: ModuleType) -> None:
    assert shrink._estimate_tokens([]) == 1
    assert shrink._estimate_tokens([{"role": "user", "content": ""}]) == 1


def test_estimate_tokens_ignores_non_dict_messages(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": "x" * 8}, "not a dict"]
    assert shrink._estimate_tokens(messages) == 2


def test_estimate_context_reports_tokenizer_and_budget(shrink: ModuleType) -> None:
    payload = json.loads(
        shrink.estimate_context([{"role": "user", "content": "x" * 40}], max_context_tokens=4)
    )
    assert payload["estimated_context_tokens"] == 10
    assert payload["remaining_tokens"] == -6
    assert payload["should_trim"] is True
    assert payload["tokenizer"] == shrink._HEURISTIC_LABEL


def test_estimate_context_within_budget_is_not_trimmed(shrink: ModuleType) -> None:
    payload = json.loads(shrink.estimate_context([{"role": "user", "content": "x" * 40}]))
    assert payload["should_trim"] is False


# --- trimming --------------------------------------------------------------


def test_trim_keeps_the_last_messages_when_over_budget(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": str(i) + "x" * 400} for i in range(20)]
    payload = json.loads(
        shrink.trim_context(messages, keep_last=5, max_context_tokens=250)
    )
    assert payload["original_count"] == 20
    assert payload["trimmed_count"] == 5
    assert payload["messages"][-1]["content"] == messages[-1]["content"]


def test_trim_leaves_short_lists_untouched(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": "hi"}]
    payload = json.loads(shrink.trim_context(messages, keep_last=8))
    assert payload["messages"] == messages


# --- compaction splitting --------------------------------------------------


def test_split_keeps_leading_system_messages_and_tail(shrink: ModuleType) -> None:
    messages = [{"role": "system", "content": "s1"}, {"role": "system", "content": "s2"}]
    messages += [{"role": "user", "content": str(i)} for i in range(5)]
    leading, to_summarize, keep = shrink._split_for_compaction(messages, keep_last=2)
    assert [m["content"] for m in leading] == ["s1", "s2"]
    assert [m["content"] for m in keep] == ["3", "4"]
    assert [m["content"] for m in to_summarize] == ["0", "1", "2"]


def test_split_with_short_rest_summarizes_nothing(shrink: ModuleType) -> None:
    leading, to_summarize, keep = shrink._split_for_compaction(
        [{"role": "user", "content": "only"}], keep_last=8
    )
    assert leading == []
    assert to_summarize == []
    assert len(keep) == 1


# --- compaction behaviour --------------------------------------------------


def _long_history(count: int = 20) -> list[dict[str, str]]:
    return [{"role": "user", "content": str(i) + "y" * 4000} for i in range(count)]


def test_compact_reports_nothing_to_compact_for_short_history(shrink: ModuleType) -> None:
    payload = json.loads(shrink.compact_context([{"role": "user", "content": "hi"}]))
    assert payload["compacted"] is False
    assert payload["reason"] == "nothing_to_compact"


def test_compact_uses_provided_summary(shrink: ModuleType) -> None:
    messages = _long_history()
    payload = json.loads(
        shrink.compact_context(messages, keep_last=2, max_context_tokens=1000, summary="SUM")
    )
    assert payload["compacted"] is True
    assert payload["method"] == "provided"
    assert payload["summary"] == "SUM"
    assert payload["messages"][-1]["content"] == messages[-1]["content"]
    assert payload["messages"][0]["content"].startswith("[summary of earlier conversation]")


def test_compact_returns_plan_when_no_model(shrink: ModuleType) -> None:
    payload = json.loads(
        shrink.compact_context(_long_history(), keep_last=2, max_context_tokens=1000, model="")
    )
    assert payload["compacted"] is False
    assert payload["needs_summary"] is True
    assert payload["summary_prompt"] == shrink.SUMMARY_INSTRUCTIONS
    assert "messages" not in payload  # no message content is echoed back


def test_compact_respects_threshold_unless_forced(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": str(i) + "z" * 400} for i in range(5)]
    skipped = json.loads(shrink.compact_context(messages, keep_last=1))
    assert skipped["reason"] == "within_threshold"
    forced = json.loads(
        shrink.compact_context(messages, keep_last=1, summary="S", force=True)
    )
    assert forced["compacted"] is True


# --- chunking --------------------------------------------------------------


def test_chunk_messages_stays_within_budget(shrink: ModuleType) -> None:
    messages = [{"role": "user", "content": "w" * 400} for _ in range(10)]
    chunks = shrink._chunk_messages(messages, chunk_budget_tokens=250)
    assert sum(len(chunk) for chunk in chunks) == 10
    assert all(shrink._estimate_tokens(chunk) <= 250 for chunk in chunks)


# --- optional tokenizer ----------------------------------------------------


class _FakeEncoding:
    def encode(self, text: str) -> list[str]:
        return text.split()


class _FakeTiktoken:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_encoding(self, name: str) -> _FakeEncoding:
        self.calls.append(name)
        return _FakeEncoding()


class _BrokenTiktoken:
    def get_encoding(self, name: str) -> _FakeEncoding:
        raise ValueError("no such encoding")


def test_tokenizer_falls_back_when_tiktoken_missing(
    shrink: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "auto")
    monkeypatch.setattr(shrink, "tiktoken", None)
    monkeypatch.setattr(shrink, "_TOKENIZER", None)
    encode, label = shrink._resolve_tokenizer()
    assert encode is None
    assert label == shrink._HEURISTIC_LABEL


def test_tokenizer_uses_tiktoken_when_available(
    shrink: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeTiktoken()
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "auto")
    monkeypatch.setattr(shrink, "tiktoken", fake)
    monkeypatch.setattr(shrink, "_TOKENIZER", None)
    encode, label = shrink._resolve_tokenizer()
    assert label == "tiktoken:cl100k_base"
    assert fake.calls == ["cl100k_base"]
    assert encode("a b c") == ["a", "b", "c"]


def test_tokenizer_honours_explicit_encoding(
    shrink: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeTiktoken()
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "o200k_base")
    monkeypatch.setattr(shrink, "tiktoken", fake)
    monkeypatch.setattr(shrink, "_TOKENIZER", None)
    _, label = shrink._resolve_tokenizer()
    assert label == "tiktoken:o200k_base"
    assert fake.calls == ["o200k_base"]


def test_tokenizer_falls_back_on_unknown_encoding(
    shrink: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "does-not-exist")
    monkeypatch.setattr(shrink, "tiktoken", _BrokenTiktoken())
    monkeypatch.setattr(shrink, "_TOKENIZER", None)
    encode, label = shrink._resolve_tokenizer()
    assert encode is None
    assert label == shrink._HEURISTIC_LABEL


def test_tokenizer_disabled_by_heuristic_setting(
    shrink: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "off")
    monkeypatch.setattr(shrink, "tiktoken", _FakeTiktoken())
    monkeypatch.setattr(shrink, "_TOKENIZER", None)
    encode, label = shrink._resolve_tokenizer()
    assert encode is None
    assert label == shrink._HEURISTIC_LABEL
