# Test

Local test runner for oMLX Prompt Shrink. Everything is one command; there is no
device matrix and nothing to install beyond the dev dependencies.

Strategy and conventions live in [`CONTRIBUTING.md`](../CONTRIBUTING.md); the
suite itself is described in the [README](../README.md#-testing--ci).

## Contents

| Path | Purpose |
| :--- | :--- |
| [`test.sh`](./test.sh) | Single test runner. Installs dev deps, runs Ruff, then pytest. |
| [`conftest.py`](./conftest.py) | Shared fixtures. Loads the server module by path and forces the deterministic token counter. |
| [`omlx-prompt-shrink-tests.py`](./omlx-prompt-shrink-tests.py) | Unit tests for the pure helpers and the tokenizer resolution logic. |

## Quick start

```bash
./test/test.sh                                   # install deps + ruff + pytest
./test/test.sh --lint                            # ruff only
./test/test.sh --no-install                      # skip the pip install step
./test/test.sh --only test/omlx-prompt-shrink-tests.py::test_compact_uses_provided_summary
./test/test.sh --help                            # full flag list
```

A bare `./test/test.sh` is what you run while working and before a commit. The
interpreter is the project `.venv` when present, otherwise `python3` (override
with `PYTHON`). Tests never touch the network: the optional tokenizer is faked
and the summariser endpoint is never called.

## Outputs

pytest writes its cache to `.pytest_cache/` (gitignored). Ruff writes to
`.ruff_cache/` (gitignored). Nothing else is produced.

## Further reading

- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — setup, tests and commit conventions
- [`README.md`](../README.md) — install, tools and the three compaction modes
