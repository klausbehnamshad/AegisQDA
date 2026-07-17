"""Adapter-scoped Ollama compatibility control for reasoning-capable models.

Python imports ``sitecustomize`` at process startup when this directory is the
explicit adapter PYTHONPATH. The pinned DigQDA runner otherwise leaves Ollama's
thinking mode at its model default; reasoning-capable models can then exhaust
num_predict in the thinking channel and return empty content instead of their
JSON envelope. The explicit false value is harmless for non-thinking models.
"""

from __future__ import annotations

from typing import Any

import ollama

_original_chat = ollama.chat


def _chat_without_thinking(*args: Any, **kwargs: Any) -> Any:
    requested = kwargs.get("think", False)
    if requested is not False:
        raise RuntimeError("AegisQDA requires Ollama think=false for bound JSON output")
    kwargs["think"] = False
    return _original_chat(*args, **kwargs)


ollama.chat = _chat_without_thinking
