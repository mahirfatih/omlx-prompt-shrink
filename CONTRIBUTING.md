# Contributing

Thanks for your interest in **oMLX Prompt Shrink**. This is a small, dependency-light
MCP server, so the contribution surface is intentionally narrow.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # mcp + pytest + ruff + tiktoken
```

## Running the checks

```bash
ruff check .   # lint
pytest -q      # unit tests
```

Both run in CI (`.github/workflows/ci.yml`) on every push and pull request.

## The server

Everything ships in a single file, `omlx-prompt-shrink.py`. Keep it that way:

- Standard library only at runtime, except the required `mcp` SDK.
- `tiktoken` must stay **optional** — import it defensively and fall back to the
  character heuristic when it is missing or fails to load.
- New behaviour belongs in a pure helper (easy to unit-test) with the MCP tool
  acting as a thin JSON wrapper.

## Tests

Add tests under `tests/`. The server module is loaded by path (its filename is
not a valid Python identifier), and each test gets a fresh module instance, so
the lazily cached tokenizer resets automatically. Never call the network in a
test — mock the tokenizer or the summariser endpoint instead.

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short imperative summary>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`. Keep
each commit to one logical change.

## Syncing a local OpenCode install

If you run the server from OpenCode, keep the deployed copy in step with the
repository (for example by copying or symlinking the file):

```bash
cp omlx-prompt-shrink.py ~/.config/opencode/mcp/omlx-prompt-shrink.py
```

OpenCode reloads MCP servers when configuration changes; run `/reload` in the TUI
if a code-only change does not take effect.
