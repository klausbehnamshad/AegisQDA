"""Strict SRT/TXT parsing with content regions and structural fingerprints."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from aegisqda.errors import IntegrityError

TIMING_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3}) --> (?P<end>\d{2}:\d{2}:\d{2},\d{3})$"
)


@dataclass(frozen=True)
class Region:
    start: int
    end: int


@dataclass(frozen=True)
class Document:
    kind: str
    text: str
    regions: tuple[Region, ...]
    fingerprint: dict[str, object]


def _newline_style(text: str) -> str:
    has_crlf = "\r\n" in text
    remainder = text.replace("\r\n", "")
    if "\r" in remainder or (has_crlf and "\n" in remainder):
        raise IntegrityError("mixed or bare-CR newlines are unsupported")
    return "CRLF" if has_crlf else "LF"


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    result: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.removesuffix("\n").removesuffix("\r")
        result.append((offset, offset + len(content), content))
        offset += len(line)
    if not text or (text and not text.endswith(("\n", "\r"))):
        if not result:
            result.append((0, 0, ""))
    return result


def _parse_srt(text: str) -> Document:
    lines = _line_spans(text)
    regions: list[Region] = []
    headers: list[tuple[str, str]] = []
    index = 0
    expected_cue = 1
    while index < len(lines):
        while index < len(lines) and not lines[index][2]:
            index += 1
        if index >= len(lines):
            break
        cue = lines[index][2]
        if not cue.isdigit() or int(cue) != expected_cue:
            raise IntegrityError("malformed SRT cue sequence")
        index += 1
        if index >= len(lines) or not TIMING_RE.fullmatch(lines[index][2]):
            raise IntegrityError("malformed SRT timing line")
        timing = lines[index][2]
        headers.append((cue, timing))
        index += 1
        content_count = 0
        while index < len(lines) and lines[index][2]:
            start, end, _ = lines[index]
            if end > start:
                regions.append(Region(start, end))
            content_count += 1
            index += 1
        if content_count == 0:
            raise IntegrityError("SRT cues require at least one content line")
        expected_cue += 1
    if not headers:
        raise IntegrityError("SRT contains no cues")
    return Document(
        kind="srt",
        text=text,
        regions=tuple(regions),
        fingerprint={
            "kind": "srt",
            "newline_style": _newline_style(text),
            "terminal_newline": text.endswith("\n"),
            "line_count": len(lines),
            "cue_headers_sha256": hashlib.sha256(repr(headers).encode()).hexdigest(),
            "cue_count": len(headers),
            "content_line_count": len(regions),
        },
    )


def _parse_txt(text: str) -> Document:
    lines = _line_spans(text)
    regions = tuple(Region(start, end) for start, end, _ in lines if end > start)
    if not text.strip():
        raise IntegrityError("TXT source cannot be empty")
    return Document(
        kind="txt",
        text=text,
        regions=regions,
        fingerprint={
            "kind": "txt",
            "newline_style": _newline_style(text),
            "terminal_newline": text.endswith("\n"),
            "line_count": len(lines),
            "blank_line_positions": [i for i, (_, _, value) in enumerate(lines) if not value],
        },
    )


def parse_document_bytes(raw: bytes, suffix: str) -> Document:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError("source must be readable UTF-8") from exc
    if "\x00" in text:
        raise IntegrityError("NUL bytes are forbidden")
    if suffix.lower() == ".srt":
        return _parse_srt(text)
    if suffix.lower() == ".txt":
        return _parse_txt(text)
    raise IntegrityError("unsupported source format")


def parse_document(path: Path) -> Document:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IntegrityError("source must be readable UTF-8") from exc
    return parse_document_bytes(raw, path.suffix)


def fingerprint_text(text: str, kind: str) -> dict[str, object]:
    temporary = Path("source.srt" if kind == "srt" else "source.txt")
    return _parse_srt(text).fingerprint if temporary.suffix == ".srt" else _parse_txt(text).fingerprint
