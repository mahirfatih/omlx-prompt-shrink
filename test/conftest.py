"""Shared pytest fixtures.

The server lives in a single file whose name is not a valid Python module
identifier (``omlx-prompt-shrink.py``), so it is loaded by path. Each test gets a
fresh module instance, which also resets the lazily cached tokenizer.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "omlx-prompt-shrink.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("omlx_prompt_shrink", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def shrink() -> ModuleType:
    """A freshly imported server module, so the tokenizer cache is empty."""
    return _load_module()


@pytest.fixture(autouse=True)
def _force_heuristic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to the deterministic, dependency-free token counter."""
    monkeypatch.setenv("OMLX_SHRINK_TOKENIZER", "heuristic")
