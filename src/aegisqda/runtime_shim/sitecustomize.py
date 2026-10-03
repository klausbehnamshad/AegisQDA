"""Adapter-scoped Ollama compatibility control for reasoning-capable models.

Python imports ``sitecustomize`` at process startup when this directory is the
explicit adapter PYTHONPATH. The pinned DigQDA runner otherwise leaves Ollama's
thinking mode at its model default; reasoning-capable models can then exhaust
num_predict in the thinking channel and return empty content instead of their
JSON envelope. The explicit false value is harmless for non-thinking models.
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from typing import Any
from urllib.parse import urlsplit

import ollama

def _local_client() -> ollama.Client:
    """Establish the bound transport before the pinned runner can load data."""
    endpoint = os.environ.get("OLLAMA_HOST", "")
    approved_model = os.environ.get("AEGISQDA_APPROVED_MODEL", "")
    approved_digest = os.environ.get("AEGISQDA_APPROVED_MODEL_DIGEST", "")
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http" or parsed.hostname is None
            or not ipaddress.ip_address(parsed.hostname).is_loopback
            or "%" in parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or parsed.port is None or not 1 <= parsed.port <= 65535
            or approved_model not in {"gemma3:4b", "gemma4:e4b"}
            or re.fullmatch(r"[0-9a-f]{64}", approved_digest) is None
            or os.environ.get("OLLAMA_API_KEY")
        ):
            raise ValueError("invalid runtime boundary")
        return ollama.Client(host=endpoint, follow_redirects=False, trust_env=False, timeout=3600.0)
    except Exception:
        # Python normally logs a sitecustomize import error and continues.
        # SystemExit instead makes initialization fail before source ingestion.
        sys.exit("AegisQDA local runtime transport boundary could not be established")


_bound_client = _local_client()


def _require_model(args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    model = kwargs.get("model", args[0] if args else None)
    if model != os.environ["AEGISQDA_APPROVED_MODEL"]:
        raise RuntimeError("AegisQDA requires the approved exact local model")


def _chat_without_thinking(*args: Any, **kwargs: Any) -> Any:
    _require_model(args, kwargs)
    requested = kwargs.get("think", False)
    if requested is not False:
        raise RuntimeError("AegisQDA requires Ollama think=false for bound JSON output")
    kwargs["think"] = False
    return _bound_client.chat(*args, **kwargs)


def _bound_show(*args: Any, **kwargs: Any) -> Any:
    _require_model(args, kwargs)
    return _bound_client.show(*args, **kwargs)


def _bound_list() -> Any:
    inventory = _bound_client.list()
    models = inventory.get("models")
    if not isinstance(models, list):
        raise RuntimeError("AegisQDA local model inventory is invalid")
    observed: dict[str, str] = {}
    for entry in models:
        tag = entry.get("model") or entry.get("name")
        digest = entry.get("digest")
        if (
            not isinstance(tag, str) or not tag or tag in observed
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise RuntimeError("AegisQDA local model inventory is ambiguous or incomplete")
        observed[tag] = digest
    if observed.get(os.environ["AEGISQDA_APPROVED_MODEL"]) != os.environ["AEGISQDA_APPROVED_MODEL_DIGEST"]:
        raise RuntimeError("AegisQDA local model inventory differs from the approved model pair")
    return inventory


ollama.chat = _chat_without_thinking
ollama.show = _bound_show
ollama.list = _bound_list
