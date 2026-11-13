#!/usr/bin/env python3
"""oMLX context guard MCP server.

Keeps local OpenAI-compatible servers (oMLX, llama.cpp, LM Studio, ...) under
their context window, with three levels of intervention:

* ``estimate_context`` - measure only, no changes.
* ``trim_context``     - drop the oldest messages.
* ``compact_context``  - replace the oldest messages with a summary.

The server is deliberately dependency-light: the MCP SDK plus the standard
library. ``compact_context`` can summarise with the local model through the
OpenAI-compatible endpoint, or accept a summary you already produced.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from mcp.server import MCPServer

try:  # optional: a real tokenizer is used when available, otherwise a heuristic
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

MAX_CONTEXT_TOKENS = 32768
DEFAULT_KEEP_LAST = 8
DEFAULT_THRESHOLD = 0.8
DEFAULT_SUMMARY_BUDGET_TOKENS = 512

DEFAULT_BASE_URL = os.environ.get("OMLX_SHRINK_BASE_URL", "http://127.0.0.1:8000/v1")
DEFAULT_API_KEY = os.environ.get("OMLX_SHRINK_API_KEY", "")
DEFAULT_MODEL = os.environ.get("OMLX_SHRINK_MODEL", "")
SUMMARY_TIMEOUT_SECONDS = float(os.environ.get("OMLX_SHRINK_TIMEOUT", "180"))

SUMMARY_INSTRUCTIONS = (
    "You compact conversation history for a coding agent. Write a dense summary "
    "that preserves: the user's goal, every decision and constraint, file paths "
    "and code identifiers, commands that were run and their key results, and any "
    "unresolved question or next step. Omit greetings, restated instructions and "
    "redundant detail. Write plain prose in the same language as the conversation. "
    "Do not add a preamble such as 'Here is a summary'."
)

logger = logging.getLogger("omlx-prompt-shrink")
logger.addHandler(logging.StreamHandler(sys.stderr))
logger.setLevel(logging.INFO)

_HEURISTIC_LABEL = "heuristic(chars/4)"
_TOKENIZER: tuple[Any, str] | None = None


def _resolve_tokenizer() -> tuple[Any, str]:
    """Return ``(encode_callable_or_None, label)``, resolved once and cached.

    ``OMLX_SHRINK_TOKENIZER`` controls the choice:

    * ``auto`` (default) - use ``tiktoken``'s ``cl100k_base`` when installed;
      otherwise fall back to the character heuristic.
    * a tiktoken encoding name (for example ``o200k_base``) - use that encoding.
    * ``heuristic`` / ``off`` / ``none`` / ``chars`` - always use the heuristic.
    """
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER

    setting = os.environ.get("OMLX_SHRINK_TOKENIZER", "auto").strip().lower()
    fallback: tuple[Any, str] = (None, _HEURISTIC_LABEL)
    if setting in {"heuristic", "off", "none", "chars", ""}:
        _TOKENIZER = fallback
        return _TOKENIZER
    if tiktoken is None:
        if setting != "auto":
            logger.warning(
                "OMLX_SHRINK_TOKENIZER=%r requested but tiktoken is not installed; "
                "using %s",
                setting,
                _HEURISTIC_LABEL,
            )
        _TOKENIZER = fallback
        return _TOKENIZER

    encoding_name = "cl100k_base" if setting == "auto" else setting
    try:
        encoder = tiktoken.get_encoding(encoding_name)
    except Exception as error:  # network/IO failure or unknown encoding
        logger.warning("tokenizer %r unavailable (%s); using %s", encoding_name, error, _HEURISTIC_LABEL)
        _TOKENIZER = fallback
        return _TOKENIZER

    _TOKENIZER = (encoder.encode, f"tiktoken:{encoding_name}")
    return _TOKENIZER


server = MCPServer("oMLX Prompt Shrink")


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    encode, _ = _resolve_tokenizer()
    if encode is not None:
        text = "\n".join(
            _content_text(message.get("content", ""))
            for message in messages
            if isinstance(message, dict)
        )
        try:
            return max(1, len(encode(text)))
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("tokenizer failed (%s); using %s", error, _HEURISTIC_LABEL)
    chars = 0
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else ""
        chars += len(_content_text(content))
    return max(1, int(math.ceil(chars / 4)))


def estimate_context_tokens(
    messages: list[dict[str, Any]],
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
) -> int:
    return min(_estimate_tokens(messages), max_context_tokens)


def _trim_messages(
    messages: list[dict[str, Any]],
    keep_last: int = DEFAULT_KEEP_LAST,
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
) -> list[dict[str, Any]]:
    result = list(messages)
    while len(result) > keep_last and _estimate_tokens(result) > max_context_tokens:
        result = result[1:]
    return result


def _split_for_compaction(
    messages: list[dict[str, Any]],
    keep_last: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split into (leading system, to summarise, to keep verbatim)."""
    keep_last = max(1, keep_last)
    leading: list[dict[str, Any]] = []
    index = 0
    total = len(messages)
    while index < total and isinstance(messages[index], dict) and messages[index].get("role") == "system":
        leading.append(messages[index])
        index += 1
    rest = list(messages[index:])
    if len(rest) <= keep_last:
        return leading, [], rest
    return leading, rest[:-keep_last], rest[-keep_last:]


