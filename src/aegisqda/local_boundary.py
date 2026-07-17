"""Loopback-only endpoint, proxy, Ollama, and upstream checks."""

from __future__ import annotations

import hashlib
import importlib.metadata
import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .config import AppConfig, ROOT
from .errors import BoundaryError, IntegrityError

PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def reject_proxy_environment(environment: dict[str, str] | None = None) -> None:
    env = os.environ if environment is None else environment
    active = sorted(key for key in PROXY_VARIABLES if env.get(key))
    if active:
        raise BoundaryError("active proxy environment is forbidden: " + ", ".join(active))


def validate_loopback_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise BoundaryError("Ollama URL must be unauthenticated loopback HTTP")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise BoundaryError("Ollama base URL cannot contain a path, query, or fragment")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
    except socket.gaierror as exc:
        raise BoundaryError("Ollama host cannot be resolved") from exc
    if not addresses or not all(ipaddress.ip_address(address).is_loopback for address in addresses):
        raise BoundaryError("Ollama endpoint is not exclusively loopback")
    return value.rstrip("/")


def ollama_models(base_url: str, *, timeout: float = 2.0) -> dict[str, str]:
    base_url = validate_loopback_url(base_url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base_url + "/api/tags", method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise BoundaryError("local Ollama is unavailable or returned invalid model metadata") from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise BoundaryError("local Ollama model metadata has an unexpected schema")
    result: dict[str, str] = {}
    for item in models:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            digest = item.get("digest")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                result[item["name"]] = digest
    return result


def package_versions() -> dict[str, str]:
    packages = ("presidio-analyzer", "presidio-anonymizer", "spacy", "pydantic", "PyYAML")
    result: dict[str, str] = {}
    for package in packages:
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "MISSING"
    return result


def locked_dependency_drift(lock_path: Path) -> list[str]:
    drift: list[str] = []
    try:
        lines = lock_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IntegrityError("dependency lock cannot be read") from exc
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if "==" in value:
            package, expected = value.split("==", 1)
        else:
            direct = re.fullmatch(
                r"(?P<package>[A-Za-z0-9_.-]+) @ https://[^#]+-"
                r"(?P<version>\d+(?:\.\d+)+)-py3-none-any\.whl#sha256=[0-9a-f]{64}",
                value,
            )
            if direct is None:
                raise IntegrityError("dependency lock contains an unpinned entry")
            package, expected = direct.group("package"), direct.group("version")
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "MISSING"
        if actual != expected:
            drift.append(f"{package}: expected {expected}, observed {actual}")
    return drift


def normalized_snapshot_hash(snapshot: Path) -> str:
    lines: list[bytes] = []
    for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
        relative = path.relative_to(ROOT).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n".encode())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def verify_upstream(config: AppConfig) -> str:
    snapshot = (ROOT / config.digqda.snapshot).resolve()
    lock_path = (ROOT / config.digqda.lock).resolve()
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("upstream lock cannot be read") from exc
    expected = lock.get("snapshot_manifest_sha256") if isinstance(lock, dict) else None
    actual = normalized_snapshot_hash(snapshot)
    if expected != actual:
        raise IntegrityError("pinned DigQDA snapshot does not match its lock")
    return actual
