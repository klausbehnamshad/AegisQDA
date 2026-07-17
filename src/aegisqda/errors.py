"""Typed, non-sensitive failures for the fail-closed CLI."""

from __future__ import annotations


class AegisError(Exception):
    """Expected gate failure whose message must not contain source text."""

    exit_code = 2


class BoundaryError(AegisError):
    """A local-only or filesystem boundary was violated."""


class IntegrityError(AegisError):
    """A protected artifact failed integrity or state validation."""


class ReviewRequired(AegisError):
    """Human review is required before processing can continue."""


class UnsupportedLanguage(AegisError):
    """The requested language has no approved, ready recognizer pack."""


class DownstreamBlocked(AegisError):
    """DigQDA invocation is not authorized by the privacy gate."""