def _assemble_compaction(
    leading: list[dict[str, Any]],
    summary: str,
    keep: list[dict[str, Any]],
    summary_role: str = "system",
) -> list[dict[str, Any]]:
    note = {
        "role": summary_role,
        "content": "[summary of earlier conversation]\n" + summary.strip() + "\n[end of summary]",
    }
    return [*leading, note, *keep]


def _render_for_model(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "?") if isinstance(message, dict) else "?"
        content = message.get("content", "") if isinstance(message, dict) else ""
        lines.append(f"{role}: {_content_text(content)}")
    return "\n".join(lines)


def _chunk_messages(
    messages: list[dict[str, Any]],
    chunk_budget_tokens: int,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in messages:
        candidate = [*current, message]
        if current and _estimate_tokens(candidate) > chunk_budget_tokens:
            chunks.append(current)
            current = [message]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _call_chat_completions(
    prompt_messages: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
) -> str:
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    payload = {
        "model": model,
        "messages": prompt_messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=SUMMARY_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"summarizer endpoint returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"summarizer endpoint unreachable: {error.reason}") from error
    try:
        return str(body["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"unexpected summarizer response: {json.dumps(body)[:500]}") from error


def _summarize(
    to_summarize: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    model: str,
    max_context_tokens: int,
    summary_budget_tokens: int,
) -> str:
    chunk_budget = max(1024, max_context_tokens - summary_budget_tokens - 1024)
    chunks = _chunk_messages(to_summarize, chunk_budget)
    summaries: list[str] = []
    for chunk in chunks:
        prompt = [
            {"role": "system", "content": SUMMARY_INSTRUCTIONS},
            {"role": "user", "content": _render_for_model(chunk)},
        ]
        summaries.append(
            _call_chat_completions(prompt, base_url, api_key, model, summary_budget_tokens)
        )
    if len(summaries) == 1:
        return summaries[0]
    merged = "\n\n".join(summaries)
    merge_prompt = [
        {
            "role": "system",
            "content": "Merge these partial summaries into one, without losing facts or repeating.",
        },
        {"role": "user", "content": merged},
    ]
    try:
        return _call_chat_completions(
            merge_prompt, base_url, api_key, model, summary_budget_tokens
        )
    except RuntimeError:
        return merged


@server.tool()
def estimate_context(
    messages: list[dict[str, Any]],
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
) -> str:
    """Estimate the current context size in tokens before sending it to the model."""
    estimated = _estimate_tokens(messages)
    _, tokenizer = _resolve_tokenizer()
    return json.dumps(
        {
            "estimated_context_tokens": estimated,
            "max_context_tokens": max_context_tokens,
            "remaining_tokens": max_context_tokens - estimated,
            "should_trim": estimated > max_context_tokens,
            "message_count": len(messages),
            "tokenizer": tokenizer,
        },
        ensure_ascii=False,
    )


@server.tool()
def trim_context(
    messages: list[dict[str, Any]],
    keep_last: int = DEFAULT_KEEP_LAST,
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
) -> str:
    """Trim the oldest messages when the estimated context exceeds the model limit."""
    trimmed = _trim_messages(messages, keep_last=keep_last, max_context_tokens=max_context_tokens)
    return json.dumps(
        {
            "messages": trimmed,
            "original_count": len(messages),
            "trimmed_count": len(trimmed),
            "estimated_context_tokens": estimate_context_tokens(trimmed, max_context_tokens),
        },
        ensure_ascii=False,
    )


@server.tool()
def compact_context(
    messages: list[dict[str, Any]],
    keep_last: int = DEFAULT_KEEP_LAST,
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
    threshold: float = DEFAULT_THRESHOLD,
    summary: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    summary_budget_tokens: int = DEFAULT_SUMMARY_BUDGET_TOKENS,
    summary_role: str = "system",
    force: bool = False,
) -> str:
    """Replace the oldest messages with a summary instead of dropping them.

    The summary comes from ``summary`` when given, otherwise from the local model
    via ``model``/``base_url`` (or the OMLX_SHRINK_MODEL / OMLX_SHRINK_BASE_URL
    environment variables). With neither, the tool returns a ``needs_summary``
    plan plus the exact prompt, and no message content is echoed back.
    """
    tokens_before = _estimate_tokens(messages)
    threshold_tokens = int(max_context_tokens * threshold)
    leading, to_summarize, keep = _split_for_compaction(messages, keep_last)
    base = {
        "estimated_context_tokens": tokens_before,
        "max_context_tokens": max_context_tokens,
        "threshold_tokens": threshold_tokens,
        "message_count": len(messages),
    }

    if not to_summarize:
        return json.dumps({**base, "compacted": False, "reason": "nothing_to_compact"}, ensure_ascii=False)

    if not force and tokens_before <= threshold_tokens:
        return json.dumps({**base, "compacted": False, "reason": "within_threshold"}, ensure_ascii=False)

    method = "provided"
    used_summary = summary
    if used_summary is None:
        # model="" forces the plan-only step even when the environment sets a model
        resolved_model = model if model is not None else DEFAULT_MODEL
        if not resolved_model:
            return json.dumps(
                {
                    **base,
                    "compacted": False,
                    "needs_summary": True,
                    "to_summarize_count": len(to_summarize),
                    "keep_count": len(keep),
                    "summary_budget_tokens": summary_budget_tokens,
                    "summary_prompt": SUMMARY_INSTRUCTIONS,
                    "retry_hint": (
                        "Summarise the oldest part of your context yourself, then call "
                        "compact_context again with summary=<that text>, the same messages, "
                        "keep_last and summary_role."
                    ),
                },
                ensure_ascii=False,
            )
        try:
            used_summary = _summarize(
                to_summarize,
                base_url or DEFAULT_BASE_URL,
                api_key if api_key is not None else DEFAULT_API_KEY,
                resolved_model,
                max_context_tokens,
                summary_budget_tokens,
            )
            method = "model"
        except RuntimeError as error:
            logger.warning("compaction summariser failed: %s", error)
            return json.dumps(
                {
                    **base,
                    "compacted": False,
                    "needs_summary": True,
                    "error": str(error),
                    "to_summarize_count": len(to_summarize),
                    "keep_count": len(keep),
                    "summary_prompt": SUMMARY_INSTRUCTIONS,
                    "retry_hint": (
                        "The summariser call failed. Summarise the oldest part of your "
                        "context yourself, then call compact_context again with "
                        "summary=<that text>."
                    ),
                },
                ensure_ascii=False,
            )

    compacted = _assemble_compaction(leading, used_summary, keep, summary_role=summary_role)
    return json.dumps(
        {
            **base,
            "compacted": True,
            "method": method,
            "messages": compacted,
            "summary": used_summary,
            "summarized_count": len(to_summarize),
            "kept_count": len(keep),
            "estimated_context_tokens_after": _estimate_tokens(compacted),
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
