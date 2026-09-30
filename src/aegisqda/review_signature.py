"""Local Ed25519 review signatures and key provisioning."""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

from .config import ROOT
from .errors import BoundaryError, IntegrityError
from .manifests import canonical_bytes, sha256_bytes
from .safeio import atomic_write, is_cloud_path, resolved_no_symlink


def _private_key(path: Path) -> Ed25519PrivateKey:
    key_path = resolved_no_symlink(path)
    if key_path.is_relative_to(ROOT) or is_cloud_path(key_path):
        raise BoundaryError("review signing keys must stay outside Git and cloud-sync paths")
    metadata = key_path.stat()
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise BoundaryError("review signing key must be owner-only mode 0600")
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise IntegrityError("review signing key is invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise IntegrityError("review signing key must be Ed25519")
    return key


def create_review_key(path: Path) -> tuple[Path, Path, str]:
    private_path = resolved_no_symlink(path, must_exist=False)
    if private_path.is_relative_to(ROOT) or is_cloud_path(private_path):
        raise BoundaryError("review signing keys must stay outside Git and cloud-sync paths")
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    public_path = private_path.with_suffix(private_path.suffix + ".pub")
    # The key file itself is 0600. An existing directory (possibly the home
    # directory) keeps its permissions; only a missing one is created 0700.
    if not private_path.parent.exists():
        private_path.parent.mkdir(mode=0o700, parents=True)
    atomic_write(private_path, private_bytes, secure_parent=False)
    atomic_write(public_path, base64.b64encode(public_bytes) + b"\n", secure_parent=False)
    return private_path, public_path, sha256_bytes(public_bytes)


def sign_review(payload: dict[str, Any], key_path: Path) -> dict[str, str]:
    key = _private_key(key_path)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    signature = key.sign(canonical_bytes(payload))
    return {
        "algorithm": "Ed25519",
        "public_key": base64.b64encode(public).decode("ascii"),
        "key_id_sha256": sha256_bytes(public),
        "signature": base64.b64encode(signature).decode("ascii"),
        "trust": "SELF_SIGNED_LOCAL",
    }


def verify_review_signature(review: dict[str, Any]) -> bool:
    signature = review.get("signature")
    if signature is None:
        return False
    if not isinstance(signature, dict) or signature.get("algorithm") != "Ed25519":
        raise IntegrityError("review signature metadata is invalid")
    try:
        public = base64.b64decode(str(signature["public_key"]), validate=True)
        signed = base64.b64decode(str(signature["signature"]), validate=True)
        if signature.get("key_id_sha256") != sha256_bytes(public):
            raise IntegrityError("review signing-key fingerprint is invalid")
        payload = {
            key: value
            for key, value in review.items()
            if key not in {"integrity_sha256", "signature"}
        }
        Ed25519PublicKey.from_public_bytes(public).verify(signed, canonical_bytes(payload))
    except (KeyError, ValueError, InvalidSignature) as exc:
        raise IntegrityError("review signature verification failed") from exc
    return True
