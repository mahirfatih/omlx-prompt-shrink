# omlx-prompt-shrink

An MCP server that keeps **oMLX / local Qwen** requests under the model's context
limit by measuring the context before the call and dropping the oldest messages
instead of letting the server reject the request.

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
single Python file, it needs no GPU, and it costs nothing at inference time —
there is no extra model call, only arithmetic on the message list you already
have.

You probably do not need it if your context window is large enough for your
sessions, or if your client already compacts history on its own.

## Tools

- `estimate_context` — approximate token count for a message list, the remaining
  budget and a `should_trim` flag.
- `trim_context` — returns the message list with the oldest messages dropped,
  keeping the most recent `keep_last` messages.

Token counting is an estimate: character count divided by 4. It is deliberately
tokenizer-free so the server stays dependency-light; treat it as a guard rail,
not an exact measurement.

Defaults match a 32K oMLX profile:

- `max_context_tokens`: `32768`
- `keep_last`: `8`

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

## Usage

- Call `estimate_context` with the current message list.
- If `should_trim` is `true`, call `trim_context` and send the returned list.
- An agent can do both automatically before every request when the estimate
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

## Notes

- Default context limit: `32768` tokens — change it to match your profile.
- Trim policy: oldest messages first; the last `keep_last` messages are always
  kept.
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
