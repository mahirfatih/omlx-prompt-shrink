# omlx-prompt-shrink

An MCP server that keeps **oMLX / local Qwen** requests under the model's context
limit. It measures the context before the call, then either **drops** the oldest
messages or **compacts** them into a summary — instead of letting the server
reject the request.

## Why this exists

oMLX profiles for this class of models run **32K context** (`max_context_window:
32768`). That is a deliberate choice: with a 4-bit KV cache it keeps the runtime
footprint at roughly 17–20 GB per model and keeps prefill short on Apple Silicon.
Raising the limit is not free — every extra token of context is paid for in
memory and prefill time.

The cost appears in a long session. The system prompt, the conversation history
and the tool results accumulate, and once the total crosses the ceiling the
server refuses the whole request:

```text
Prompt is too long: 39514 tokens > 32768 maximum context length
```

At that point the agent stops. Nothing was wrong with the question — the prompt
was simply 6.7K tokens too big. The usual workarounds are all unsatisfying:

| Workaround | Why it falls short |
| :--- | :--- |
| Raise `max_context_window` | Moves the wall, does not remove it; costs memory and prefill speed on the same machine |
| Truncate by hand | Manual, easy to forget, throws away whole sessions |
| Start a new session | Loses the context that made the task work in the first place |

So this server takes the cheap path: **keep 32K, send a smaller prompt.**

## Recommendation

Use it if you run oMLX or another local OpenAI-compatible server with a fixed
context window and you have hit `Prompt is too long` at least once. It is a
single Python file and needs no GPU. `estimate_context` and `trim_context` are
pure arithmetic — they cost nothing at inference time. `compact_context` only
calls the local model when you ask it to summarise (or you can hand it a summary
yourself and it calls nothing at all).

You probably do not need it if your context window is large enough for your
sessions, or if your client already compacts history on its own.

## Tools

- `estimate_context` — approximate token count for a message list, the remaining
  budget and a `should_trim` flag.
- `trim_context` — returns the message list with the oldest messages dropped,
  keeping the most recent `keep_last` messages.
- `compact_context` — replaces the oldest messages with a **summary**, keeping
  the leading system messages and the most recent `keep_last` messages. The
  summary is either the `summary` you pass in, or one the server generates with
  the local model through the OpenAI-compatible endpoint.

Token counting is an estimate: character count divided by 4. It is deliberately
tokenizer-free so the server stays dependency-light; treat it as a guard rail,
not an exact measurement.

Defaults match a 32K oMLX profile:

- `max_context_tokens`: `32768`
- `keep_last`: `8`
- `threshold`: `0.8` (compact only when the estimate crosses 80% of the limit)

### `compact_context` in three modes

1. **Summary provided** — pass `summary="..."` and no model call is made. Use
   this when the agent (or the user) already wrote the summary.
2. **Model-generated** — pass `model="..."` (and optionally `base_url`), or set
   the environment variables below, and the server summarises the oldest
   messages for you. Long histories are summarised in chunks so the local model
   does not overflow while summarising.
3. **Plan only** — with neither, the call returns `needs_summary: true`, the
   exact `summary_prompt` to use, and the token counts. **No message content is
   echoed back**, so the result stays small; call again with `summary=<text>`.

`compact_context` returns the assembled `messages` list only in modes 1 and 2,
and leaves the list untouched (`compacted: false`) when it is already within
`threshold` unless you pass `force: true`.

## Install

1. Copy `server.py` into a directory of your choice.
2. Install the MCP SDK:

```bash
pip install mcp
```

3. Add the server to your OpenCode config (desktop or CLI):

```jsonc
{
  "mcp": {
    "omlx-prompt-shrink": {
      "type": "local",
      "enabled": true,
      "command": [
        "python3",
        "/absolute/path/to/server.py"
      ],
      "timeout": 60000
    }
  }
}
```

4. Restart OpenCode.
5. Select your local model (for example oMLX `Qwen3.6-35B-A3B-4bit`).

On macOS the system `/opt/homebrew/bin/python3` works; that is the interpreter the
server is tested against.

### Configuration

`compact_context` reads its endpoint and model from the environment when the
arguments are not given:

| Variable | Default | Meaning |
| :--- | :--- | :--- |
| `OMLX_SHRINK_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI-compatible base URL |
| `OMLX_SHRINK_MODEL` | *(empty)* | Model name to summarise with; empty disables the model mode |
| `OMLX_SHRINK_API_KEY` | *(empty)* | Bearer token, if the server needs one |
| `OMLX_SHRINK_TIMEOUT` | `180` | Summariser request timeout, seconds |

Add them under `environment` in the MCP entry if you want the model mode:

```jsonc
"environment": {
  "OMLX_SHRINK_MODEL": "Qwen3.6-35B-A3B-4bit"
}
```

## Usage

- Call `estimate_context` with the current message list.
- If `should_trim` is `true`, call `trim_context` and send the returned list, or
  `compact_context` to keep the gist instead of dropping it.
- An agent can do this automatically before every request when the estimate
  crosses the limit.

```json
{
  "messages": [
    { "role": "user", "content": "first message" },
    { "role": "assistant", "content": "first answer" },
    { "role": "user", "content": "second message" }
  ],
  "keep_last": 8,
  "max_context_tokens": 32768
}
```

Compaction flow, model mode:

```json
{
  "messages": [ "..." ],
  "keep_last": 8,
  "model": "Qwen3.6-35B-A3B-4bit",
  "base_url": "http://127.0.0.1:8000/v1"
}
```

Compaction flow, agent mode (two calls):

1. `compact_context({ "messages": [...], "force": true })` → `needs_summary: true`
   plus the `summary_prompt`.
2. The agent writes the summary, then calls again with
   `{ "messages": [...], "force": true, "summary": "<that text>" }` → the
   compacted `messages` list.

## Notes

- Default context limit: `32768` tokens — change it to match your profile.
- Trim policy: oldest messages first; the last `keep_last` messages are always
  kept.
- Compact policy: leading `system` messages are kept, the oldest of the rest are
  replaced by one `system` message holding the summary, and the last `keep_last`
  messages are kept verbatim.
- The tool surface is plain MCP, so any MCP client can use the server, not just
  OpenCode.

## Background

The 32K profile and the `Prompt is too long` failure this server addresses are
documented in
[`mahirfatih/omlx-m1-max-benchmark`](https://github.com/mahirfatih/omlx-m1-max-benchmark):
`docs/reference/PROFILES.md` explains why the context window is set to 32K, and
the README has the recommendation section for this server.

## License

MIT
