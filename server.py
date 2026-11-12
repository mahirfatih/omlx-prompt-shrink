#!/usr/bin/env python3
"""oMLX context guard MCP server."""

import asyncio
import json
import logging
import math
import sys
from typing import Any

from mcp.server import MCPServer

MAX_CONTEXT_TOKENS = 32768
DEFAULT_KEEP_LAST = 8
logger = logging.getLogger("omlx-prompt-shrink")
logger.addHandler(logging.StreamHandler(sys.stderr))
logger.setLevel(logging.INFO)

server = MCPServer("omlx-prompt-shrink")


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


@server.tool()
def estimate_context(
    messages: list[dict[str, Any]],
    max_context_tokens: int = MAX_CONTEXT_TOKENS,
) -> str:
    """Estimate the current context size in tokens before sending it to the model."""
    estimated = _estimate_tokens(messages)
    return json.dumps(
        {
            "estimated_context_tokens": estimated,
            "max_context_tokens": max_context_tokens,
            "remaining_tokens": max_context_tokens - estimated,
            "should_trim": estimated > max_context_tokens,
            "message_count": len(messages),
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


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
